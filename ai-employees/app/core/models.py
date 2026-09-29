"""Task、実行結果、Agentの利用量を表すモデルを定義する。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from app.core.baseline import BaselineRequirement, ConcreteGoal


T = TypeVar("T")  # AgentResultで包む成果物の型


@dataclass(frozen=True, slots=True)
class Task:
    """Review Loopへ渡すTaskを表す。"""

    task_id: str
    goal: str
    baseline_requirements: tuple[BaselineRequirement, ...] = ()
    concrete_goal: ConcreteGoal | None = None
    dependencies_complete: bool = True


@dataclass(frozen=True, slots=True)
class Plan:
    """Workerが作成した計画を表す。"""

    content: str


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Workerの実行結果と変更ファイル一覧を表す。"""

    content: str
    changed_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentMetrics:
    """Agentの1回の応答で観測したturn数とtool call数を表す。"""

    turns: int = 1
    tool_calls: int = 0
    session_id: str | None = None
    cost_usd: float | None = None


@dataclass(frozen=True, slots=True)
class AgentResult(Generic[T]):
    """Agentの成果物と利用量をまとめる。"""

    value: T
    metrics: AgentMetrics = AgentMetrics()


@dataclass(frozen=True, slots=True)
class TaskResult:
    """Review Loopの最終状態を返す。"""

    task_id: str
    state: str
    reason: str | None
    restart_count: int
    plan: Plan | None = None
    execution: ExecutionResult | None = None
    history: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LoopEvent:
    """Review Loopの状態変更とAgent応答を永続化するイベント。"""

    event_type: str
    state: str
    reason: str | None
    restart_count: int
    history: tuple[str, ...]
    plan: Plan | None = None
    execution: ExecutionResult | None = None
    review_target: str | None = None
    review: object | None = None
    agent_id: str | None = None
    phase: str | None = None
    metrics: AgentMetrics | None = None


LoopEventHandler = Callable[[LoopEvent], None]  # LoopEventを同期保存するcallback
