"""Task状態と許可する状態遷移を定義する。"""

from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    """Taskのライフサイクル状態を表す。"""

    TASK_RECEIVED = "TASK_RECEIVED"
    WAITING_DEPENDENCY = "WAITING_DEPENDENCY"
    PLAN_DRAFT = "PLAN_DRAFT"
    PLAN_REVIEW = "PLAN_REVIEW"
    EXECUTE = "EXECUTE"
    RESULT_REVIEW = "RESULT_REVIEW"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InvalidStateTransition(ValueError):
    """許可されていないTask状態遷移を表す。"""


# Task State Machineが許可する状態遷移
_ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.TASK_RECEIVED: frozenset({TaskState.WAITING_DEPENDENCY, TaskState.PLAN_DRAFT, TaskState.HUMAN_REQUIRED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.WAITING_DEPENDENCY: frozenset({TaskState.PLAN_DRAFT, TaskState.HUMAN_REQUIRED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.PLAN_DRAFT: frozenset({TaskState.PLAN_REVIEW, TaskState.HUMAN_REQUIRED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.PLAN_REVIEW: frozenset({TaskState.PLAN_DRAFT, TaskState.EXECUTE, TaskState.HUMAN_REQUIRED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.EXECUTE: frozenset({TaskState.RESULT_REVIEW, TaskState.HUMAN_REQUIRED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.RESULT_REVIEW: frozenset({TaskState.PLAN_DRAFT, TaskState.COMPLETE, TaskState.HUMAN_REQUIRED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.HUMAN_REQUIRED: frozenset({TaskState.TASK_RECEIVED, TaskState.PLAN_DRAFT, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.COMPLETE: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class TaskStateMachine:
    """現在状態から許可済みの遷移だけを適用する。"""

    def transition(self, current: TaskState, target: TaskState) -> TaskState:
        """許可された遷移先を返し、それ以外は例外にする。"""
        if target not in _ALLOWED_TRANSITIONS[current]:
            raise InvalidStateTransition(f"{current.value}から{target.value}へ遷移できません")
        return target
