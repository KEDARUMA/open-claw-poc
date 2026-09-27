"""Reviewer異常、confidence閾値、retry上限の単体テスト。"""

import unittest

from app.agents.base import ReviewerError, WorkerError
from app.core.baseline import BaselineRequirement
from app.core.limits import LoopLimits
from app.core.models import AgentResult, ExecutionResult, Plan, Task
from app.core.review_loop import ReviewLoopRunner
from app.core.review_models import ReviewIssue, ReviewResult
from app.core.state_machine import TaskState
from tests.fakes import FakeReviewer, FakeWorker


class ReviewRetryTests(unittest.IsolatedAsyncioTestCase):
    """Reviewerの異常をWorker再計画と分離して確認する。"""

    def setUp(self) -> None:
        """共通のTaskを初期化する。"""
        self.task = Task(
            task_id="retry-task",
            goal="保存結果を表示する",
            baseline_requirements=(BaselineRequirement("BR-001", "保存結果を表示する"),),
        )

    async def test_invalid_json_retries_reviewer_without_replanning(self) -> None:
        """Reviewer JSON異常後もWorkerを再計画せず同じReviewerを再試行する。"""
        reviewer = FakeReviewer(
            plan_reviews=[ReviewerError("invalid JSON"), ReviewResult("問題なし", 0.9)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, self.task)
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(reviewer.plan_review_calls, 2)
        self.assertEqual(worker.create_plan_calls, 1)
        self.assertEqual(result.restart_count, 0)

    async def test_low_confidence_retries_reviewer(self) -> None:
        """confidence閾値未満を同じReviewerのretryにする。"""
        reviewer = FakeReviewer(
            plan_reviews=[ReviewResult("不確実", 0.49), ReviewResult("確認済み", 0.5)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, self.task)
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(reviewer.plan_review_calls, 2)
        self.assertEqual(worker.create_plan_calls, 1)

    async def test_invalid_issue_number_retries_reviewer(self) -> None:
        """Issue番号Schema違反をWorker再計画でなくReviewer retryにする。"""
        invalid = ReviewResult(
            "番号異常",
            0.9,
            (ReviewIssue(2, "HIGH", ("BR-001",), "DESIGN", "問題", (), "修正"),),
        )
        reviewer = FakeReviewer(
            plan_reviews=[invalid, ReviewResult("問題なし", 0.9)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, self.task)
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(reviewer.plan_review_calls, 2)
        self.assertEqual(worker.create_plan_calls, 1)

    async def test_unknown_baseline_id_retries_reviewer(self) -> None:
        """存在しないBaseline IDをReviewer retryにする。"""
        invalid = ReviewResult(
            "参照異常",
            0.9,
            (ReviewIssue(1, "HIGH", ("BR-999",), "DESIGN", "問題", (), "修正"),),
        )
        reviewer = FakeReviewer(
            plan_reviews=[invalid, ReviewResult("問題なし", 0.9)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, self.task)
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(reviewer.plan_review_calls, 2)
        self.assertEqual(worker.create_plan_calls, 1)

    async def test_malformed_issue_field_retries_reviewer(self) -> None:
        """Issue fieldの型異常をWorker再計画でなくReviewer retryにする。"""
        invalid = ReviewResult(
            "型異常",
            0.9,
            (ReviewIssue(1, "HIGH", ("BR-001",), "DESIGN", "問題", None, "修正"),),
        )
        reviewer = FakeReviewer(
            plan_reviews=[invalid, ReviewResult("問題なし", 0.9)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, self.task)
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(reviewer.plan_review_calls, 2)
        self.assertEqual(worker.create_plan_calls, 1)

    async def test_unrecoverable_worker_error_requires_human(self) -> None:
        """PlanとExecuteの回復不能WorkerエラーをHUMAN_REQUIREDへ移す。"""

        class FailingWorker(FakeWorker):
            """指定されたPhaseで回復不能エラーを返すFake Worker。"""

            def __init__(self, failure_phase: str) -> None:
                """回復不能エラーを返すPhaseを設定する。"""
                super().__init__()
                self.failure_phase = failure_phase

            async def create_plan(self, task: Task) -> AgentResult[Plan]:
                """Plan作成の回復不能エラーを再現する。"""
                if self.failure_phase == "plan":
                    raise WorkerError("Plan作成失敗")
                return await super().create_plan(task)

            async def execute(
                self, task: Task, plan: Plan
            ) -> AgentResult[ExecutionResult]:
                """Executeの回復不能エラーを再現する。"""
                if self.failure_phase == "execute":
                    raise WorkerError("Execute失敗")
                return await super().execute(task, plan)

        for failure_phase in ("plan", "execute"):
            with self.subTest(failure_phase=failure_phase):
                result = await ReviewLoopRunner().run(
                    FailingWorker(failure_phase), FakeReviewer(), self.task
                )
                self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
                self.assertEqual(result.reason, "UNRECOVERABLE_WORKER_ERROR")

    async def test_retry_limit_requires_human(self) -> None:
        """confidence異常がretry上限まで続けばHuman Requiredにする。"""
        reviewer = FakeReviewer(
            plan_reviews=[ReviewResult("不確実", 0.1), ReviewResult("不確実", 0.2)]
        )
        limits = LoopLimits(max_review_retries=1)
        worker = FakeWorker()
        result = await ReviewLoopRunner(limits=limits).run(worker, reviewer, self.task)
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "MAX_REVIEW_RETRIES_EXCEEDED")
        self.assertEqual(worker.create_plan_calls, 1)
        self.assertEqual(result.restart_count, 0)
