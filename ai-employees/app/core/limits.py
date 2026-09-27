"""Review Loopが使う決定論的な上限値とPhase予算を定義する。"""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_MAX_RESTART_COUNT = 3  # PLAN再開の既定上限
DEFAULT_MAX_REVIEW_RETRIES = 2  # Reviewer再試行の既定上限
DEFAULT_MAX_TURNS_PER_PHASE = 12  # Phaseごとのturn上限
DEFAULT_MAX_TOOL_CALLS_PER_PHASE = 20  # Phaseごとのtool call上限
DEFAULT_MAX_CHANGED_FILES = 10  # Taskの変更ファイル上限
DEFAULT_MAX_EXECUTION_MINUTES = 30  # Agent Phaseの実行時間上限
DEFAULT_CONFIDENCE_THRESHOLD = 0.5  # Reviewer結果の最低confidence


class LimitConfigurationError(ValueError):
    """不正な上限値を表す。"""


@dataclass(frozen=True, slots=True)
class LoopLimits:
    """Review Loopで適用する全上限を保持する。"""

    max_restart_count: int = DEFAULT_MAX_RESTART_COUNT
    max_review_retries: int = DEFAULT_MAX_REVIEW_RETRIES
    max_turns_per_phase: int = DEFAULT_MAX_TURNS_PER_PHASE
    max_tool_calls_per_phase: int = DEFAULT_MAX_TOOL_CALLS_PER_PHASE
    max_changed_files: int = DEFAULT_MAX_CHANGED_FILES
    max_execution_minutes: float = DEFAULT_MAX_EXECUTION_MINUTES
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD

    def __post_init__(self) -> None:
        """上限値の範囲を確認する。"""
        integer_limits = (
            self.max_restart_count,
            self.max_review_retries,
            self.max_turns_per_phase,
            self.max_tool_calls_per_phase,
            self.max_changed_files,
        )
        if any(value < 0 for value in integer_limits):
            raise LimitConfigurationError("回数上限は0以上が必要です")
        if self.max_execution_minutes <= 0:
            raise LimitConfigurationError("実行時間上限は0より大きい値が必要です")
        if not 0.0 <= self.confidence_threshold <= 1.0:
            raise LimitConfigurationError("confidence_thresholdは0から1の範囲が必要です")


@dataclass(slots=True)
class PhaseUsage:
    """1つのAgent Phaseで累積したturn数とtool call数を保持する。"""

    turns: int = 0
    tool_calls: int = 0

    def add(self, turns: int, tool_calls: int) -> None:
        """Agent呼び出し1回分の利用量を加算する。"""
        self.turns += turns
        self.tool_calls += tool_calls

    def exceeded(self, limits: LoopLimits) -> str | None:
        """最初に超過したPhase上限のreasonを返す。"""
        if self.turns > limits.max_turns_per_phase:
            return "MAX_TURNS_EXCEEDED"
        if self.tool_calls > limits.max_tool_calls_per_phase:
            return "MAX_TOOL_CALLS_EXCEEDED"
        return None
