"""Fake Agentで動作可能なReview Loop Coreを提供する。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import time

from app.agents.base import ReviewerAgent, ReviewerError, WorkerAgent, WorkerError
from app.core.baseline import (
    BaselineValidationError,
    validate_baseline_requirements,
    normalize_concrete_goal,
)
from app.core.limits import LoopLimits, PhaseUsage
from app.core.locks import TaskLockRegistry
from app.core.models import ExecutionResult, Plan, Task, TaskResult
from app.core.review_models import (
    ReviewResult,
    ReviewSchemaError,
    Severity,
    effective_severity,
    validate_review_result,
)
from app.core.state_machine import TaskState, TaskStateMachine


class _PhaseLimitExceeded(RuntimeError):
    """Phase上限超過を内部で伝える。"""

    def __init__(self, reason: str) -> None:
        """上限超過reasonを保持する。"""
        super().__init__(reason)
        self.reason = reason


def build_review_prompt(task: Task, review_target: str) -> str:
    """Review対象、全Baseline、固定Review Scopeを含むpromptを作る。"""
    baseline_text = "\n".join(
        f"{item.requirement_id}: {item.text}" for item in task.baseline_requirements
    )
    return (
        f"Review target: {review_target}\n"
        "Baseline Requirements:\n"
        f"{baseline_text}\n"
        "Review Scope:\n"
        "Baseline Requirementsを満たすために必要な問題だけを指摘する。"
        "要件違反でない一般改善、将来要件、リファクタリング、設計の好みは指摘しない。"
    )


class ReviewLoopRunner:
    """Baseline確認から結果レビューまでを直列に実行する。"""

    def __init__(
        self,
        limits: LoopLimits | None = None,
        locks: TaskLockRegistry | None = None,
        state_machine: TaskStateMachine | None = None,
    ) -> None:
        """上限、Task Lock、State Machineを設定する。"""
        self.limits = limits or LoopLimits()
        self.locks = locks or TaskLockRegistry()
        self.state_machine = state_machine or TaskStateMachine()

    async def run(
        self, worker: WorkerAgent, reviewer: ReviewerAgent, task: Task
    ) -> TaskResult:
        """1 TaskのReview Loopを実行し、最終状態を返す。"""
        async with self.locks.hold(task.task_id):
            task_started = time.monotonic()
            current = TaskState.TASK_RECEIVED
            history = [current.value]
            restart_count = 0

            try:
                requirements = task.baseline_requirements
                if not requirements and task.concrete_goal is not None:
                    requirements = normalize_concrete_goal(task.concrete_goal)
                requirements = validate_baseline_requirements(requirements)
            except BaselineValidationError:
                current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                return self._task_result(
                    task, current, "BASELINE_REQUIREMENTS_REQUIRED", restart_count, history
                )

            if not task.dependencies_complete:
                current = self._transition(current, TaskState.WAITING_DEPENDENCY, history)
                return self._task_result(
                    task, current, "DEPENDENCY_INCOMPLETE", restart_count, history
                )

            active_task = replace(task, baseline_requirements=requirements)
            current = self._transition(current, TaskState.PLAN_DRAFT, history)
            changed_files: set[str] = set()
            plan: Plan | None = None
            execution: ExecutionResult | None = None

            while True:
                try:
                    plan = await self._run_worker_phase(
                        lambda: worker.create_plan(active_task), task_started
                    )
                except _PhaseLimitExceeded as error:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task, current, error.reason, restart_count, history, plan, execution
                    )
                except WorkerError:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task,
                        current,
                        "UNRECOVERABLE_WORKER_ERROR",
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                current = self._transition(current, TaskState.PLAN_REVIEW, history)
                plan_review, retry_failure = await self._run_review_phase(
                    lambda prompt: reviewer.review_plan(
                        active_task, plan, prompt
                    ),
                    active_task,
                    "PLAN",
                    task_started,
                )
                if retry_failure is not None:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task,
                        current,
                        retry_failure,
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                if self._requires_restart(plan_review):
                    if restart_count >= self.limits.max_restart_count:
                        current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                        return self._task_result(
                            active_task,
                            current,
                            "MAX_RESTART_COUNT_EXCEEDED",
                            restart_count,
                            history,
                            plan,
                            execution,
                        )
                    restart_count += 1
                    current = self._transition(current, TaskState.PLAN_DRAFT, history)
                    if restart_count >= self.limits.max_restart_count:
                        current = self._transition(
                            current, TaskState.HUMAN_REQUIRED, history
                        )
                        return self._task_result(
                            active_task,
                            current,
                            "MAX_RESTART_COUNT_EXCEEDED",
                            restart_count,
                            history,
                            plan,
                            execution,
                        )
                    continue

                current = self._transition(current, TaskState.EXECUTE, history)
                try:
                    execution = await self._run_worker_phase(
                        lambda: worker.execute(active_task, plan), task_started
                    )
                except _PhaseLimitExceeded as error:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task, current, error.reason, restart_count, history, plan, execution
                    )
                except WorkerError:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task,
                        current,
                        "UNRECOVERABLE_WORKER_ERROR",
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                changed_files.update(execution.changed_files)
                if len(changed_files) > self.limits.max_changed_files:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task,
                        current,
                        "MAX_CHANGED_FILES_EXCEEDED",
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                current = self._transition(current, TaskState.RESULT_REVIEW, history)
                result_review, retry_failure = await self._run_review_phase(
                    lambda prompt: reviewer.review_result(
                        active_task, plan, execution, prompt
                    ),
                    active_task,
                    "RESULT",
                    task_started,
                )
                if retry_failure is not None:
                    current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                    return self._task_result(
                        active_task,
                        current,
                        retry_failure,
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                if self._requires_restart(result_review):
                    if restart_count >= self.limits.max_restart_count:
                        current = self._transition(current, TaskState.HUMAN_REQUIRED, history)
                        return self._task_result(
                            active_task,
                            current,
                            "MAX_RESTART_COUNT_EXCEEDED",
                            restart_count,
                            history,
                            plan,
                            execution,
                        )
                    restart_count += 1
                    current = self._transition(current, TaskState.PLAN_DRAFT, history)
                    if restart_count >= self.limits.max_restart_count:
                        current = self._transition(
                            current, TaskState.HUMAN_REQUIRED, history
                        )
                        return self._task_result(
                            active_task,
                            current,
                            "MAX_RESTART_COUNT_EXCEEDED",
                            restart_count,
                            history,
                            plan,
                            execution,
                        )
                    continue

                current = self._transition(current, TaskState.COMPLETE, history)
                return self._task_result(
                    active_task, current, None, restart_count, history, plan, execution
                )

    async def _run_worker_phase(self, call, task_started: float) -> object:
        """Worker呼び出しをPhase予算内で実行する。"""
        usage = PhaseUsage()
        return await self._invoke(usage, call, task_started)

    async def _run_review_phase(
        self, call, task: Task, target: str, task_started: float
    ) -> tuple[ReviewResult | None, str | None]:
        """Schemaまたはconfidence異常だけを同じReviewerでretryする。"""
        usage = PhaseUsage()
        prompt = build_review_prompt(task, target)
        baseline_ids = {item.requirement_id for item in task.baseline_requirements}
        for attempt in range(self.limits.max_review_retries + 1):
            try:
                review: ReviewResult = await self._invoke(
                    usage, lambda: call(prompt), task_started
                )
                validate_review_result(
                    review, baseline_ids, self.limits.confidence_threshold
                )
                return review, None
            except _PhaseLimitExceeded as error:
                return None, error.reason
            except (ReviewerError, ReviewSchemaError) as error:
                if attempt == self.limits.max_review_retries:
                    return None, "MAX_REVIEW_RETRIES_EXCEEDED"
        return None, "MAX_REVIEW_RETRIES_EXCEEDED"

    async def _invoke(self, usage: PhaseUsage, call, task_started: float):
        """Agent呼び出しをTask全体の時間とPhaseのturn/tool上限で囲む。"""
        task_limit_seconds = self.limits.max_execution_minutes * 60
        remaining = task_limit_seconds - (time.monotonic() - task_started)
        if remaining <= 0:
            raise _PhaseLimitExceeded("MAX_EXECUTION_TIME_EXCEEDED")
        try:
            response = await asyncio.wait_for(call(), timeout=remaining)
        except asyncio.TimeoutError as error:
            raise _PhaseLimitExceeded("MAX_EXECUTION_TIME_EXCEEDED") from error

        metrics = response.metrics
        if metrics.turns < 0 or metrics.tool_calls < 0:
            raise _PhaseLimitExceeded("INVALID_AGENT_METRICS")
        usage.add(metrics.turns, metrics.tool_calls)
        reason = usage.exceeded(self.limits)
        if reason is not None:
            raise _PhaseLimitExceeded(reason)
        return response.value

    @staticmethod
    def _requires_restart(review: ReviewResult | None) -> bool:
        """有効レビューにHIGHまたはMEDIUMが含まれるか返す。"""
        return effective_severity(review) in {Severity.HIGH, Severity.MEDIUM}

    def _transition(
        self, current: TaskState, target: TaskState, history: list[str]
    ) -> TaskState:
        """State Machineを通して状態を変更し履歴へ記録する。"""
        next_state = self.state_machine.transition(current, target)
        history.append(next_state.value)
        return next_state

    @staticmethod
    def _task_result(
        task: Task,
        state: TaskState,
        reason: str | None,
        restart_count: int,
        history: list[str],
        plan: Plan | None = None,
        execution: ExecutionResult | None = None,
    ) -> TaskResult:
        """TaskResultを生成する。"""
        return TaskResult(
            task_id=task.task_id,
            state=state.value,
            reason=reason,
            restart_count=restart_count,
            plan=plan,
            execution=execution,
            history=tuple(history),
        )
