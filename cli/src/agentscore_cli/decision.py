"""Release-decision math (TSK_123).

Ported 1:1 from the frontend ``lib/releaseReadiness.ts`` so the CLI
agrees byte-for-byte with the suite dashboard. **No new product
thresholds** — the constants below mirror the existing frontend
constants. If they ever change, both ends must move in lock-step
(INVARIANT #2).

The module is pure: no HTTP, no env reads, no logging side-effects.
Callers feed it the typed dashboard payload (`DashboardPayload`) and
get back a typed ``DecisionReport``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal


# --------------------------------------------------------------------------- #
# Mirrored product constants (frontend lib/releaseReadiness.ts).               #
# --------------------------------------------------------------------------- #

CRITICAL_PASS_RATIO = 0.8
MAJOR_PASS_RATIO = 0.6
STYLE_PASS_RATIO = 0.5

MIN_TOTAL_CASES_FOR_MEDIUM_CONFIDENCE = 30
MIN_CRITERIA_FOR_MEDIUM_CONFIDENCE = 3
MIN_CASES_PER_CRITERION_FOR_MEDIUM_CONFIDENCE = 5

METHODOLOGY_LABEL = "AgentScore release gate v1"

CRITICAL_TIER = "critical"
ARCHITECTURE_TIER = "architecture"
STYLE_TIER = "style"


CriterionStatus = Literal["PASSED", "WARNING", "FAILED"]
ReleaseVerdict = Literal[
    "BLOCKED", "NEEDS_FIXES", "REVIEW_REQUIRED", "RELEASE_CANDIDATE"
]
ReleaseConfidence = Literal["LOW", "MEDIUM", "HIGH"]
FailSignal = Literal[
    "BLOCKED",
    "NEEDS_FIXES",
    "REVIEW_REQUIRED",
    "LOW_CONFIDENCE_CRITICAL",
]

DEFAULT_FAIL_ON: tuple[FailSignal, ...] = (
    "BLOCKED",
    "NEEDS_FIXES",
    "LOW_CONFIDENCE_CRITICAL",
)


@dataclass(frozen=True)
class CriterionEvaluation:
    """Per-criterion evaluation row in the CLI's report."""

    code: str
    name: str
    tier: str
    status: CriterionStatus
    score: float
    weight: float
    required_passed_cases: int
    actual_passed_cases: int
    total_cases: int
    has_error_note: bool
    has_invalid_counts: bool
    risk_domains: list[str] = field(default_factory=list)
    policy_ids: list[str] = field(default_factory=list)
    release_impact: str | None = None


@dataclass(frozen=True)
class DecisionReport:
    """Full release-decision report for one suite."""

    verdict: ReleaseVerdict
    confidence: ReleaseConfidence
    diagnostic_score: float
    evidence_passed: int
    evidence_total: int
    critical_failures: int
    blocking_reasons: list[str]
    criteria: list[CriterionEvaluation]
    methodology: str = METHODOLOGY_LABEL
    insufficient_evidence: bool = False


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _safe_count(value: Any) -> int | None:
    """Mirror of `safeCount` from the frontend module."""
    if not isinstance(value, (int, float)):
        return None
    if isinstance(value, bool):
        return None
    if not math.isfinite(float(value)):
        return None
    if value < 0:
        return None
    return int(value)


def _threshold_for(tier: str) -> float:
    if tier == CRITICAL_TIER:
        return CRITICAL_PASS_RATIO
    if tier == ARCHITECTURE_TIER:
        return MAJOR_PASS_RATIO
    return STYLE_PASS_RATIO


def _evaluate_criterion(c: dict[str, Any]) -> CriterionEvaluation:
    """Port of `evaluateCriterion`."""
    tier = str(c.get("tier", STYLE_TIER))
    raw_total = _safe_count(c.get("test_case_count"))
    raw_passed = _safe_count(c.get("passed_count"))
    has_invalid_counts = raw_total is None or raw_passed is None
    safe_total = raw_total or 0
    safe_passed = min(raw_passed or 0, safe_total)
    pass_ratio = _threshold_for(tier)
    required = math.ceil(safe_total * pass_ratio)
    has_error_note = bool(c.get("error_note"))

    if has_invalid_counts or safe_total == 0 or has_error_note:
        status: CriterionStatus = "WARNING"
    elif safe_passed >= required:
        status = (
            "WARNING" if required > 0 and safe_passed == required else "PASSED"
        )
    else:
        status = "FAILED"

    score_raw = c.get("score", 0)
    score = float(score_raw) if isinstance(score_raw, (int, float)) and math.isfinite(float(score_raw)) else 0.0

    return CriterionEvaluation(
        code=str(c.get("code", "")),
        name=str(c.get("name", "")),
        tier=tier,
        status=status,
        score=score,
        weight=float(c.get("weight", 0)),
        required_passed_cases=required,
        actual_passed_cases=safe_passed,
        total_cases=safe_total,
        has_error_note=has_error_note,
        has_invalid_counts=has_invalid_counts,
        risk_domains=list(c.get("risk_domains") or []),
        policy_ids=list(c.get("policy_ids") or []),
        release_impact=c.get("release_impact"),
    )


def _compute_confidence(
    criteria: list[CriterionEvaluation],
    total_cases: int,
    uncalibrated: bool,
) -> ReleaseConfidence:
    if (
        not criteria
        or total_cases == 0
        or any(c.has_error_note for c in criteria)
        or any(c.has_invalid_counts for c in criteria)
        or any(
            c.total_cases < MIN_CASES_PER_CRITERION_FOR_MEDIUM_CONFIDENCE
            for c in criteria
        )
    ):
        return "LOW"
    if (
        len(criteria) < MIN_CRITERIA_FOR_MEDIUM_CONFIDENCE
        or total_cases < MIN_TOTAL_CASES_FOR_MEDIUM_CONFIDENCE
    ):
        return "LOW"
    # Multi-run variance not on the wire yet → cap at MEDIUM.
    return "MEDIUM"


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


def compute_release_decision(
    dashboard: dict[str, Any],
    *,
    enriched_criteria: list[dict[str, Any]] | None = None,
) -> DecisionReport:
    """Build a :class:`DecisionReport` from a /dashboard payload.

    ``enriched_criteria`` is the optional list of :class:`dict` rows from
    `/v2/evaluations/criteria/registry`; when supplied, each entry is
    merged into the matching dashboard criterion so the report can carry
    `policy_ids`, `risk_domains`, and `release_impact`.
    """

    raw_criteria = list(dashboard.get("criteria") or [])
    registry_by_code = {
        r["id"]: r for r in (enriched_criteria or []) if isinstance(r, dict) and "id" in r
    }

    merged: list[dict[str, Any]] = []
    for c in raw_criteria:
        if not isinstance(c, dict):
            continue
        code = c.get("code", "")
        registry = registry_by_code.get(code) or {}
        merged.append(
            {
                **c,
                "risk_domains": registry.get("risk_domains") or [],
                "policy_ids": registry.get("policy_ids") or [],
                "release_impact": registry.get("release_impact"),
            }
        )

    evaluations = [_evaluate_criterion(c) for c in merged]
    total_cases = sum(c.total_cases for c in evaluations)
    passed_cases = sum(c.actual_passed_cases for c in evaluations)
    insufficient = not evaluations or total_cases == 0

    critical_failures = sum(
        1 for c in evaluations if c.tier == CRITICAL_TIER and c.status == "FAILED"
    )
    major_failures = sum(
        1 for c in evaluations if c.tier == ARCHITECTURE_TIER and c.status == "FAILED"
    )
    warning_count = sum(1 for c in evaluations if c.status == "WARNING")
    has_error_note = any(c.has_error_note for c in evaluations)
    has_invalid_counts = any(c.has_invalid_counts for c in evaluations)

    if critical_failures > 0:
        verdict: ReleaseVerdict = "BLOCKED"
    elif major_failures > 0:
        verdict = "NEEDS_FIXES"
    else:
        verdict = "RELEASE_CANDIDATE"

    uncalibrated = dashboard.get("category_thresholds") is None
    confidence = _compute_confidence(evaluations, total_cases, uncalibrated)

    if insufficient:
        verdict = "REVIEW_REQUIRED"
    elif verdict == "RELEASE_CANDIDATE" and (
        confidence == "LOW" or warning_count > 0
    ):
        verdict = "REVIEW_REQUIRED"

    reasons: list[str] = []
    if insufficient:
        reasons.append(
            "Not enough evaluation evidence to render a release decision."
        )
    if has_invalid_counts:
        reasons.append(
            "One or more criteria reported invalid case counts."
        )
    if critical_failures > 0:
        reasons.append(
            f"{critical_failures} critical check"
            f"{'' if critical_failures == 1 else 's'} failed."
        )
    if major_failures > 0 and critical_failures == 0:
        reasons.append(
            f"{major_failures} important check"
            f"{'' if major_failures == 1 else 's'} below target."
        )
    if has_error_note and critical_failures == 0:
        reasons.append(
            "One or more criteria could not be measured — they do not count as passed."
        )
    if (
        warning_count > 0
        and verdict not in ("BLOCKED", "NEEDS_FIXES")
    ):
        reasons.append(
            f"{warning_count} criterion"
            f"{'' if warning_count == 1 else 's'} at threshold or unmeasured."
        )

    overall_score_raw = dashboard.get("overall_score", 0)
    diagnostic_score = (
        round(float(overall_score_raw) * 10) / 10
        if isinstance(overall_score_raw, (int, float))
        and math.isfinite(float(overall_score_raw))
        else 0.0
    )

    return DecisionReport(
        verdict=verdict,
        confidence=confidence,
        diagnostic_score=diagnostic_score,
        evidence_passed=passed_cases,
        evidence_total=total_cases,
        critical_failures=critical_failures,
        blocking_reasons=reasons if verdict != "RELEASE_CANDIDATE" else [],
        criteria=evaluations,
        insufficient_evidence=insufficient,
    )


def decision_should_fail(
    report: DecisionReport,
    fail_on: tuple[FailSignal, ...] = DEFAULT_FAIL_ON,
) -> bool:
    """Return True when the CLI should exit non-zero.

    `LOW_CONFIDENCE_CRITICAL` is the composite signal: even on
    `RELEASE_CANDIDATE` we fail when confidence is LOW *and* at least one
    critical criterion is unmeasured / at-threshold (i.e. we don't trust
    the result enough to ship).
    """

    fail_signals = set(fail_on)
    if report.verdict in fail_signals:
        return True
    if "LOW_CONFIDENCE_CRITICAL" in fail_signals:
        if report.confidence == "LOW":
            critical_unsafe = any(
                c.tier == CRITICAL_TIER
                and (
                    c.status != "PASSED"
                    or c.has_error_note
                    or c.has_invalid_counts
                )
                for c in report.criteria
            )
            if critical_unsafe:
                return True
    return False
