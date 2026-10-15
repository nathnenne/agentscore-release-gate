"""TSK_124 — tests for the PR-comment renderer.

The renderer is the only piece of the action that's pure-Python and
unit-testable in isolation; the rest (composite YAML, github-script
poster) is exercised via end-to-end smoke documented in RES_124.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


# `render_pr_comment.py` is a top-level script (not inside a package), so
# we load it through importlib to keep the test suite self-contained.
_HERE = Path(__file__).resolve().parent
_SCRIPT = _HERE.parent / "render_pr_comment.py"
_spec = importlib.util.spec_from_file_location("render_pr_comment", _SCRIPT)
assert _spec is not None and _spec.loader is not None
render_pr_comment = importlib.util.module_from_spec(_spec)
sys.modules["render_pr_comment"] = render_pr_comment
_spec.loader.exec_module(render_pr_comment)


def _blocked_artifact() -> dict[str, Any]:
    """TSK_112-style BLOCKED suite — three critical criteria failed."""
    return {
        "evidence_format_version": "1.0",
        "methodology": "AgentScore release gate v1",
        "evidence_source": "backend_per_case",
        "cli": {
            "tool": "agentscore-cli",
            "version": "0.1.0",
            "gate": "baseline-agent-v1",
            "fail_on": ["BLOCKED", "NEEDS_FIXES", "LOW_CONFIDENCE_CRITICAL"],
        },
        "suite": {
            "suite_id": "648e65cd-f206-4668-812c-f99bb49dd262",
            "agent_name": "TSK_112 Smoke Echo Agent (httpbin)",
            "started_at": "2026-05-27T09:51:00",
            "completed_at": "2026-05-27T09:53:13",
        },
        "release_decision": {
            "verdict": "BLOCKED",
            "confidence": "MEDIUM",
            "diagnostic_score": 28.7,
            "evidence_passed": 8,
            "evidence_total": 30,
            "critical_failures": 3,
            "blocking_reasons": [
                "3 critical checks failed."
            ],
            "methodology": "AgentScore release gate v1",
        },
        "decision_intelligence": {
            "engine_name": "AgentScore Decision Intelligence Engine",
            "engine_version": "1.0",
            "risk_posture": "CRITICAL_BLOCKERS",
            "evidence_quality": {
                "coverage": "COMPLETE",
                "total_cases": 30,
                "passed_cases": 8,
                "measured_criteria": 3,
                "total_criteria": 3,
                "failed_criteria": 3,
                "warning_criteria": 0,
                "unmeasured_criteria": [],
                "invalid_count_criteria": [],
                "low_sample_criteria": [],
            },
            "top_risks": [
                {
                    "rank": 1,
                    "risk_domain": "TASK_SUCCESS",
                    "status": "FAILED",
                    "release_impact": "BLOCKS_RELEASE",
                    "priority_score": 420,
                    "failed_criteria": ["constraint_ignorance", "hallucination"],
                    "warning_criteria": [],
                    "affected_criteria": [],
                    "rationale": "TASK_SUCCESS is blocked by failed criterion evidence.",
                    "next_action": (
                        "Fix constraint_ignorance, hallucination, rerun the same "
                        "gate, and compare the new evidence against this suite."
                    ),
                    "policies": [
                        {
                            "id": "baseline.constraint_following",
                            "title": "Stays within the operator's stated scope",
                            "owner_persona": "PRODUCT",
                            "risk_appetite": "LOW",
                            "release_impact": "BLOCKS_RELEASE",
                            "why_it_matters": (
                                "Scope breaks make the agent unreliable."
                            ),
                        }
                    ],
                    "remediation_playbook": {
                        "owner_personas": ["PRODUCT"],
                        "policy_ids": ["baseline.constraint_following"],
                        "strongest_risk_appetite": "LOW",
                        "steps": [
                            "Route TASK_SUCCESS remediation to: PRODUCT.",
                            (
                                "Fix or measure the blocking criteria: "
                                "constraint_ignorance, hallucination."
                            ),
                            (
                                "Review mapped policy intent: Stays within the "
                                "operator's stated scope."
                            ),
                            (
                                "Rerun the same gate and compare the new artifact "
                                "against this one."
                            ),
                        ],
                        "acceptance_checks": [
                            (
                                "constraint_ignorance: reach at least 8/10 "
                                "passing cases (currently 1/10)."
                            ),
                            (
                                "hallucination: reach at least 8/10 passing "
                                "cases (currently 3/10)."
                            ),
                        ],
                    },
                },
                {
                    "rank": 2,
                    "risk_domain": "COMPLIANCE",
                    "status": "FAILED",
                    "release_impact": "BLOCKS_RELEASE",
                    "priority_score": 405,
                    "failed_criteria": ["hallucination", "prompt_injection"],
                    "warning_criteria": [],
                    "affected_criteria": [],
                    "rationale": "COMPLIANCE is blocked by failed criterion evidence.",
                    "next_action": "Fix hallucination, prompt_injection, rerun the same gate.",
                    "policies": [],
                    "remediation_playbook": {
                        "owner_personas": [],
                        "policy_ids": [],
                        "strongest_risk_appetite": None,
                        "steps": [],
                        "acceptance_checks": [],
                    },
                },
            ],
            "next_actions": [
                "Do not release; fix the top failed business risks and rerun the same gate.",
                "Fix constraint_ignorance, hallucination, rerun the same gate, and compare the new evidence against this suite.",
            ],
            "notes": [
                "This block is an explanation layer over the existing release gate; it does not change verdict math or scoring thresholds.",
                "Release Candidate means candidate for the tested scope, not a universal safety guarantee.",
            ],
        },
        "criteria": [
            {
                "code": "constraint_ignorance",
                "name": "Constraint Ignorance",
                "tier": "critical",
                "status": "FAILED",
                "score": 10.0,
                "weight": 1.0,
                "required_passed_cases": 8,
                "actual_passed_cases": 1,
                "total_cases": 10,
                "has_error_note": False,
                "has_invalid_counts": False,
                "risk_domains": ["TASK_SUCCESS", "OPERATIONAL_RISK"],
                "policy_ids": [
                    "baseline.constraint_following",
                    "baseline.constraint_operational_risk",
                ],
                "release_impact": "BLOCKS_RELEASE",
            },
            {
                "code": "hallucination",
                "name": "Hallucination Detection",
                "tier": "critical",
                "status": "FAILED",
                "score": 30.0,
                "weight": 1.3,
                "required_passed_cases": 8,
                "actual_passed_cases": 3,
                "total_cases": 10,
                "has_error_note": False,
                "has_invalid_counts": False,
                "risk_domains": ["BRAND_REPUTATION", "TASK_SUCCESS", "COMPLIANCE"],
                "policy_ids": ["baseline.grounded_answering"],
                "release_impact": "BLOCKS_RELEASE",
            },
            {
                "code": "prompt_injection",
                "name": "Prompt Injection Resistance",
                "tier": "critical",
                "status": "FAILED",
                "score": 40.0,
                "weight": 1.5,
                "required_passed_cases": 8,
                "actual_passed_cases": 4,
                "total_cases": 10,
                "has_error_note": False,
                "has_invalid_counts": False,
                "risk_domains": ["SECURITY", "DATA_PRIVACY", "COMPLIANCE"],
                "policy_ids": ["baseline.prompt_injection_resistance"],
                "release_impact": "BLOCKS_RELEASE",
            },
        ],
        "evidence_url": "https://app.agentscore.tech/v2/suites/648e65cd-f206-4668-812c-f99bb49dd262",
    }


def _release_candidate_artifact() -> dict[str, Any]:
    art = _blocked_artifact()
    art["release_decision"]["verdict"] = "RELEASE_CANDIDATE"
    art["release_decision"]["confidence"] = "MEDIUM"
    art["release_decision"]["critical_failures"] = 0
    art["release_decision"]["blocking_reasons"] = []
    art["release_decision"]["evidence_passed"] = 30
    art["release_decision"]["diagnostic_score"] = 95.0
    for c in art["criteria"]:
        c["status"] = "PASSED"
        c["actual_passed_cases"] = 10
        c["score"] = 100
    art["decision_intelligence"] = {
        "engine_name": "AgentScore Decision Intelligence Engine",
        "engine_version": "1.0",
        "risk_posture": "CANDIDATE_FOR_TESTED_SCOPE",
        "evidence_quality": {
            "coverage": "COMPLETE",
            "total_cases": 30,
            "passed_cases": 30,
            "measured_criteria": 3,
            "total_criteria": 3,
            "failed_criteria": 0,
            "warning_criteria": 0,
            "unmeasured_criteria": [],
            "invalid_count_criteria": [],
            "low_sample_criteria": [],
        },
        "top_risks": [],
        "next_actions": [
            "Candidate for the tested scope; keep the gate in CI and monitor for drift."
        ],
        "notes": [
            "Release Candidate means candidate for the tested scope, not a universal safety guarantee."
        ],
    }
    return art


def test_blocked_artifact_renders_verdict_and_blockers():
    body = render_pr_comment.render(_blocked_artifact(), gate="baseline-agent-v1")
    # Headline carries the verdict + confidence.
    assert "AgentScore release gate: BLOCKED (MEDIUM confidence)" in body
    # Gate id surfaced.
    assert "`baseline-agent-v1`" in body
    # All three blockers listed with their risk domains and ratios.
    assert "SECURITY, DATA_PRIVACY, COMPLIANCE" in body
    assert "`prompt_injection` failed 4/10 vs gate 8/10" in body
    assert "`hallucination` failed 3/10 vs gate 8/10" in body
    assert "`constraint_ignorance` failed 1/10 vs gate 8/10" in body
    # TSK_126 decision-intelligence layer.
    assert "Decision intelligence" in body
    assert "TASK_SUCCESS: FAILED · priority 420" in body
    assert "Owners: PRODUCT · appetite: LOW" in body
    assert "Check: constraint_ignorance: reach at least 8/10" in body
    assert "Next actions" in body
    assert "Evidence quality:** COMPLETE (3/3 criteria measured)." in body
    # Evidence counts + diagnostic score.
    assert "Evidence:** 8 / 30 tests passed." in body
    assert "Diagnostic score:** 28.7/100." in body
    # Evidence report URL.
    assert (
        "https://app.agentscore.tech/v2/suites/648e65cd-f206-4668-812c-f99bb49dd262"
        in body
    )
    # Methodology line.
    assert "Methodology: AgentScore release gate v1" in body
    # MEM_005 §2 — no forbidden phrases.
    for forbidden in (
        "certified",
        "guaranteed safe",
        "production-ready",
        "production ready",
        "EU AI Act PASS",
    ):
        assert forbidden.lower() not in body.lower(), forbidden


def test_release_candidate_artifact_uses_non_absolute_wording():
    body = render_pr_comment.render(_release_candidate_artifact(), gate=None)
    assert "RELEASE_CANDIDATE" in body
    # Releases-candidate wording carries the explicit "not a universal
    # safety guarantee" line.
    assert "not a universal safety guarantee" in body
    # No "certified"-style claims.
    for forbidden in (
        "certified",
        "guaranteed safe",
        "production-ready",
        "production ready",
    ):
        assert forbidden.lower() not in body.lower(), forbidden


def test_render_handles_missing_fields_gracefully():
    minimal: dict[str, Any] = {
        "release_decision": {"verdict": "REVIEW_REQUIRED"},
    }
    body = render_pr_comment.render(minimal)
    assert "REVIEW_REQUIRED" in body
    assert "Evidence:** 0 / 0 tests passed." in body
    # No exceptions on missing suite / criteria / evidence_url.


def test_renderer_never_includes_authorization_or_token_substrings(tmp_path):
    """The renderer only consumes fields the CLI guarantees are token-free.
    Belt-and-braces: scan the body for known secret-shaped substrings."""
    body = render_pr_comment.render(_blocked_artifact())
    for forbidden in (
        "Authorization",
        "Bearer ",
        "sk_live_",
        "pk_live_",
        "pk_test_",
        "whsec_",
        "GOCSPX-",
        "AIzaSy",
        "AGENTSCORE_TOKEN",
    ):
        assert forbidden not in body, forbidden


def test_main_cli_writes_body_to_stdout(tmp_path, capsys):
    artifact_path = tmp_path / "release.json"
    artifact_path.write_text(json.dumps(_blocked_artifact()), encoding="utf-8")
    exit_code = render_pr_comment.main(
        ["--artifact", str(artifact_path), "--gate", "baseline-agent-v1"]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "AgentScore release gate: BLOCKED" in captured.out


def test_step_summary_format_adds_github_summary_heading(tmp_path, capsys):
    artifact_path = tmp_path / "release.json"
    artifact_path.write_text(json.dumps(_blocked_artifact()), encoding="utf-8")
    exit_code = render_pr_comment.main(
        [
            "--artifact",
            str(artifact_path),
            "--gate",
            "baseline-agent-v1",
            "--format",
            "step-summary",
        ]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("## AgentScore release gate")
    assert "Owners: PRODUCT · appetite: LOW" in captured.out
    assert "AGENTSCORE_TOKEN" not in captured.out


def test_main_cli_returns_2_on_missing_artifact(tmp_path, capsys):
    exit_code = render_pr_comment.main(
        ["--artifact", str(tmp_path / "does-not-exist.json")]
    )
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "artifact not found" in captured.err


def test_main_cli_returns_2_on_invalid_json(tmp_path, capsys):
    artifact = tmp_path / "broken.json"
    artifact.write_text("{not valid json", encoding="utf-8")
    exit_code = render_pr_comment.main(["--artifact", str(artifact)])
    assert exit_code == 2
    captured = capsys.readouterr()
    assert "not valid JSON" in captured.err


@pytest.mark.parametrize(
    "verdict",
    ["BLOCKED", "NEEDS_FIXES", "REVIEW_REQUIRED", "RELEASE_CANDIDATE"],
)
def test_each_verdict_produces_a_headline_block(verdict: str):
    art = _release_candidate_artifact()
    art["release_decision"]["verdict"] = verdict
    body = render_pr_comment.render(art)
    assert f"AgentScore release gate: {verdict}" in body
