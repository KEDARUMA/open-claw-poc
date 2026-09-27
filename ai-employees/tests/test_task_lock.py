"""同一Taskの排他制御の単体テスト。"""

import asyncio
import unittest

from app.core.baseline import BaselineRequirement
from app.core.models import Task
from app.core.review_loop import ReviewLoopRunner
from tests.fakes import FakeActivityTracker, FakeReviewer, FakeWorker


class TaskLockTests(unittest.IsolatedAsyncioTestCase):
    """同じTask IDを持つ実行が重複しないことを確認する。"""

    async def test_same_task_runs_are_serialized(self) -> None:
        """同一TaskのWorker呼び出しが並行ACTIVEにならない。"""
        task = Task(
            "locked-task",
            "一覧を表示する",
            (BaselineRequirement("BR-001", "一覧を表示する"),),
        )
        activity = FakeActivityTracker()
        worker = FakeWorker(delay_seconds=0.01, activity=activity)
        runner = ReviewLoopRunner()
        await asyncio.gather(
            runner.run(worker, FakeReviewer(activity=activity, delay_seconds=0.01), task),
            runner.run(worker, FakeReviewer(activity=activity, delay_seconds=0.01), task),
        )
        self.assertEqual(worker.max_active_calls, 1)
        self.assertEqual(activity.max_active, 1)
