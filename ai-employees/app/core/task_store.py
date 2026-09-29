"""TaskとReview LoopイベントをSQLiteへ保存する。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from collections.abc import Iterator

from app.core.baseline import BaselineRequirement, ConcreteGoal
from app.core.models import ExecutionResult, LoopEvent, Plan, Task
from app.core.state_machine import TaskState, TaskStateMachine


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """SQLiteから読み込んだTaskの最新状態を表す。"""

    task: Task
    state: str
    reason: str | None
    restart_count: int
    history: tuple[str, ...]
    plan: Plan | None
    execution: ExecutionResult | None
    running: bool
    created_at: str
    updated_at: str


class TaskAlreadyRunningError(RuntimeError):
    """同じTaskが実行中であることを表す。"""


class TaskStateConflictError(RuntimeError):
    """Taskの現在状態では要求された操作ができないことを表す。"""


class TaskStore:
    """Taskの最新状態と追記型イベント履歴を保存する。"""

    def __init__(self, database_path: Path) -> None:
        """SQLiteファイルの保存先を設定する。"""
        self.database_path = database_path

    def initialize(self) -> None:
        """保存先と初期テーブルを準備する。"""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    task_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    reason TEXT,
                    restart_count INTEGER NOT NULL DEFAULT 0,
                    history_json TEXT NOT NULL,
                    plan_json TEXT,
                    execution_json TEXT,
                    running INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    attempt_id TEXT,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_task_events_task_id
                    ON task_events(task_id, event_id);
                """
            )

    def create(self, task: Task) -> None:
        """新しいTaskと作成イベントを保存する。"""
        timestamp = self._now()
        with self._connection() as connection, connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, task_json, state, history_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    self._dump(task),
                    TaskState.TASK_RECEIVED.value,
                    self._dump((TaskState.TASK_RECEIVED.value,)),
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(
                connection, task.task_id, None, "task_created", {"task": task}
            )

    def get(self, task_id: str) -> TaskRecord | None:
        """Taskの最新状態を取得する。"""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        return self._record(row) if row else None

    def list(self, limit: int = 100) -> tuple[TaskRecord, ...]:
        """更新日時の新しい順にTaskを取得する。"""
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return tuple(self._record(row) for row in rows)

    def events(self, task_id: str) -> tuple[dict[str, object], ...]:
        """Taskに記録されたイベントを時系列で取得する。"""
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, event_type, payload_json, created_at
                FROM task_events WHERE task_id = ? ORDER BY event_id
                """,
                (task_id,),
            ).fetchall()
        return tuple(
            {
                "attempt_id": row["attempt_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        )

    def start_attempt(
        self, task_id: str, attempt_id: str, *, resume: bool
    ) -> Task:
        """実行権を取得し、新しい実行履歴を開始する。"""
        timestamp = self._now()
        with self._connection() as connection, connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["running"]:
                raise TaskAlreadyRunningError(task_id)

            current = TaskState(row["state"])
            if resume:
                if current is not TaskState.HUMAN_REQUIRED:
                    raise TaskStateConflictError("HUMAN_REQUIREDのTaskだけ再開できます")
                TaskStateMachine().transition(current, TaskState.TASK_RECEIVED)
            elif current is not TaskState.TASK_RECEIVED:
                raise TaskStateConflictError("TASK_RECEIVEDのTaskだけ実行できます")

            changed = connection.execute(
                """
                UPDATE tasks SET state = ?, reason = NULL, restart_count = 0,
                    history_json = ?, running = 1, updated_at = ?
                WHERE task_id = ? AND running = 0
                """,
                (
                    TaskState.TASK_RECEIVED.value,
                    self._dump((TaskState.TASK_RECEIVED.value,)),
                    timestamp,
                    task_id,
                ),
            ).rowcount
            if changed != 1:
                raise TaskAlreadyRunningError(task_id)

            task = self._task_from_json(row["task_json"])
            self._append_event(
                connection,
                task_id,
                attempt_id,
                "attempt_started",
                {"resumed_from": current.value if resume else None},
            )
        return task

    def update_progress(self, task_id: str, attempt_id: str, event: LoopEvent) -> None:
        """Loop状態とAgent応答を同一transactionで保存する。"""
        timestamp = self._now()
        with self._connection() as connection, connection:
            changed = connection.execute(
                """
                UPDATE tasks SET state = ?, reason = ?, restart_count = ?,
                    history_json = ?, plan_json = ?, execution_json = ?, updated_at = ?
                WHERE task_id = ? AND running = 1
                """,
                (
                    event.state,
                    event.reason,
                    event.restart_count,
                    self._dump(event.history),
                    self._dump(event.plan) if event.plan is not None else None,
                    (
                        self._dump(event.execution)
                        if event.execution is not None
                        else None
                    ),
                    timestamp,
                    task_id,
                ),
            ).rowcount
            if changed != 1:
                raise TaskStateConflictError("実行中Taskの状態を保存できません")
            self._append_event(
                connection, task_id, attempt_id, event.event_type, event
            )

    def finish(self, task_id: str, attempt_id: str, result) -> None:
        """Review Loopの終了状態と結果を保存する。"""
        timestamp = self._now()
        with self._connection() as connection, connection:
            changed = connection.execute(
                """
                UPDATE tasks SET state = ?, reason = ?, restart_count = ?,
                    history_json = ?, plan_json = ?, execution_json = ?, running = 0,
                    updated_at = ?
                WHERE task_id = ? AND running = 1
                """,
                (
                    result.state,
                    result.reason,
                    result.restart_count,
                    self._dump(result.history),
                    self._dump(result.plan) if result.plan is not None else None,
                    (
                        self._dump(result.execution)
                        if result.execution is not None
                        else None
                    ),
                    timestamp,
                    task_id,
                ),
            ).rowcount
            if changed != 1:
                raise TaskStateConflictError("実行中Taskの結果を保存できません")
            self._append_event(
                connection, task_id, attempt_id, "attempt_finished", result
            )

    def mark_interrupted(
        self, task_id: str, attempt_id: str, reason: str
    ) -> None:
        """停止要求や実行中断をHuman Requiredとして保存する。"""
        timestamp = self._now()
        with self._connection() as connection, connection:
            row = connection.execute(
                "SELECT state, history_json FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None or not row["running"]:
                return
            current = TaskState(row["state"])
            history = list(json.loads(row["history_json"]))
            if current is not TaskState.HUMAN_REQUIRED:
                TaskStateMachine().transition(current, TaskState.HUMAN_REQUIRED)
                current = TaskState.HUMAN_REQUIRED
                history.append(current.value)
            connection.execute(
                """
                UPDATE tasks SET state = ?, reason = ?, history_json = ?,
                    running = 0, updated_at = ? WHERE task_id = ?
                """,
                (
                    current.value,
                    reason,
                    self._dump(tuple(history)),
                    timestamp,
                    task_id,
                ),
            )
            self._append_event(
                connection,
                task_id,
                attempt_id,
                "attempt_interrupted",
                {"state": current.value, "reason": reason, "history": history},
            )

    def recover_interrupted(self) -> tuple[str, ...]:
        """前回プロセスで実行中だったTaskを自動再実行せず停止する。"""
        timestamp = self._now()
        recovered: list[str] = []
        with self._connection() as connection, connection:
            rows = connection.execute(
                "SELECT task_id, state, history_json FROM tasks WHERE running = 1"
            ).fetchall()
            for row in rows:
                current = TaskState(row["state"])
                if current in {
                    TaskState.TASK_RECEIVED,
                    TaskState.WAITING_DEPENDENCY,
                    TaskState.PLAN_DRAFT,
                    TaskState.PLAN_REVIEW,
                    TaskState.EXECUTE,
                    TaskState.RESULT_REVIEW,
                }:
                    TaskStateMachine().transition(current, TaskState.HUMAN_REQUIRED)
                    history = list(json.loads(row["history_json"]))
                    history.append(TaskState.HUMAN_REQUIRED.value)
                    connection.execute(
                        """
                        UPDATE tasks SET state = ?, reason = ?, history_json = ?,
                            running = 0, updated_at = ? WHERE task_id = ?
                        """,
                        (
                            TaskState.HUMAN_REQUIRED.value,
                            "PROCESS_RESTARTED_REQUIRES_REVIEW",
                            self._dump(tuple(history)),
                            timestamp,
                            row["task_id"],
                        ),
                    )
                    reason = "PROCESS_RESTARTED_REQUIRES_REVIEW"
                else:
                    connection.execute(
                        "UPDATE tasks SET running = 0, updated_at = ? WHERE task_id = ?",
                        (timestamp, row["task_id"]),
                    )
                    reason = "PROCESS_RESTARTED_AFTER_TERMINAL_STATE"
                self._append_event(
                    connection,
                    row["task_id"],
                    None,
                    "process_recovery",
                    {"state": row["state"], "reason": reason},
                )
                recovered.append(row["task_id"])
        return tuple(recovered)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """SQLite接続を開き、処理後に確実に閉じる。"""
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _record(row: sqlite3.Row) -> TaskRecord:
        """SQLite行をTaskRecordへ変換する。"""
        return TaskRecord(
            task=TaskStore._task_from_json(row["task_json"]),
            state=row["state"],
            reason=row["reason"],
            restart_count=row["restart_count"],
            history=tuple(json.loads(row["history_json"])),
            plan=Plan(**json.loads(row["plan_json"])) if row["plan_json"] else None,
            execution=(
                ExecutionResult(**json.loads(row["execution_json"]))
                if row["execution_json"]
                else None
            ),
            running=bool(row["running"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _task_from_json(value: str) -> Task:
        """Task JSONを不変モデルへ復元する。"""
        data = json.loads(value)
        concrete_goal = data.get("concrete_goal")
        return Task(
            task_id=data["task_id"],
            goal=data["goal"],
            baseline_requirements=tuple(
                BaselineRequirement(**item)
                for item in data["baseline_requirements"]
            ),
            concrete_goal=(
                ConcreteGoal(
                    text=concrete_goal["text"],
                    completion_conditions=tuple(
                        concrete_goal.get("completion_conditions", ())
                    ),
                )
                if concrete_goal is not None
                else None
            ),
            dependencies_complete=data.get("dependencies_complete", True),
        )

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        task_id: str,
        attempt_id: str | None,
        event_type: str,
        payload: object,
    ) -> None:
        """イベントをTask状態と同じtransactionへ追記する。"""
        connection.execute(
            """
            INSERT INTO task_events (
                task_id, attempt_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                task_id,
                attempt_id,
                event_type,
                TaskStore._dump(payload),
                TaskStore._now(),
            ),
        )

    @staticmethod
    def _dump(value: object) -> str:
        """DataclassとEnumをJSONへ変換する。"""
        return json.dumps(
            value,
            ensure_ascii=False,
            default=TaskStore._json_default,
            separators=(",", ":"),
        )

    @staticmethod
    def _json_default(value: object) -> object:
        """JSONが直接扱えない型を基本値へ変換する。"""
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, Enum):
            return value.value
        raise TypeError(f"JSONへ変換できません: {type(value).__name__}")

    @staticmethod
    def _now() -> str:
        """UTCの現在時刻をISO 8601形式で返す。"""
        return datetime.now(timezone.utc).isoformat()
