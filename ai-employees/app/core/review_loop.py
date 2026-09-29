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
from app.core.models import AgentResult, ExecutionResult, LoopEvent, LoopEventHandler, Plan, Task, TaskResult
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
        self,
        worker: WorkerAgent,
        reviewer: ReviewerAgent,
        task: Task,
        on_event: LoopEventHandler | None = None,
    ) -> TaskResult:
        """1 TaskのReview Loopを実行し、最終状態を返す。"""
        async with self.locks.hold(task.task_id):
            task_started = time.monotonic()
            current = TaskState.TASK_RECEIVED
            history = [current.value]
            restart_count = 0
            plan: Plan | None = None
            execution: ExecutionResult | None = None

            def emit(
                event_type: str,
                *,
                event_reason: str | None = None,
                plan_value: Plan | None = None,
                execution_value: ExecutionResult | None = None,
                review_target: str | None = None,
                review: ReviewResult | None = None,
                agent_id: str | None = None,
                phase: str | None = None,
                metrics=None,
            ) -> None:
                """現在のLoop情報を永続化callbackへ渡す。"""
                if on_event is None:
                    return
                on_event(
                    LoopEvent(
                        event_type=event_type,
                        state=current.value,
                        reason=event_reason,
                        restart_count=restart_count,
                        history=tuple(history),
                        plan=plan_value if plan_value is not None else plan,
                        execution=(
                            execution_value
                            if execution_value is not None
                            else execution
                        ),
                        review_target=review_target,
                        review=review,
                        agent_id=agent_id,
                        phase=phase,
                        metrics=metrics,
                    )
                )

            def transition(target: TaskState, reason: str | None = None) -> TaskState:
                """状態遷移を適用し、変更後の履歴を通知する。"""
                nonlocal current
                current = self._transition(current, target, history)
                emit("state_changed", event_reason=reason)
                return current

            try:
                requirements = task.baseline_requirements
                if not requirements and task.concrete_goal is not None:
                    requirements = normalize_concrete_goal(task.concrete_goal)
                requirements = validate_baseline_requirements(requirements)
            except BaselineValidationError:
                transition(TaskState.HUMAN_REQUIRED, "BASELINE_REQUIREMENTS_REQUIRED")
                return self._task_result(
                    task, current, "BASELINE_REQUIREMENTS_REQUIRED", restart_count, history
                )

            if not task.dependencies_complete:
                transition(TaskState.WAITING_DEPENDENCY, "DEPENDENCY_INCOMPLETE")
                return self._task_result(
                    task, current, "DEPENDENCY_INCOMPLETE", restart_count, history
                )

            active_task = replace(task, baseline_requirements=requirements)
            transition(TaskState.PLAN_DRAFT)
            changed_files: set[str] = set()

            while True:
                try:
                    plan = await self._run_worker_phase(
                        lambda: worker.create_plan(active_task),
                        task_started,
                        lambda response: emit(
                            "agent_response",
                            plan_value=response.value
                            if isinstance(response.value, Plan)
                            else None,
                            agent_id=getattr(worker, "agent_id", "worker"),
                            phase="PLAN",
                            metrics=response.metrics,
                        ),
                    )
                except _PhaseLimitExceeded as error:
                    transition(TaskState.HUMAN_REQUIRED, error.reason)
                    return self._task_result(
                        active_task, current, error.reason, restart_count, history, plan, execution
                    )
                except WorkerError as error:
                    if error.metrics is not None:
                        emit(
                            "agent_error",
                            event_reason=str(error),
                            agent_id=getattr(worker, "agent_id", "worker"),
                            phase="PLAN",
                            metrics=error.metrics,
                        )
                    transition(TaskState.HUMAN_REQUIRED, "UNRECOVERABLE_WORKER_ERROR")
                    return self._task_result(
                        active_task,
                        current,
                        "UNRECOVERABLE_WORKER_ERROR",
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                transition(TaskState.PLAN_REVIEW)
                plan_review, retry_failure = await self._run_review_phase(
                    lambda prompt: reviewer.review_plan(
                        active_task, plan, prompt
                    ),
                    active_task,
                    "PLAN",
                    task_started,
                    lambda response, review: emit(
                        "agent_response",
                        review_target="PLAN",
                        review=review,
                        agent_id=getattr(reviewer, "agent_id", "reviewer"),
                        phase="PLAN_REVIEW",
                        metrics=response.metrics,
                    ),
                )
                if retry_failure is not None:
                    transition(TaskState.HUMAN_REQUIRED, retry_failure)
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
                        transition(TaskState.HUMAN_REQUIRED, "MAX_RESTART_COUNT_EXCEEDED")
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
                    transition(TaskState.PLAN_DRAFT)
                    if restart_count >= self.limits.max_restart_count:
                        transition(TaskState.HUMAN_REQUIRED, "MAX_RESTART_COUNT_EXCEEDED")
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

                transition(TaskState.EXECUTE)
                try:
                    execution = await self._run_worker_phase(
                        lambda: worker.execute(active_task, plan),
                        task_started,
                        lambda response: emit(
                            "agent_response",
                            execution_value=response.value
                            if isinstance(response.value, ExecutionResult)
                            else None,
                            agent_id=getattr(worker, "agent_id", "worker"),
                            phase="EXECUTE",
                            metrics=response.metrics,
                        ),
                    )
                except _PhaseLimitExceeded as error:
                    transition(TaskState.HUMAN_REQUIRED, error.reason)
                    return self._task_result(
                        active_task, current, error.reason, restart_count, history, plan, execution
                    )
                except WorkerError as error:
                    if error.metrics is not None:
                        emit(
                            "agent_error",
                            event_reason=str(error),
                            agent_id=getattr(worker, "agent_id", "worker"),
                            phase="EXECUTE",
                            metrics=error.metrics,
                        )
                    transition(TaskState.HUMAN_REQUIRED, "UNRECOVERABLE_WORKER_ERROR")
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
                    transition(TaskState.HUMAN_REQUIRED, "MAX_CHANGED_FILES_EXCEEDED")
                    return self._task_result(
                        active_task,
                        current,
                        "MAX_CHANGED_FILES_EXCEEDED",
                        restart_count,
                        history,
                        plan,
                        execution,
                    )

                transition(TaskState.RESULT_REVIEW)
                result_review, retry_failure = await self._run_review_phase(
                    lambda prompt: reviewer.review_result(
                        active_task, plan, execution, prompt
                    ),
                    active_task,
                    "RESULT",
                    task_started,
                    lambda response, review: emit(
                        "agent_response",
                        review_target="RESULT",
                        review=review,
                        agent_id=getattr(reviewer, "agent_id", "reviewer"),
                        phase="RESULT_REVIEW",
                        metrics=response.metrics,
                    ),
                )
                if retry_failure is not None:
                    transition(TaskState.HUMAN_REQUIRED, retry_failure)
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
                        transition(TaskState.HUMAN_REQUIRED, "MAX_RESTART_COUNT_EXCEEDED")
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
                    transition(TaskState.PLAN_DRAFT)
                    if restart_count >= self.limits.max_restart_count:
                        transition(TaskState.HUMAN_REQUIRED, "MAX_RESTART_COUNT_EXCEEDED")
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

                transition(TaskState.COMPLETE)
                return self._task_result(
                    active_task, current, None, restart_count, history, plan, execution
                )

    async def _run_worker_phase(
        self, call, task_started: float, on_response=None
    ) -> object:
        """Worker呼び出しをPhase予算内で実行する。"""
        usage = PhaseUsage()
        response = await self._invoke(
            usage, call, task_started, on_response=on_response
        )
        return response.value

    async def _run_review_phase(
        self,
        call,
        task: Task,
        target: str,
        task_started: float,
        on_response=None,
    ) -> tuple[ReviewResult | None, str | None]:
        """Schemaまたはconfidence異常だけを同じReviewerでretryする。"""
        usage = PhaseUsage()
        prompt = build_review_prompt(task, target)
        baseline_ids = {item.requirement_id for item in task.baseline_requirements}
        for attempt in range(self.limits.max_review_retries + 1):
            try:
                response: AgentResult[ReviewResult] = await self._invoke(
                    usage,
                    lambda: call(prompt),
                    task_started,
                    on_response=(
                        lambda response: on_response(response, response.value)
                    )
                    if on_response is not None
                    else None,
                )
                review = response.value
                validate_review_result(
                    review, baseline_ids, self.limits.confidence_threshold
                )
                return review, None
            except _PhaseLimitExceeded as error:
                return None, error.reason
            except (ReviewerError, ReviewSchemaError) as error:
                if (
                    isinstance(error, ReviewerError)
                    and error.metrics is not None
                    and on_response is not None
                ):
                    on_response(AgentResult(None, error.metrics), None)
                if attempt == self.limits.max_review_retries:
                    return None, "MAX_REVIEW_RETRIES_EXCEEDED"
        return None, "MAX_REVIEW_RETRIES_EXCEEDED"

    async def _invoke(
        self, usage: PhaseUsage, call, task_started: float, on_response=None
    ):
        """Agent呼び出しをTask全体の時間とPhaseのturn/tool上限で囲む。"""
        task_limit_seconds = self.limits.max_execution_minutes * 60
        remaining = task_limit_seconds - (time.monotonic() - task_started)
        if remaining <= 0:
            raise _PhaseLimitExceeded("MAX_EXECUTION_TIME_EXCEEDED")
        try:
            response = await asyncio.wait_for(call(), timeout=remaining)
        except asyncio.TimeoutError as error:
            raise _PhaseLimitExceeded("MAX_EXECUTION_TIME_EXCEEDED") from error

        if on_response is not None:
            on_response(response)
        metrics = response.metrics
        if metrics.turns < 0 or metrics.tool_calls < 0:
            raise _PhaseLimitExceeded("INVALID_AGENT_METRICS")
        usage.add(metrics.turns, metrics.tool_calls)
        reason = usage.exceeded(self.limits)
        if reason is not None:
            raise _PhaseLimitExceeded(reason)
        return response

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
