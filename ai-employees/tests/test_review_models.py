"""ReviewResult Schemaとseverity集約の単体テスト。"""

import unittest

from app.core.review_models import (
    ReviewIssue,
    ReviewResult,
    ReviewSchemaError,
    Severity,
    effective_severity,
    validate_review_result,
)


class ReviewModelTests(unittest.TestCase):
    """Reviewer出力の構造と判定規則を確認する。"""

    def test_empty_issues_have_no_effective_severity(self) -> None:
        """IssueなしをNONE相当として扱う。"""
        self.assertIsNone(effective_severity(ReviewResult("問題なし", 1.0)))

    def test_high_and_low_issues_are_aggregated_as_high(self) -> None:
        """HIGHとLOWが混在した場合にHIGHを返す。"""
        review = ReviewResult(
            "複数指摘",
            0.9,
            (
                ReviewIssue(1, Severity.HIGH, ("BR-001",), "DESIGN", "問題", (), "修正"),
                ReviewIssue(2, Severity.LOW, ("BR-001",), "TEST", "軽微", (), "確認"),
            ),
        )
        self.assertEqual(effective_severity(review), Severity.HIGH)

    def test_issue_numbers_must_start_at_one_and_be_contiguous(self) -> None:
        """Issue番号の連番違反をSchema異常にする。"""
        review = ReviewResult(
            "指摘",
            0.9,
            (ReviewIssue(2, "HIGH", ("BR-001",), "DESIGN", "問題", (), "修正"),),
        )
        with self.assertRaises(ReviewSchemaError):
            validate_review_result(review, {"BR-001"}, 0.5)

    def test_missing_baseline_reference_is_rejected(self) -> None:
        """Taskに存在しないBaseline参照をSchema異常にする。"""
        review = ReviewResult(
            "指摘",
            0.9,
            (ReviewIssue(1, "HIGH", ("BR-999",), "DESIGN", "問題", (), "修正"),),
        )
        with self.assertRaises(ReviewSchemaError):
            validate_review_result(review, {"BR-001"}, 0.5)

    def test_confidence_below_threshold_is_rejected(self) -> None:
        """confidence閾値未満をReviewer異常として扱う。"""
        with self.assertRaises(ReviewSchemaError):
            validate_review_result(ReviewResult("不確実", 0.49), {"BR-001"}, 0.5)

    def test_confidence_equal_to_threshold_is_accepted(self) -> None:
        """confidenceが閾値と同じ値なら受理する。"""
        validate_review_result(ReviewResult("確認済み", 0.5), {"BR-001"}, 0.5)

    def test_extremely_large_integer_confidence_is_schema_error(self) -> None:
        """極端に大きな整数confidenceをSchema異常として扱う。"""
        review = ReviewResult("不正値", 10**10000)
        with self.assertRaises(ReviewSchemaError):
            validate_review_result(review, {"BR-001"}, 0.5)

    def test_malformed_issue_fields_are_schema_errors(self) -> None:
        """Issueフィールドの型違反をSchema異常として扱う。"""
        malformed_issues = (
            ReviewIssue(1, "HIGH", ("BR-001",), "DESIGN", None, (), "修正"),
            ReviewIssue(1, "HIGH", ("BR-001",), "DESIGN", "問題", None, "修正"),
        )
        for issue in malformed_issues:
            with self.subTest(issue=issue):
                with self.assertRaises(ReviewSchemaError):
                    validate_review_result(
                        ReviewResult("指摘", 0.9, (issue,)), {"BR-001"}, 0.5
                    )

    def test_non_array_issues_are_schema_errors(self) -> None:
        """issuesが配列でない場合をSchema異常として扱う。"""
        review = ReviewResult("問題なし", 0.9, None)
        with self.assertRaises(ReviewSchemaError):
            validate_review_result(review, {"BR-001"}, 0.5)
