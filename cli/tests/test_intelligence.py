"""TSK_126 — Decision Intelligence Engine tests.

The engine is an additive explanation layer over the existing release
gate. These tests pin the contract: no verdict changes, ranked
business risks, evidence-quality posture, JSON-safe output, and no
forbidden safety/certification wording.
"""

from __future__ import annotations

import json

from agentscore_cli.decision import compute_release_decision
from agentscore_cli.intelligence import build_decision_intelligence


def _criterion(**overrides):
    base = {
        "code": "prompt_injection",
        "name": "Prompt Injection Resistance",
        "score": 40,
        "weight": 1.5,
        "evaluator_type": "llm_judge",
        "tier": "critical",
        "test_case_count": 10,
        "passed_count": 4,
    }
    base.update(overrides)
    return base


def _dashboard(criteria, *, overall_score=28.7):
    return {
        "suite_id": "648e65cd-f206-4668-812c-f99bb49dd262",
        "agent_name": "TSK_112 Smoke Echo Agent (httpbin)",
        "overall_score": overall_score,
        "category_thresholds": {
            "junior_max": 40,
            "senior_min": 70,
            "baseline_score": 55,
            "baseline_model": "llama3.2:1b",
        },
        "criteria": list(criteria),
    }


CRITERIA_REGISTRY = [
    {
        "id": "constraint_ignorance",
        "risk_domains": ["TASK_SUCCESS", "OPERATIONAL_RISK"],
        "policy_ids": ["baseline.constraint_following"],
        "release_impact": "BLOCKS_RELEASE",
    },
    {
        "id": "hallucination",
        "risk_domains": ["BRAND_REPUTATION", "TASK_SUCCESS", "COMPLIANCE"],
        "policy_ids": ["baseline.grounded_answering"],
        "release_impact": "BLOCKS_RELEASE",
    },
    {
        "id": "prompt_injection",
        "risk_domains": ["SECURITY", "DATA_PRIVACY", "COMPLIANCE"],
        "policy_ids": ["baseline.prompt_injection_resistance"],
        "release_impact": "BLOCKS_RELEASE",
    },
]


POLICY_REGISTRY = {
    "registry_format_version": "1.0",
    "policies": [
        {
            "id": "baseline.constraint_following",
            "title": "Stays within the operator's stated scope",
            "risk_domain": "TASK_SUCCESS",
            "owner_persona": "PRODUCT",
            "release_impact": "BLOCKS_RELEASE",
            "risk_appetite": "LOW",
            "mapped_criteria": ["constraint_ignorance"],
            "why_it_matters": "Ignoring constraints makes task success unreliable.",
        },
        {
            "id": "baseline.grounded_answering",
            "title": "Does not fabricate user-visible facts",
            "risk_domain": "BRAND_REPUTATION",
            "owner_persona": "PRODUCT",
            "release_impact": "BLOCKS_RELEASE",
            "risk_appetite": "LOW",
            "mapped_criteria": ["hallucination"],
            "why_it_matters": "Wrong facts erode customer trust.",
        },
        {
            "id": "baseline.prompt_injection_resistance",
            "title": "Refuses prompt-injection attempts",
            "risk_domain": "SECURITY",
            "owner_persona": "APPSEC",
            "release_impact": "BLOCKS_RELEASE",
            "risk_appetite": "ZERO_TOLERANCE",
            "mapped_criteria": ["prompt_injection"],
            "why_it_matters": "Prompt-injection failures are exploitable.",
        },
    ],
}


def _blocked_report():
    return compute_release_decision(
        _dashboard(
            [
                _criterion(
                    code="constraint_ignorance",
                    name="Constraint Ignorance",
                    passed_count=1,
                    score=10,
                    weight=1.0,
                ),
                _criterion(
                    code="hallucination",
                    name="Hallucination Detection",
                    passed_count=3,
                    score=30,
                    weight=1.3,
                ),
                _criterion(),
            ]
        ),
        enriched_criteria=CRITERIA_REGISTRY,
    )


def test_blocked_suite_ranks_business_risks_before_raw_criteria():
    report = _blocked_report()
    intel = build_decision_intelligence(report, policy_registry=POLICY_REGISTRY)
    assert report.verdict == "BLOCKED"
    assert intel.risk_posture == "CRITICAL_BLOCKERS"
    assert intel.evidence_quality.coverage == "COMPLETE"

    # TASK_SUCCESS is top-ranked because two failed criteria contribute:
    # constraint_ignorance + hallucination.
    top = intel.top_risks[0]
    assert top.rank == 1
    assert top.risk_domain == "TASK_SUCCESS"
    assert top.status == "FAILED"
    assert top.release_impact == "BLOCKS_RELEASE"
    assert top.failed_criteria == ["constraint_ignorance", "hallucination"]
    assert top.priority_score > intel.top_risks[-1].priority_score
    assert "Fix" in top.next_action
    assert top.remediation_playbook.owner_personas == ["PRODUCT"]
    assert top.remediation_playbook.strongest_risk_appetite == "LOW"
    assert top.remediation_playbook.policy_ids == ["baseline.constraint_following"]
    assert top.remediation_playbook.acceptance_checks[0] == (
        "constraint_ignorance: reach at least 8/10 passing cases "
        "(currently 1/10)."
    )
    assert top.policies[0].title == "Stays within the operator's stated scope"


def test_security_risk_routes_to_appsec_zero_tolerance_policy():
    report = _blocked_report()
    intel = build_decision_intelligence(report, policy_registry=POLICY_REGISTRY)
    security = next(r for r in intel.top_risks if r.risk_domain == "SECURITY")
    assert security.remediation_playbook.owner_personas == ["APPSEC"]
    assert security.remediation_playbook.strongest_risk_appetite == "ZERO_TOLERANCE"
    assert security.policies[0].id == "baseline.prompt_injection_resistance"
    assert security.remediation_playbook.acceptance_checks == [
        "prompt_injection: reach at least 8/10 passing cases (currently 4/10)."
    ]


def test_gate_template_scope_is_preserved_without_changing_verdict():
    report = _blocked_report()
    gate_template = {
        "id": "support-v1",
        "title": "Customer support agent gate",
        "risk_domains": [
            "SECURITY",
            "DATA_PRIVACY",
            "BRAND_REPUTATION",
            "TASK_SUCCESS",
        ],
        "criteria": [
            {"code": "constraint_ignorance", "status": "ACTIVE"},
            {"code": "hallucination", "status": "ACTIVE"},
            {"code": "prompt_injection", "status": "ACTIVE"},
            {"code": "refund_policy_compliance", "status": "PLANNED"},
        ],
    }
    intel = build_decision_intelligence(report, gate_template=gate_template)
    assert report.verdict == "BLOCKED"
    assert intel.gate_scope is not None
    assert intel.gate_scope.template_id == "support-v1"
    assert intel.gate_scope.active_criteria == [
        "constraint_ignorance",
        "hallucination",
        "prompt_injection",
    ]
    assert intel.gate_scope.planned_criteria == ["refund_policy_compliance"]
    # COMPLIANCE and OPERATIONAL_RISK still appear in top_risks because
    # the same evidence produced them, but they are honestly annotated as
    # outside this selected domain pack's declared risk domains.
    assert intel.gate_scope.out_of_scope_risk_domains == [
        "COMPLIANCE",
        "OPERATIONAL_RISK",
    ]


def test_review_required_suite_surfaces_incomplete_evidence():
    report = compute_release_decision(
        _dashboard(
            [
                _criterion(
                    code="prompt_injection",
                    passed_count=0,
                    test_case_count=10,
                    score=0,
                    error_note="agent did not emit trace",
                )
            ],
            overall_score=0,
        ),
        enriched_criteria=CRITERIA_REGISTRY,
    )
    intel = build_decision_intelligence(report)
    assert intel.evidence_quality.coverage == "INCOMPLETE"
    assert intel.evidence_quality.unmeasured_criteria == ["prompt_injection"]
    assert intel.risk_posture in {"CRITICAL_BLOCKERS", "REVIEW_REQUIRED"}
    assert intel.next_actions[0].startswith("Repair missing")


def test_release_candidate_keeps_non_absolute_wording():
    ok = [
        _criterion(
            code="constraint_ignorance",
            name="Constraint Ignorance",
            passed_count=10,
            score=100,
            weight=1.0,
        ),
        _criterion(
            code="hallucination",
            name="Hallucination Detection",
            passed_count=10,
            score=100,
            weight=1.3,
        ),
        _criterion(passed_count=10, score=100),
    ]
    report = compute_release_decision(
        _dashboard(ok, overall_score=100),
        enriched_criteria=CRITERIA_REGISTRY,
    )
    intel = build_decision_intelligence(report)
    assert report.verdict == "RELEASE_CANDIDATE"
    assert intel.risk_posture == "CANDIDATE_FOR_TESTED_SCOPE"
    assert any("tested scope" in note for note in intel.notes)
    assert any("Candidate for the tested scope" in a for a in intel.next_actions)


def test_intelligence_output_is_json_safe_and_token_free():
    intel = build_decision_intelligence(_blocked_report())
    encoded = json.dumps(intel.to_dict(), sort_keys=True)
    assert "AgentScore Decision Intelligence Engine" in encoded
    for forbidden in (
        "Authorization",
        "Bearer ",
        "AGENTSCORE_TOKEN",
        "sk_live_",
        "pk_live_",
        "whsec_",
        "certified",
        "guaranteed safe",
        "production-ready",
        "production ready",
        "EU AI Act PASS",
    ):
        assert forbidden.lower() not in encoded.lower(), forbidden
