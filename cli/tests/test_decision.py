"""TSK_123 — release-decision math tests.

The Python port of `lib/releaseReadiness.ts` MUST agree with the
frontend byte-for-byte, so the test fixtures mirror the frontend's
`test/ReleaseDecision.test.ts` cases (BLOCKED, NEEDS_FIXES,
REVIEW_REQUIRED, RELEASE_CANDIDATE).
"""

from __future__ import annotations

from agentscore_cli.decision import (
    DEFAULT_FAIL_ON,
    compute_release_decision,
    decision_should_fail,
)


def _criterion(**overrides):
    base = {
        "code": "prompt_injection",
        "name": "Prompt Injection Resistance",
        "score": 50,
        "weight": 1.5,
        "evaluator_type": "llm_judge",
        "tier": "critical",
        "test_case_count": 10,
        "passed_count": 8,
    }
    base.update(overrides)
    return base


def _dashboard(criteria, **overrides):
    base = {
        "suite_id": "00000000-0000-0000-0000-000000000000",
        "agent_name": "Test Agent",
        "started_at": None,
        "completed_at": None,
        "overall_score": 50,
        "category": "Mid",
        "category_thresholds": {
            "junior_max": 40,
            "senior_min": 70,
            "baseline_score": 55,
            "baseline_model": "llama3.2:1b",
        },
        "criteria": list(criteria),
        "recommendations": [],
    }
    base.update(overrides)
    return base


# --- TSK_120 / 114 parity cases ------------------------------------------- #


def test_critical_failure_projects_to_BLOCKED():
    dash = _dashboard(
        [_criterion(passed_count=1, score=10)],
        overall_score=10,
    )
    r = compute_release_decision(dash)
    assert r.verdict == "BLOCKED"
    assert r.critical_failures == 1
    assert r.evidence_passed == 1
    assert r.evidence_total == 10


def test_architecture_failure_projects_to_NEEDS_FIXES():
    passing = [
        _criterion(code="ci", name="Constraint Ignorance", passed_count=10, score=100),
        _criterion(code="hal", name="Hallucination", passed_count=10, score=100),
        _criterion(code="pi", name="Prompt Injection", passed_count=10, score=100),
    ]
    failing_arch = _criterion(
        code="tool_choice",
        name="Tool Choice Quality",
        score=30,
        weight=1,
        tier="architecture",
        passed_count=3,
    )
    r = compute_release_decision(_dashboard(passing + [failing_arch], overall_score=70))
    assert r.verdict == "NEEDS_FIXES"
    assert r.critical_failures == 0


def test_thin_evidence_projects_to_REVIEW_REQUIRED_with_LOW_confidence():
    thin = [
        _criterion(code="ci", name="Constraint Ignorance", passed_count=5, test_case_count=5, score=100),
        _criterion(code="hal", name="Hallucination", passed_count=5, test_case_count=5, score=100),
        _criterion(code="pi", name="Prompt Injection", passed_count=5, test_case_count=5, score=100),
    ]
    r = compute_release_decision(_dashboard(thin, overall_score=100))
    assert r.verdict == "REVIEW_REQUIRED"
    assert r.confidence == "LOW"


def test_adequate_evidence_projects_to_RELEASE_CANDIDATE():
    ok = [
        _criterion(code="ci", name="Constraint Ignorance", passed_count=10, test_case_count=10, score=100),
        _criterion(code="hal", name="Hallucination", passed_count=10, test_case_count=10, score=100),
        _criterion(code="pi", name="Prompt Injection", passed_count=10, test_case_count=10, score=100),
    ]
    r = compute_release_decision(_dashboard(ok, overall_score=100))
    assert r.verdict == "RELEASE_CANDIDATE"
    assert r.blocking_reasons == []


def test_diagnostic_score_is_rounded_to_one_decimal():
    r = compute_release_decision(
        _dashboard([_criterion(passed_count=1, score=10)], overall_score=28.728)
    )
    assert r.diagnostic_score == 28.7


def test_NaN_overall_score_does_not_leak():
    import math

    r = compute_release_decision(
        _dashboard([_criterion(passed_count=1, score=10)], overall_score=float("nan"))
    )
    assert math.isfinite(r.diagnostic_score)
    assert r.diagnostic_score == 0.0


def test_methodology_label_is_pinned():
    r = compute_release_decision(_dashboard([_criterion()]))
    assert r.methodology == "AgentScore release gate v1"


def test_does_not_hide_a_critical_failure():
    """Anti-goal: blocking_reasons collapsing to empty must not happen
    when a critical criterion failed."""

    r = compute_release_decision(
        _dashboard(
            [_criterion(passed_count=0, test_case_count=10, score=0)],
            overall_score=0,
        )
    )
    assert r.verdict == "BLOCKED"
    assert r.critical_failures == 1
    assert len(r.blocking_reasons) > 0


# --- exit-code rule ------------------------------------------------------- #


def test_decision_should_fail_for_blocked_under_default_fail_on():
    r = compute_release_decision(
        _dashboard(
            [_criterion(passed_count=0, test_case_count=10, score=0)],
            overall_score=0,
        )
    )
    assert decision_should_fail(r, DEFAULT_FAIL_ON) is True


def test_decision_should_fail_for_needs_fixes_under_default():
    arch_fail = _criterion(
        code="tool_choice",
        name="Tool Choice",
        score=30,
        weight=1,
        tier="architecture",
        passed_count=3,
    )
    passing = [
        _criterion(code="ci", name="Constraint Ignorance", passed_count=10, score=100),
        _criterion(code="hal", name="Hallucination", passed_count=10, score=100),
        _criterion(code="pi", name="Prompt Injection", passed_count=10, score=100),
    ]
    r = compute_release_decision(_dashboard(passing + [arch_fail], overall_score=70))
    assert r.verdict == "NEEDS_FIXES"
    assert decision_should_fail(r, DEFAULT_FAIL_ON) is True


def test_decision_should_not_fail_for_release_candidate():
    ok = [
        _criterion(code="ci", name="Constraint Ignorance", passed_count=10, test_case_count=10, score=100),
        _criterion(code="hal", name="Hallucination", passed_count=10, test_case_count=10, score=100),
        _criterion(code="pi", name="Prompt Injection", passed_count=10, test_case_count=10, score=100),
    ]
    r = compute_release_decision(_dashboard(ok, overall_score=100))
    assert r.verdict == "RELEASE_CANDIDATE"
    assert decision_should_fail(r, DEFAULT_FAIL_ON) is False


def test_LOW_CONFIDENCE_CRITICAL_fires_on_unmeasured_critical():
    """Even a clean-looking RELEASE_CANDIDATE must fail when confidence
    is LOW *and* a critical criterion is unmeasured."""

    crits = [
        _criterion(code="ci", name="Constraint Ignorance", passed_count=10, test_case_count=10, score=100),
        _criterion(code="hal", name="Hallucination", passed_count=10, test_case_count=10, score=100),
        # Third critical: error_note → unmeasured. The verdict will be
        # REVIEW_REQUIRED (because of the warning), but the
        # LOW_CONFIDENCE_CRITICAL signal independently triggers fail.
        _criterion(
            code="pi",
            name="Prompt Injection",
            passed_count=0,
            test_case_count=10,
            score=0,
            error_note="agent did not return trace",
        ),
    ]
    r = compute_release_decision(_dashboard(crits, overall_score=70))
    assert decision_should_fail(r, ("LOW_CONFIDENCE_CRITICAL",)) is True
