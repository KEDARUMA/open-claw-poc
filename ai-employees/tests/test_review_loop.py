"""ReviewLoopRunnerの状態遷移と受入条件の単体テスト。"""

import unittest

from app.core.baseline import BaselineRequirement, ConcreteGoal
from app.core.limits import LoopLimits
from app.core.models import Task
from app.core.review_loop import ReviewLoopRunner
from app.core.review_models import ReviewIssue, ReviewResult
from app.core.state_machine import TaskState
from tests.fakes import FakeReviewer, FakeWorker


def _task(**changes) -> Task:
    """テスト用の有効Baseline付きTaskを作る。"""
    values = {
        "task_id": "task-1",
        "goal": "画面に一覧を表示する",
        "baseline_requirements": (BaselineRequirement("BR-001", "一覧を表示する"),),
    }
    values.update(changes)
    return Task(**values)


def _high_review() -> ReviewResult:
    """Planを再開させるHIGH指摘を作る。"""
    issue = ReviewIssue(1, "HIGH", ("BR-001",), "DESIGN", "要件未達", (), "対応する")
    return ReviewResult("要件未達", 0.9, (issue,))


class ReviewLoopTests(unittest.IsolatedAsyncioTestCase):
    """Review Loopの主要遷移を確認する。"""

    async def test_missing_baseline_stops_before_plan(self) -> None:
        """Baseline未定義ではPlanを作らずHuman Requiredにする。"""
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, FakeReviewer(), _task(baseline_requirements=()))
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "BASELINE_REQUIREMENTS_REQUIRED")
        self.assertEqual(worker.create_plan_calls, 0)
        self.assertEqual(result.restart_count, 0)

    async def test_missing_baseline_precedes_incomplete_dependency(self) -> None:
        """Baseline不足と依存未完了が重なればBaseline不足で人へ戻す。"""
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(
            worker,
            FakeReviewer(),
            _task(baseline_requirements=(), dependencies_complete=False),
        )
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "BASELINE_REQUIREMENTS_REQUIRED")
        self.assertEqual(worker.create_plan_calls, 0)
        self.assertEqual(worker.execute_calls, 0)

    async def test_concrete_goal_is_normalized_and_prompt_has_scope(self) -> None:
        """明確Goalの本文を保持しReview promptへ要件とScopeを渡す。"""
        reviewer = FakeReviewer()
        task = _task(
            baseline_requirements=(),
            concrete_goal=ConcreteGoal(
                "利用者が一覧を閲覧できる", ("一覧は名前順に並ぶ",)
            ),
        )
        result = await ReviewLoopRunner().run(FakeWorker(), reviewer, task)
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        prompt = reviewer.plan_prompts[0]
        self.assertIn("BR-001: 利用者が一覧を閲覧できる", prompt)
        self.assertIn("BR-002: 一覧は名前順に並ぶ", prompt)
        self.assertIn("Review Scope", prompt)
        self.assertIn("リファクタリング", prompt)

    async def test_empty_and_low_only_reviews_complete(self) -> None:
        """指摘なしとLOWのみのレビューでTaskを完了する。"""
        low = ReviewResult(
            "軽微な指摘",
            0.8,
            (ReviewIssue(1, "LOW", ("BR-001",), "TEST", "補足", (), "任意確認"),),
        )
        reviewer = FakeReviewer(
            plan_reviews=[ReviewResult("問題なし", 1.0)],
            result_reviews=[low],
        )
        result = await ReviewLoopRunner().run(FakeWorker(), reviewer, _task())
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(reviewer.plan_review_calls, 1)
        self.assertEqual(reviewer.result_review_calls, 1)

    async def test_medium_review_restarts_from_plan(self) -> None:
        """MEDIUM指摘でも再計画へ戻る。"""
        medium = ReviewResult(
            "対応が必要",
            0.9,
            (ReviewIssue(1, "MEDIUM", ("BR-001",), "DESIGN", "問題", (), "修正"),),
        )
        reviewer = FakeReviewer(
            plan_reviews=[medium, ReviewResult("問題なし", 1.0)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, _task())
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(result.restart_count, 1)
        self.assertEqual(worker.create_plan_calls, 2)

    async def test_high_review_restarts_from_plan(self) -> None:
        """PlanのHIGH指摘後に再計画し、実行へ直行しない。"""
        reviewer = FakeReviewer(plan_reviews=[_high_review(), ReviewResult("問題なし", 1.0)])
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, _task())
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(result.restart_count, 1)
        self.assertEqual(worker.create_plan_calls, 2)
        self.assertEqual(result.history.count(TaskState.PLAN_DRAFT.value), 2)

    async def test_result_review_finding_returns_to_plan(self) -> None:
        """成果物のHIGH指摘でもPLAN_DRAFTへ戻る。"""
        reviewer = FakeReviewer(
            result_reviews=[_high_review(), ReviewResult("問題なし", 1.0)]
        )
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(worker, reviewer, _task())
        self.assertEqual(result.state, TaskState.COMPLETE.value)
        self.assertEqual(result.restart_count, 1)
        self.assertEqual(worker.create_plan_calls, 2)

    async def test_incomplete_dependency_waits_without_execution(self) -> None:
        """前提Task未完了ではWAITING_DEPENDENCYにして実行しない。"""
        worker = FakeWorker()
        result = await ReviewLoopRunner().run(
            worker, FakeReviewer(), _task(dependencies_complete=False)
        )
        self.assertEqual(result.state, TaskState.WAITING_DEPENDENCY.value)
        self.assertEqual(worker.create_plan_calls, 0)
        self.assertEqual(worker.execute_calls, 0)
