"""Integration-grade release-gate outputs (TSK_128).

The primary AgentScore artifact remains the source of truth. This module
derives two standard-friendly projections from it:

* CloudEvents-compatible JSON for event buses / webhook consumers.
* SARIF 2.1.0 for code-scanning / annotation-style CI surfaces.

Both are deterministic and token-free by construction. They do not change
verdict math, thresholds, or exit codes.
"""

from __future__ import annotations

from typing import Any


CLOUDEVENTS_SPEC_VERSION = "1.0"
CLOUDEVENT_TYPE = "tech.agentscore.release_gate.decision.v1"
SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def _suite(artifact: dict[str, Any]) -> dict[str, Any]:
    suite = artifact.get("suite")
    return suite if isinstance(suite, dict) else {}


def _decision(artifact: dict[str, Any]) -> dict[str, Any]:
    decision = artifact.get("release_decision")
    return decision if isinstance(decision, dict) else {}


def _cli(artifact: dict[str, Any]) -> dict[str, Any]:
    cli = artifact.get("cli")
    return cli if isinstance(cli, dict) else {}


def _criterion_status(c: dict[str, Any]) -> str:
    return str(c.get("status") or "UNKNOWN")


def _criterion_level(c: dict[str, Any]) -> str:
    status = _criterion_status(c)
    impact = c.get("release_impact")
    if status == "FAILED" and impact == "BLOCKS_RELEASE":
        return "error"
    if status == "FAILED":
        return "warning"
    if status == "WARNING" or c.get("has_error_note") or c.get("has_invalid_counts"):
        return "warning"
    return "note"


def build_release_event(artifact: dict[str, Any]) -> dict[str, Any]:
    """Build a CloudEvents-compatible event envelope from the artifact."""

    suite = _suite(artifact)
    decision = _decision(artifact)
    cli = _cli(artifact)
    intelligence = artifact.get("decision_intelligence")
    if not isinstance(intelligence, dict):
        intelligence = {}
    suite_id = str(suite.get("suite_id") or "unknown-suite")
    verdict = str(decision.get("verdict") or "UNKNOWN")
    completed_at = suite.get("completed_at") or suite.get("started_at")
    event: dict[str, Any] = {
        "specversion": CLOUDEVENTS_SPEC_VERSION,
        "type": CLOUDEVENT_TYPE,
        "source": "https://agentscore.tech/release-gate",
        "id": f"agentscore.release-gate.{suite_id}.{verdict.lower()}",
        "subject": f"suite/{suite_id}",
        "datacontenttype": "application/json",
        "dataschema": "https://agentscore.tech/schemas/release-gate-event.v1.json",
        "data": {
            "artifact_format_version": artifact.get("evidence_format_version"),
            "methodology": artifact.get("methodology"),
            "evidence_source": artifact.get("evidence_source"),
            "gate": cli.get("gate"),
            "fail_on": list(cli.get("fail_on") or []),
            "suite": suite,
            "release_decision": decision,
            "risk_posture": intelligence.get("risk_posture"),
            "top_risks": list((intelligence.get("top_risks") or [])[:5]),
            "evidence_url": artifact.get("evidence_url"),
        },
    }
    if completed_at:
        event["time"] = completed_at
    return event


def build_sarif(artifact: dict[str, Any]) -> dict[str, Any]:
    """Build a SARIF 2.1.0 projection from the release-gate artifact."""

    criteria = [
        c for c in (artifact.get("criteria") or []) if isinstance(c, dict)
    ]
    evidence_url = str(artifact.get("evidence_url") or "")
    rules = []
    results = []
    for c in criteria:
        code = str(c.get("code") or "unknown_criterion")
        risk_domains = list(c.get("risk_domains") or [])
        policy_ids = list(c.get("policy_ids") or [])
        rules.append(
            {
                "id": code,
                "name": str(c.get("name") or code),
                "shortDescription": {"text": str(c.get("name") or code)},
                "fullDescription": {
                    "text": (
                        f"AgentScore criterion {code}; tier={c.get('tier')}; "
                        f"release_impact={c.get('release_impact') or 'UNKNOWN'}."
                    )
                },
                "help": {
                    "text": (
                        "This result is evidence-backed release-gate output. "
                        "It is not a certification or universal safety claim."
                    )
                },
                "properties": {
                    "risk_domains": risk_domains,
                    "policy_ids": policy_ids,
                    "tier": c.get("tier"),
                    "release_impact": c.get("release_impact"),
                },
            }
        )
        status = _criterion_status(c)
        if status == "PASSED" and not c.get("has_error_note") and not c.get(
            "has_invalid_counts"
        ):
            continue
        actual = c.get("actual_passed_cases")
        required = c.get("required_passed_cases")
        total = c.get("total_cases")
        message = (
            f"{code} {status}: {actual}/{total} passing cases vs gate "
            f"{required}/{total}."
        )
        if c.get("has_error_note"):
            message = f"{message} Evidence error: {c.get('error_note')}"
        results.append(
            {
                "ruleId": code,
                "level": _criterion_level(c),
                "message": {"text": message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": evidence_url or f"agentscore://criteria/{code}"
                            }
                        }
                    }
                ],
                "properties": {
                    "status": status,
                    "risk_domains": risk_domains,
                    "policy_ids": policy_ids,
                    "actual_passed_cases": actual,
                    "required_passed_cases": required,
                    "total_cases": total,
                    "release_impact": c.get("release_impact"),
                },
            }
        )
    return {
        "version": SARIF_VERSION,
        "$schema": SARIF_SCHEMA,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "AgentScore",
                        "informationUri": "https://agentscore.tech",
                        "rules": rules,
                    }
                },
                "results": results,
                "properties": {
                    "methodology": artifact.get("methodology"),
                    "evidence_url": evidence_url,
                    "verdict": _decision(artifact).get("verdict"),
                    "confidence": _decision(artifact).get("confidence"),
                },
            }
        ],
    }
