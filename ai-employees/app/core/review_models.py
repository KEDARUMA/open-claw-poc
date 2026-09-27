"""Reviewerの出力形式、検証、severity集約を定義する。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from collections.abc import Collection


class Severity(str, Enum):
    """Review Issueの重大度を表す。"""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewCategory(str, Enum):
    """指示書で定義されたReview分類を表す。"""

    REQUIREMENT = "REQUIREMENT"
    DESIGN = "DESIGN"
    IMPLEMENTATION = "IMPLEMENTATION"
    TEST = "TEST"
    SECURITY = "SECURITY"
    PERFORMANCE = "PERFORMANCE"
    OPERABILITY = "OPERABILITY"
    OTHER = "OTHER"


class ReviewSchemaError(ValueError):
    """ReviewerのJSONまたはSchema異常を表す。"""


@dataclass(frozen=True, slots=True)
class ReviewIssue:
    """Baseline Requirementに紐づく1件の指摘を表す。"""

    number: int
    severity: Severity | str
    baseline_requirement_ids: tuple[str, ...]
    category: ReviewCategory | str
    problem: str
    evidence: tuple[str, ...]
    required_action: str


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Reviewerの要約、confidence、複数の指摘を表す。"""

    summary: str
    confidence: float
    issues: tuple[ReviewIssue, ...] = ()


def validate_review_result(
    review: ReviewResult,
    baseline_requirement_ids: Collection[str],
    confidence_threshold: float,
) -> None:
    """Review結果のconfidenceと全Issue参照を検証する。"""
    if not 0.0 <= confidence_threshold <= 1.0:
        raise ValueError("confidence_thresholdは0から1の範囲が必要です")
    if not isinstance(review, ReviewResult):
        raise ReviewSchemaError("ReviewResult形式ではありません")
    if (
        isinstance(review.confidence, bool)
        or not isinstance(review.confidence, (int, float))
    ):
        raise ReviewSchemaError("confidenceが数値ではありません")
    if isinstance(review.confidence, float) and not math.isfinite(review.confidence):
        raise ReviewSchemaError("confidenceが有限値ではありません")
    if not 0.0 <= review.confidence <= 1.0:
        raise ReviewSchemaError("confidenceが0から1の範囲外です")
    if review.confidence < confidence_threshold:
        raise ReviewSchemaError("confidenceが設定閾値未満です")
    if not isinstance(review.summary, str) or not review.summary.strip():
        raise ReviewSchemaError("summaryは空でない文字列が必要です")
    if not isinstance(review.issues, (tuple, list)):
        raise ReviewSchemaError("issuesは配列である必要があります")

    known_ids = set(baseline_requirement_ids)
    valid_severities = {severity.value for severity in Severity}
    valid_categories = {category.value for category in ReviewCategory}
    for expected_number, issue in enumerate(review.issues, start=1):
        if not isinstance(issue, ReviewIssue):
            raise ReviewSchemaError("Issue形式ではありません")
        if (
            isinstance(issue.number, bool)
            or not isinstance(issue.number, int)
            or issue.number != expected_number
        ):
            raise ReviewSchemaError("Issue番号が1からの連番ではありません")
        severity = issue.severity.value if isinstance(issue.severity, Severity) else issue.severity
        if not isinstance(severity, str) or severity not in valid_severities:
            raise ReviewSchemaError("Issue severityが不正です")
        category = issue.category.value if isinstance(issue.category, ReviewCategory) else issue.category
        if not isinstance(category, str) or category not in valid_categories:
            raise ReviewSchemaError("Issue categoryが不正です")
        if not isinstance(issue.baseline_requirement_ids, (tuple, list)):
            raise ReviewSchemaError("IssueのBaseline Requirement参照が配列ではありません")
        if not issue.baseline_requirement_ids:
            raise ReviewSchemaError("IssueにBaseline Requirement参照がありません")
        if any(
            not isinstance(requirement_id, str) or requirement_id not in known_ids
            for requirement_id in issue.baseline_requirement_ids
        ):
            raise ReviewSchemaError("Issueが存在しないBaseline Requirementを参照しています")
        if not isinstance(issue.problem, str) or not issue.problem.strip():
            raise ReviewSchemaError("Issueのproblemは必須です")
        if not isinstance(issue.evidence, (tuple, list)) or any(
            not isinstance(item, str) for item in issue.evidence
        ):
            raise ReviewSchemaError("Issueのevidenceは文字列配列である必要があります")
        if not isinstance(issue.required_action, str) or not issue.required_action.strip():
            raise ReviewSchemaError("Issueのrequired_actionは必須です")


def effective_severity(review: ReviewResult) -> Severity | None:
    """Issue一覧から重大度を決定し、空の場合はNoneを返す。"""
    severities = {
        issue.severity.value if isinstance(issue.severity, Severity) else issue.severity
        for issue in review.issues
    }
    valid_severities = {severity.value for severity in Severity}
    if not severities <= valid_severities:
        raise ReviewSchemaError("Issue severityが不正です")
    if Severity.HIGH.value in severities:
        return Severity.HIGH
    if Severity.MEDIUM.value in severities:
        return Severity.MEDIUM
    if Severity.LOW.value in severities:
        return Severity.LOW
    if not severities:
        return None
    return None
