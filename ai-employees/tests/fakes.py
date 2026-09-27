"""Review Loopの単体テストで使うFake Agentを提供する。"""

from __future__ import annotations

import asyncio

from app.agents.base import ReviewerError
from app.core.models import AgentMetrics, AgentResult, ExecutionResult, Plan, Task
from app.core.review_models import ReviewResult


class FakeActivityTracker:
    """Fake WorkerとFake Reviewerの同時ACTIVE数を共有記録する。"""

    def __init__(self) -> None:
        """ACTIVE数と最大同時数を初期化する。"""
        self.active = 0
        self.max_active = 0

    def begin(self) -> None:
        """AgentのACTIVE開始を記録する。"""
        self.active += 1
        self.max_active = max(self.max_active, self.active)

    def end(self) -> None:
        """AgentのACTIVE終了を記録する。"""
        self.active -= 1


class FakeWorker:
    """固定Planと実行結果を返すWorker。"""

    def __init__(
        self,
        execution: ExecutionResult | None = None,
        metrics: AgentMetrics | None = None,
        delay_seconds: float = 0.0,
        activity: FakeActivityTracker | None = None,
    ) -> None:
        """Fakeの返却値、遅延、並行度計測値を設定する。"""
        self.execution = execution or ExecutionResult("done")
        self.metrics = metrics or AgentMetrics()
        self.delay_seconds = delay_seconds
        self.activity = activity or FakeActivityTracker()
        self.create_plan_calls = 0
        self.execute_calls = 0
        self.active_calls = 0
        self.max_active_calls = 0

    async def create_plan(self, task: Task) -> AgentResult[Plan]:
        """固定Planを返し、同時実行数を記録する。"""
        self.create_plan_calls += 1
        return await self._respond(Plan("plan"))

    async def execute(self, task: Task, plan: Plan) -> AgentResult[ExecutionResult]:
        """固定ExecutionResultを返し、同時実行数を記録する。"""
        self.execute_calls += 1
        return await self._respond(self.execution)

    async def _respond(self, value):
        """設定された遅延を反映してAgentResultを返す。"""
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        self.activity.begin()
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            return AgentResult(value, self.metrics)
        finally:
            self.activity.end()
            self.active_calls -= 1


class FakeReviewer:
    """順番に設定済みのReview結果を返すReviewer。"""

    def __init__(
        self,
        plan_reviews: list[ReviewResult | Exception] | None = None,
        result_reviews: list[ReviewResult | Exception] | None = None,
        metrics: AgentMetrics | None = None,
        activity: FakeActivityTracker | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        """Plan用・成果物用のReview応答列を設定する。"""
        self.plan_reviews = list(plan_reviews or [])
        self.result_reviews = list(result_reviews or [])
        self.metrics = metrics or AgentMetrics()
        self.activity = activity or FakeActivityTracker()
        self.delay_seconds = delay_seconds
        self.plan_prompts: list[str] = []
        self.result_prompts: list[str] = []
        self.plan_review_calls = 0
        self.result_review_calls = 0

    async def review_plan(
        self, task: Task, plan: Plan, prompt: str
    ) -> AgentResult[ReviewResult]:
        """Plan用の次の応答を返す。"""
        self.plan_review_calls += 1
        self.plan_prompts.append(prompt)
        return await self._respond(self.plan_reviews)

    async def review_result(
        self, task: Task, plan: Plan, result: ExecutionResult, prompt: str
    ) -> AgentResult[ReviewResult]:
        """成果物用の次の応答を返す。"""
        self.result_review_calls += 1
        self.result_prompts.append(prompt)
        return await self._respond(self.result_reviews)

    async def _respond(self, responses: list[ReviewResult | Exception]):
        """ACTIVEを記録して設定済みの次の応答を返す。"""
        self.activity.begin()
        try:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            return self._next(responses)
        finally:
            self.activity.end()

    def _next(self, responses: list[ReviewResult | Exception]) -> AgentResult[ReviewResult]:
        """応答列の先頭を返し、未設定なら指摘なしを返す。"""
        response = responses.pop(0) if responses else ReviewResult("ok", 1.0)
        if isinstance(response, Exception):
            if isinstance(response, ReviewerError):
                raise response
            raise ReviewerError(str(response)) from response
        return AgentResult(response, self.metrics)
