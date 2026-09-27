"""Review Loopのrestart、turn、tool、時間、変更ファイル上限テスト。"""

import unittest

from app.core.baseline import BaselineRequirement
from app.core.limits import LoopLimits
from app.core.models import AgentMetrics, ExecutionResult, Task
from app.core.review_loop import ReviewLoopRunner
from app.core.review_models import ReviewIssue, ReviewResult
from app.core.state_machine import TaskState
from tests.fakes import FakeReviewer, FakeWorker


def _task() -> Task:
    """上限テスト用Taskを作る。"""
    return Task("limit-task", "一覧を表示する", (BaselineRequirement("BR-001", "一覧を表示する"),))


def _high_review() -> ReviewResult:
    """上限テスト用のHIGH指摘を作る。"""
    issue = ReviewIssue(1, "HIGH", ("BR-001",), "IMPLEMENTATION", "未達", (), "修正")
    return ReviewResult("未達", 0.9, (issue,))


class LimitTests(unittest.IsolatedAsyncioTestCase):
    """各上限超過が決定論的に処理されることを確認する。"""

    async def test_restart_limit_requires_human(self) -> None:
        """最大再開回数へ達した時点で次のWorker実行をせずHuman Requiredにする。"""
        worker = FakeWorker()
        reviewer = FakeReviewer(plan_reviews=[_high_review()])
        result = await ReviewLoopRunner(
            limits=LoopLimits(max_restart_count=1)
        ).run(worker, reviewer, _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.restart_count, 1)
        self.assertEqual(worker.create_plan_calls, 1)
        self.assertEqual(reviewer.plan_review_calls, 1)

    async def test_default_restart_limit_stops_at_third_finding(self) -> None:
        """既定上限3に達した時点で4回目のPlanを作らない。"""
        worker = FakeWorker()
        reviewer = FakeReviewer(plan_reviews=[_high_review()] * 3)
        result = await ReviewLoopRunner().run(worker, reviewer, _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.restart_count, 3)
        self.assertEqual(worker.create_plan_calls, 3)
        self.assertEqual(reviewer.plan_review_calls, 3)

    async def test_turn_limit_requires_human(self) -> None:
        """Phaseのturn上限超過でHuman Requiredにする。"""
        worker = FakeWorker(metrics=AgentMetrics(turns=2, tool_calls=0))
        result = await ReviewLoopRunner(
            limits=LoopLimits(max_turns_per_phase=1)
        ).run(worker, FakeReviewer(), _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "MAX_TURNS_EXCEEDED")

    async def test_tool_call_limit_requires_human(self) -> None:
        """Phaseのtool call上限超過でHuman Requiredにする。"""
        worker = FakeWorker(metrics=AgentMetrics(turns=1, tool_calls=2))
        result = await ReviewLoopRunner(
            limits=LoopLimits(max_tool_calls_per_phase=1)
        ).run(worker, FakeReviewer(), _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "MAX_TOOL_CALLS_EXCEEDED")

    async def test_changed_file_limit_requires_human(self) -> None:
        """変更ファイル上限を超えた実行結果を停止する。"""
        worker = FakeWorker(execution=ExecutionResult("done", ("a.py", "b.py")))
        result = await ReviewLoopRunner(
            limits=LoopLimits(max_changed_files=1)
        ).run(worker, FakeReviewer(), _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "MAX_CHANGED_FILES_EXCEEDED")

    async def test_phase_time_limit_requires_human(self) -> None:
        """Agent Phaseの実時間上限超過でHuman Requiredにする。"""
        worker = FakeWorker(delay_seconds=0.2)
        result = await ReviewLoopRunner(
            limits=LoopLimits(max_execution_minutes=0.001)
        ).run(worker, FakeReviewer(), _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "MAX_EXECUTION_TIME_EXCEEDED")

    async def test_execution_time_limit_covers_the_entire_task(self) -> None:
        """再計画を含むTask全体の経過時間上限を適用する。"""
        worker = FakeWorker(delay_seconds=0.03)
        reviewer = FakeReviewer(
            plan_reviews=[_high_review(), ReviewResult("問題なし", 0.9)],
            delay_seconds=0.03,
        )
        result = await ReviewLoopRunner(
            limits=LoopLimits(max_execution_minutes=0.0017)
        ).run(worker, reviewer, _task())
        self.assertEqual(result.state, TaskState.HUMAN_REQUIRED.value)
        self.assertEqual(result.reason, "MAX_EXECUTION_TIME_EXCEEDED")
