"""Baseline Requirementsの単体テスト。"""

import unittest

from app.core.baseline import (
    BaselineRequirement,
    BaselineValidationError,
    ConcreteGoal,
    normalize_concrete_goal,
    validate_baseline_requirements,
)


class BaselineTests(unittest.TestCase):
    """Baselineの正規化と検証を確認する。"""

    def test_concrete_goal_is_preserved_without_added_content(self) -> None:
        """Goalと明示済み完了条件の本文がそのまま保存される。"""
        goal = ConcreteGoal("画面に一覧を表示する", ("一覧を名前順に並べる",))
        requirements = normalize_concrete_goal(goal)
        self.assertEqual([item.requirement_id for item in requirements], ["BR-001", "BR-002"])
        self.assertEqual(
            [item.text for item in requirements],
            ["画面に一覧を表示する", "一覧を名前順に並べる"],
        )

    def test_empty_baseline_is_rejected(self) -> None:
        """Baseline未定義を検証エラーにする。"""
        with self.assertRaises(BaselineValidationError):
            validate_baseline_requirements(())

    def test_duplicate_baseline_ids_are_rejected(self) -> None:
        """重複IDを検証エラーにする。"""
        requirements = (
            BaselineRequirement("BR-001", "要件A"),
            BaselineRequirement("BR-001", "要件B"),
        )
        with self.assertRaises(BaselineValidationError):
            validate_baseline_requirements(requirements)
