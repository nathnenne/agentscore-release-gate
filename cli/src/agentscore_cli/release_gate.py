"""`agentscore release-gate` command implementation (TSK_123).

Pure orchestration: fetch /dashboard + /criteria/registry + /evidence
(when available), run `compute_release_decision`, write the JSON
artifact, print a short terminal summary, and return the exit code.

All HTTP failures are caught at the boundary and rendered as a
single-line, secret-free error. The token never appears in the JSON
artifact, stdout, stderr, or any error message.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, TextIO

from .api import AgentScoreApiError, AgentScoreClient, DEFAULT_API_URL
from .config import Config
from .decision import (
    DEFAULT_FAIL_ON,
    DecisionReport,
    compute_release_decision,
    decision_should_fail,
)
from .intelligence import DecisionIntelligence, build_decision_intelligence
from .integration import build_release_event, build_sarif


EVIDENCE_FORMAT_VERSION = "1.0"
METHODOLOGY_LABEL = "AgentScore release gate v1"


def _evidence_url(api_url: str, suite_id: str) -> str:
    """Best-effort app URL for the suite. Falls back to the API base."""
    # Convention from the production deploy: app subdomain mirrors the
    # api subdomain. We keep this purely as a hint shown to the user;
    # the CLI never depends on the app URL for any decision.
    if "://api." in api_url:
        return api_url.replace("://api.", "://app.").rstrip("/") + (
            f"/v2/suites/{suite_id}"
        )
    return api_url.rstrip("/") + f"/v2/suites/{suite_id}"


def _build_artifact(
    *,
    dashboard: dict[str, Any],
    report: DecisionReport,
    intelligence: DecisionIntelligence,
    gate_id: str,
    fail_on: tuple[str, ...],
    evidence: dict[str, Any] | None,
    evidence_url: str,
) -> dict[str, Any]:
    """Build the on-disk JSON artifact. Same shape as the frontend
    `EvidenceExport`, plus a `cli` metadata block. Token-free by
    construction (we never store the bearer anywhere)."""

    return {
        "evidence_format_version": EVIDENCE_FORMAT_VERSION,
        "methodology": METHODOLOGY_LABEL,
        "evidence_source": (
            "backend_per_case" if evidence else "dashboard_aggregate"
        ),
        "cli": {
            "tool": "agentscore-cli",
            "version": "0.1.0",
            "gate": gate_id,
            "fail_on": list(fail_on),
        },
        "suite": {
            "suite_id": dashboard.get("suite_id"),
            "agent_name": dashboard.get("agent_name"),
            "started_at": dashboard.get("started_at"),
            "completed_at": dashboard.get("completed_at"),
        },
        "release_decision": {
            "verdict": report.verdict,
            "confidence": report.confidence,
            "diagnostic_score": report.diagnostic_score,
            "evidence_passed": report.evidence_passed,
            "evidence_total": report.evidence_total,
            "critical_failures": report.critical_failures,
            "blocking_reasons": list(report.blocking_reasons),
            "methodology": METHODOLOGY_LABEL,
        },
        "decision_intelligence": intelligence.to_dict(),
        "criteria": [
            {
                **{k: v for k, v in asdict(c).items()},
                "evidence": (
                    _evidence_for(evidence, c.code) if evidence else None
                ),
            }
            for c in report.criteria
        ],
        "evidence_url": evidence_url,
    }


def _evidence_for(
    evidence: dict[str, Any], criterion_code: str
) -> list[dict[str, Any]]:
    for c in evidence.get("criteria") or []:
        if c.get("criterion_code") == criterion_code:
            return list(c.get("evidence") or [])
    return []


def _print_summary(
    *,
    report: DecisionReport,
    intelligence: DecisionIntelligence,
    suite_id: str,
    evidence_url: str,
    gate_id: str,
    stdout: TextIO,
) -> None:
    """Render the terminal summary. Never echoes the token or any
    request header. Wording mirrors the frontend `buildHumanSummary`
    and refuses the forbidden phrases from MEM_005 §2."""

    stdout.write(
        f"AgentScore release gate: {report.verdict} ({report.confidence} confidence)\n"
    )
    stdout.write(f"Gate: {gate_id}\n")
    stdout.write("\n")

    blockers = [
        c
        for c in report.criteria
        if c.status == "FAILED" or c.has_error_note or c.has_invalid_counts
    ]
    if blockers:
        stdout.write("Top blockers:\n")
        for i, c in enumerate(blockers, 1):
            risk = ", ".join(c.risk_domains) if c.risk_domains else c.tier.upper()
            stdout.write(
                f"{i}. {risk} — {c.code} failed "
                f"{c.actual_passed_cases}/{c.total_cases} vs gate "
                f"{c.required_passed_cases}/{c.total_cases}\n"
            )
        stdout.write("\n")
    elif report.blocking_reasons:
        stdout.write("Notes:\n")
        for r in report.blocking_reasons:
            stdout.write(f"  • {r}\n")
        stdout.write("\n")

    if intelligence.top_risks:
        stdout.write("Decision intelligence:\n")
        for r in intelligence.top_risks[:3]:
            criteria = ", ".join(
                r.failed_criteria or r.warning_criteria
            ) or ", ".join(c.code for c in r.affected_criteria[:3])
            stdout.write(
                f"{r.rank}. {r.risk_domain} — {r.status} "
                f"(priority {r.priority_score}; criteria: {criteria})\n"
            )
        stdout.write("\n")

    stdout.write(
        f"Evidence: {report.evidence_passed} / {report.evidence_total} tests passed."
        "\n"
    )
    stdout.write(
        f"Diagnostic score: {report.diagnostic_score}/100. "
        f"Methodology: {METHODOLOGY_LABEL}.\n"
    )
    stdout.write("\n")
    stdout.write(f"Evidence report:\n{evidence_url}\n")


def run(
    *,
    config: Config,
    token: str,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    fetch_evidence: bool = True,
) -> int:
    """Execute the `release-gate` command. Returns the process exit code.

    Caller is responsible for keeping `token` out of any logging
    surface; this function never echoes it.
    """

    api_url = config.api_url or DEFAULT_API_URL
    suite_id = config.suite_id
    if not suite_id:
        stderr.write(
            "error: no suite id (pass --suite or set suite_id in agentscore.yml)\n"
        )
        return 2

    try:
        with AgentScoreClient(api_url=api_url, token=token) as client:
            # Validate the gate id against the live registry — strict,
            # so a typo doesn't silently fall back to baseline.
            registry = client.get_gate_template_registry()
            templates = [
                t for t in (registry.get("templates") or []) if isinstance(t, dict)
            ]
            valid_gates = {t.get("id") for t in templates}
            if config.gate not in valid_gates:
                stderr.write(
                    f"error: unknown gate {config.gate!r}. "
                    f"Known gates: {sorted(g for g in valid_gates if g)}\n"
                )
                return 2
            gate_template = next(
                (t for t in templates if t.get("id") == config.gate),
                None,
            )

            dashboard = client.get_suite_dashboard(suite_id)
            criteria_registry = client.get_criterion_registry()
            policy_registry = None
            try:
                policy_registry = client.get_policy_registry()
            except AgentScoreApiError as exc:
                stderr.write(
                    f"warning: could not fetch policy registry ({exc.status_code}); "
                    "writing decision intelligence without policy metadata.\n"
                )
            evidence = None
            if fetch_evidence:
                try:
                    evidence = client.get_suite_evidence(suite_id)
                except AgentScoreApiError as exc:
                    # Soft-fail: still produce the aggregate artifact.
                    stderr.write(
                        f"warning: could not fetch per-case evidence ({exc.status_code}); "
                        "writing aggregate-only artifact.\n"
                    )

        report = compute_release_decision(
            dashboard, enriched_criteria=criteria_registry.get("criteria")
        )
        intelligence = build_decision_intelligence(
            report,
            gate_template=gate_template,
            policy_registry=policy_registry,
        )
        artifact = _build_artifact(
            dashboard=dashboard,
            report=report,
            intelligence=intelligence,
            gate_id=config.gate,
            fail_on=config.fail_on,
            evidence=evidence,
            evidence_url=_evidence_url(api_url, suite_id),
        )

        try:
            Path(config.output_json).write_text(
                json.dumps(artifact, indent=2, sort_keys=False),
                encoding="utf-8",
            )
        except OSError as exc:
            stderr.write(
                f"error: could not write {config.output_json}: {exc}\n"
            )
            return 2
        if config.output_event:
            try:
                Path(config.output_event).write_text(
                    json.dumps(
                        build_release_event(artifact),
                        indent=2,
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                stderr.write(
                    f"error: could not write {config.output_event}: {exc}\n"
                )
                return 2
        if config.output_sarif:
            try:
                Path(config.output_sarif).write_text(
                    json.dumps(
                        build_sarif(artifact),
                        indent=2,
                        sort_keys=False,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                stderr.write(
                    f"error: could not write {config.output_sarif}: {exc}\n"
                )
                return 2

        _print_summary(
            report=report,
            intelligence=intelligence,
            suite_id=suite_id,
            evidence_url=_evidence_url(api_url, suite_id),
            gate_id=config.gate,
            stdout=stdout,
        )

        return 1 if decision_should_fail(report, config.fail_on) else 0

    except AgentScoreApiError as exc:
        stderr.write(f"error: {exc}\n")
        return 2
