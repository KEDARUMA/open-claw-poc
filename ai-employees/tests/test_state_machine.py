"""Task State Machineの単体テスト。"""

import unittest

from app.core.state_machine import InvalidStateTransition, TaskState, TaskStateMachine


class StateMachineTests(unittest.TestCase):
    """許可遷移と終端状態を確認する。"""

    def test_review_finding_returns_to_plan_draft(self) -> None:
        """レビュー指摘からPLAN_DRAFTへ戻れる。"""
        machine = TaskStateMachine()
        self.assertEqual(
            machine.transition(TaskState.PLAN_REVIEW, TaskState.PLAN_DRAFT),
            TaskState.PLAN_DRAFT,
        )

    def test_complete_is_terminal(self) -> None:
        """COMPLETEからの遷移を拒否する。"""
        with self.assertRaises(InvalidStateTransition):
            TaskStateMachine().transition(TaskState.COMPLETE, TaskState.PLAN_DRAFT)
