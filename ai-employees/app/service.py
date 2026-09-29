"""永続TaskをReviewLoopRunnerとOpenClaw社員へ接続する。"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from enum import Enum
import os
from pathlib import Path
import uuid

from app.agents.openclaw import (
    OpenClawClient,
    OpenClawReviewerAgent,
    OpenClawWorkerAgent,
)
from app.core.baseline import (
    BaselineRequirement,
    BaselineValidationError,
    validate_baseline_requirements,
)
from app.core.review_loop import ReviewLoopRunner
from app.core.task_store import (
    TaskAlreadyRunningError,
    TaskRecord,
    TaskStateConflictError,
    TaskStore,
)
from app.core.models import Task


class TaskService:
    """Task APIの保存・実行・停止・再開をまとめる。"""

    def __init__(
        self,
        project_root: Path | None = None,
        store: TaskStore | None = None,
    ) -> None:
        """DBとOpenClaw CLIのプロジェクトルートを設定する。"""
        self.project_root = (
            project_root or Path(__file__).resolve().parents[2]
        ).resolve()
        database_path = os.environ.get("RLC_DB_PATH")
        if store is not None:
            self.store = store
        else:
            path = (
                Path(database_path)
                if database_path
                else self.project_root / ".openclaw" / "rlc" / "tasks.sqlite3"
            )
            if not path.is_absolute():
                path = self.project_root / path
            self.store = TaskStore(path)
        self._jobs: dict[str, tuple[asyncio.Task[None], str]] = {}
        self._jobs_lock = asyncio.Lock()

    def startup(self) -> tuple[str, ...]:
        """DBを準備し、前回プロセスの中断TaskをHuman Requiredにする。"""
        self.store.initialize()
        return self.store.recover_interrupted()

    async def shutdown(self) -> None:
        """終了時に実行中Agentを停止し、曖昧なTaskを人へ戻す。"""
        async with self._jobs_lock:
            jobs = tuple(self._jobs.items())
            for _, (job, _) in jobs:
                job.cancel()
        if jobs:
            await asyncio.gather(
                *(job for _, (job, _) in jobs), return_exceptions=True
            )
        for task_id, (_, attempt_id) in jobs:
            self.store.mark_interrupted(
                task_id, attempt_id, "SERVICE_SHUTDOWN_REQUIRES_REVIEW"
            )

    def create_task(self, goal: str, requirements: list[dict[str, str]]) -> str:
        """固定Baselineを保持するTaskを新規登録する。"""
        normalized_goal = goal.strip()
        if not normalized_goal:
            raise BaselineValidationError("Goalは空にできません")
        baseline = validate_baseline_requirements(
            tuple(BaselineRequirement(**item) for item in requirements)
        )
        task_id = f"task-{uuid.uuid4()}"
        task = Task(
            task_id=task_id,
            goal=normalized_goal,
            baseline_requirements=baseline,
        )
        self.store.create(task)
        return task_id

    async def start(self, task_id: str, *, resume: bool = False) -> str:
        """Taskの実行またはHuman Requiredからの明示再開を予約する。"""
        async with self._jobs_lock:
            active = self._jobs.get(task_id)
            if active is not None and not active[0].done():
                raise TaskAlreadyRunningError(task_id)
            attempt_id = str(uuid.uuid4())
            task = self.store.start_attempt(task_id, attempt_id, resume=resume)
            client = OpenClawClient(self.project_root)
            worker = OpenClawWorkerAgent(client, self.project_root)
            reviewer = OpenClawReviewerAgent(client, self.project_root)
            runner = ReviewLoopRunner()
            job = asyncio.create_task(
                self._execute(task, attempt_id, runner, worker, reviewer)
            )
            self._jobs[task_id] = (job, attempt_id)
            return attempt_id

    async def stop(self, task_id: str) -> None:
        """Taskの実行を中断し、再実行前の確認を要求する。"""
        async with self._jobs_lock:
            active = self._jobs.get(task_id)
            if active is None or active[0].done():
                raise TaskStateConflictError("実行中のTaskではありません")
            job, attempt_id = active
            job.cancel()
        await asyncio.gather(job, return_exceptions=True)
        self.store.mark_interrupted(task_id, attempt_id, "STOP_REQUESTED_REQUIRES_REVIEW")

    def get(self, task_id: str) -> dict[str, object] | None:
        """Taskの最新状態をAPI向けJSON形式で取得する。"""
        record = self.store.get(task_id)
        if record is None:
            return None
        return self._record_view(record)

    def list(self, limit: int) -> list[dict[str, object]]:
        """更新日時の新しい順にTask一覧を取得する。"""
        return [self._record_view(record) for record in self.store.list(limit)]

    def get_events(self, task_id: str) -> tuple[dict[str, object], ...] | None:
        """Taskイベントを時系列で取得する。"""
        if self.store.get(task_id) is None:
            return None
        return self.store.events(task_id)

    async def _execute(
        self,
        task: Task,
        attempt_id: str,
        runner: ReviewLoopRunner,
        worker: OpenClawWorkerAgent,
        reviewer: OpenClawReviewerAgent,
    ) -> None:
        """Review Loopを実行し、完了または中断をSQLiteへ記録する。"""
        try:
            result = await runner.run(
                worker,
                reviewer,
                task,
                on_event=lambda event: self.store.update_progress(
                    task.task_id, attempt_id, event
                ),
            )
            self.store.finish(task.task_id, attempt_id, result)
        except asyncio.CancelledError:
            self.store.mark_interrupted(
                task.task_id, attempt_id, "STOP_REQUESTED_REQUIRES_REVIEW"
            )
        except Exception:
            self.store.mark_interrupted(
                task.task_id, attempt_id, "RUNTIME_ERROR_REQUIRES_REVIEW"
            )
        finally:
            async with self._jobs_lock:
                active = self._jobs.get(task.task_id)
                if active is not None and active[1] == attempt_id:
                    self._jobs.pop(task.task_id, None)

    @staticmethod
    def _record_view(record: TaskRecord) -> dict[str, object]:
        """TaskRecordをAPI応答で扱える辞書へ変換する。"""
        return {
            "task": TaskService._jsonable(record.task),
            "state": record.state,
            "reason": record.reason,
            "restart_count": record.restart_count,
            "history": list(record.history),
            "plan": TaskService._jsonable(record.plan),
            "execution": TaskService._jsonable(record.execution),
            "running": record.running,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @staticmethod
    def _jsonable(value: object) -> object:
        """Dataclass、Enum、tupleをJSON互換値へ変換する。"""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return TaskService._jsonable(asdict(value))
        if isinstance(value, dict):
            return {
                str(key): TaskService._jsonable(item)
                for key, item in value.items()
            }
        if isinstance(value, (tuple, list)):
            return [TaskService._jsonable(item) for item in value]
        return str(value)
