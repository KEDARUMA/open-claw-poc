"""Review Loopが利用するWorkerとReviewerの非同期Protocolを定義する。"""

from __future__ import annotations

from typing import Protocol

from app.core.models import AgentMetrics, AgentResult, ExecutionResult, Plan, Task
from app.core.review_models import ReviewResult


class ReviewerError(RuntimeError):
    """ReviewerのJSON出力またはsession実行異常を表す。"""

    def __init__(
        self, message: str, metrics: AgentMetrics | None = None
    ) -> None:
        """異常内容と、取得できた場合は応答利用量を保持する。"""
        super().__init__(message)
        self.metrics = metrics


class WorkerError(RuntimeError):
    """Workerの回復不能な実行異常を表す。"""

    def __init__(
        self, message: str, metrics: AgentMetrics | None = None
    ) -> None:
        """異常内容と、取得できた場合は応答利用量を保持する。"""
        super().__init__(message)
        self.metrics = metrics


class WorkerAgent(Protocol):
    """Plan作成と実行を行うAgentの契約を表す。回復不能な異常はWorkerErrorで通知する。"""

    async def create_plan(self, task: Task) -> AgentResult[Plan]:
        """TaskのPlanと利用量を返す。"""
        ...

    async def execute(self, task: Task, plan: Plan) -> AgentResult[ExecutionResult]:
        """承認済みPlanに沿った実行結果と利用量を返す。"""
        ...


class ReviewerAgent(Protocol):
    """Planと成果物を独立してレビューするAgentの契約を表す。"""

    async def review_plan(
        self, task: Task, plan: Plan, prompt: str
    ) -> AgentResult[ReviewResult]:
        """Planレビュー結果と利用量を返す。"""
        ...

    async def review_result(
        self, task: Task, plan: Plan, result: ExecutionResult, prompt: str
    ) -> AgentResult[ReviewResult]:
        """成果物レビュー結果と利用量を返す。"""
        ...
