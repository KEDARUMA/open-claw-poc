"""Baseline Requirementsの値と検証を定義する。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Sequence


_BASELINE_ID_PATTERN = re.compile(r"^BR-\d{3}$")  # Baseline IDの固定形式


class BaselineValidationError(ValueError):
    """Baseline Requirementsの不正を表す。"""


@dataclass(frozen=True, slots=True)
class ConcreteGoal:
    """Managerが明確と判断したGoalと、明示済みの完了条件を保持する。"""

    text: str
    completion_conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BaselineRequirement:
    """Review対象となる固定要件を表す。"""

    requirement_id: str
    text: str


def normalize_concrete_goal(goal: ConcreteGoal) -> tuple[BaselineRequirement, ...]:
    """明確と確認済みのGoalだけを文面を変えずにBR形式へ変換する。"""
    statements = (goal.text, *goal.completion_conditions)
    if not goal.text.strip() or any(not statement.strip() for statement in statements):
        raise BaselineValidationError("Goalと完了条件は空にできません")
    return tuple(
        BaselineRequirement(f"BR-{index:03d}", statement)
        for index, statement in enumerate(statements, start=1)
    )


def validate_baseline_requirements(
    requirements: Sequence[BaselineRequirement],
) -> tuple[BaselineRequirement, ...]:
    """要件が空でなく、IDが一意なBR形式であることを確認する。"""
    normalized = tuple(requirements)
    if not normalized:
        raise BaselineValidationError("Baseline Requirementsが未定義です")
    ids: set[str] = set()
    for requirement in normalized:
        if not _BASELINE_ID_PATTERN.fullmatch(requirement.requirement_id):
            raise BaselineValidationError("Baseline Requirement IDはBR-001形式が必要です")
        if requirement.requirement_id in ids:
            raise BaselineValidationError("Baseline Requirement IDが重複しています")
        if not requirement.text.strip():
            raise BaselineValidationError("Baseline Requirement本文は空にできません")
        ids.add(requirement.requirement_id)
    return normalized
