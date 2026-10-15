#!/usr/bin/env python3
"""TSK_124 — render the AgentScore release-gate PR comment body.

Reads the JSON artifact produced by the CLI (TSK_123) and prints a
markdown body to stdout. The body is what the action posts as a sticky
PR comment; the marker line is added by the action itself so the
sticky-update logic can find it.

Wording hygiene (MEM_005 §2 / TSK_124 §"PR Comment Contract"):
  • no "certified" / "guaranteed safe" / "production-ready" / "EU AI Act PASS";
  • methodology line is the versioned constant.

Token hygiene:
  • the artifact never carries the token (TSK_123 guarantees this);
  • this script never reads env vars, never logs anything other than
    its rendered output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

METHODOLOGY_LABEL = "AgentScore release gate v1"


VERDICT_HEADLINE = {
    "BLOCKED": "Do not release this agent yet.",
    "NEEDS_FIXES": "Fix the items below before release.",
    "REVIEW_REQUIRED": "Evidence is thin or unmeasured — manual review required.",
    "RELEASE_CANDIDATE": (
        "Critical gates passed on the tested scenarios. This is a release "
        "candidate for the tested scope, not a universal safety guarantee."
    ),
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def render(artifact: dict[str, Any], *, gate: str | None = None) -> str:
    """Render the markdown body. Pure function — unit-testable."""

    decision = artifact.get("release_decision") or {}
    verdict = str(decision.get("verdict") or "UNKNOWN")
    confidence = str(decision.get("confidence") or "UNKNOWN")
    diagnostic_score = _safe_float(decision.get("diagnostic_score"))
    evidence_passed = _safe_int(decision.get("evidence_passed"))
    evidence_total = _safe_int(decision.get("evidence_total"))

    suite = artifact.get("suite") or {}
    suite_id = str(suite.get("suite_id") or "")
    agent_name = str(suite.get("agent_name") or "")

    evidence_url = str(artifact.get("evidence_url") or "")

    criteria = artifact.get("criteria") or []
    blockers: list[dict[str, Any]] = []
    for c in criteria:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status") or "")
        has_err = bool(c.get("has_error_note")) or bool(c.get("has_invalid_counts"))
        if status == "FAILED" or has_err:
            blockers.append(c)

    intelligence = artifact.get("decision_intelligence") or {}
    top_risks = (
        intelligence.get("top_risks")
        if isinstance(intelligence, dict)
        else None
    ) or []
    next_actions = (
        intelligence.get("next_actions")
        if isinstance(intelligence, dict)
        else None
    ) or []
    evidence_quality = (
        intelligence.get("evidence_quality")
        if isinstance(intelligence, dict)
        else None
    ) or {}

    lines: list[str] = []
    lines.append(f"**AgentScore release gate: {verdict} ({confidence} confidence)**")
    lines.append("")
    if gate:
        lines.append(f"Gate: `{gate}`")
        lines.append("")
    headline = VERDICT_HEADLINE.get(verdict)
    if headline:
        lines.append(headline)
        lines.append("")
    if agent_name and suite_id:
        lines.append(f"**Agent:** {agent_name} · **Suite:** `{suite_id[:8]}`")
        lines.append("")

    if blockers:
        lines.append("**Top blockers:**")
        for i, c in enumerate(blockers[:5], 1):
            code = c.get("code") or "?"
            risk_domains = c.get("risk_domains") or []
            risk = (
                ", ".join(risk_domains)
                if risk_domains
                else (c.get("tier") or "").upper()
            )
            actual = _safe_int(c.get("actual_passed_cases"))
            required = _safe_int(c.get("required_passed_cases"))
            total = _safe_int(c.get("total_cases"))
            lines.append(
                f"{i}. {risk} — `{code}` failed {actual}/{total} vs gate {required}/{total}"
            )
        lines.append("")
    elif decision.get("blocking_reasons"):
        lines.append("**Notes:**")
        for r in decision["blocking_reasons"]:
            lines.append(f"- {r}")
        lines.append("")

    if top_risks:
        lines.append("**Decision intelligence:**")
        for i, r in enumerate(top_risks[:3], 1):
            if not isinstance(r, dict):
                continue
            domain = str(r.get("risk_domain") or "?")
            status = str(r.get("status") or "UNKNOWN")
            priority = _safe_int(r.get("priority_score"))
            criteria_list = r.get("failed_criteria") or r.get("warning_criteria") or []
            if not criteria_list:
                criteria_list = [
                    c.get("code")
                    for c in (r.get("affected_criteria") or [])
                    if isinstance(c, dict) and c.get("code")
                ]
            criteria_text = ", ".join(str(c) for c in criteria_list[:3])
            if criteria_text:
                lines.append(
                    f"{i}. {domain}: {status} · priority {priority} · {criteria_text}"
                )
            else:
                lines.append(f"{i}. {domain}: {status} · priority {priority}")
            playbook = (
                r.get("remediation_playbook")
                if isinstance(r.get("remediation_playbook"), dict)
                else {}
            )
            owners = playbook.get("owner_personas") or []
            appetite = playbook.get("strongest_risk_appetite")
            if owners or appetite:
                owner_text = (
                    ", ".join(str(o) for o in owners)
                    if owners
                    else "unassigned"
                )
                if appetite:
                    lines.append(f"   Owners: {owner_text} · appetite: {appetite}")
                else:
                    lines.append(f"   Owners: {owner_text}")
            checks = playbook.get("acceptance_checks") or []
            if checks:
                lines.append(f"   Check: {checks[0]}")
        lines.append("")

    if next_actions:
        lines.append("**Next actions:**")
        for action in next_actions[:3]:
            lines.append(f"- {action}")
        lines.append("")

    if isinstance(evidence_quality, dict) and evidence_quality:
        coverage = str(evidence_quality.get("coverage") or "UNKNOWN")
        measured = _safe_int(evidence_quality.get("measured_criteria"))
        total = _safe_int(evidence_quality.get("total_criteria"))
        lines.append(f"**Evidence quality:** {coverage} ({measured}/{total} criteria measured).")
        lines.append("")

    lines.append(
        f"**Evidence:** {evidence_passed} / {evidence_total} tests passed."
    )
    lines.append(
        f"**Diagnostic score:** {diagnostic_score}/100."
    )
    lines.append("")
    if evidence_url:
        lines.append(f"**Evidence report:** {evidence_url}")
        lines.append("")
    lines.append(f"_Methodology: {METHODOLOGY_LABEL}._")

    return "\n".join(lines)


def render_step_summary(
    artifact: dict[str, Any], *, gate: str | None = None
) -> str:
    """Render a GitHub Step Summary body from the same artifact."""

    return "## AgentScore release gate\n\n" + render(artifact, gate=gate)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="render_pr_comment",
        description=(
            "Render the AgentScore release-gate PR comment markdown body "
            "from the CLI's JSON artifact."
        ),
    )
    p.add_argument(
        "--artifact",
        required=True,
        help="Path to the JSON artifact (default name: agentscore-release-decision.json).",
    )
    p.add_argument(
        "--gate",
        default=None,
        help="Optional gate template id to show in the comment header.",
    )
    p.add_argument(
        "--format",
        choices=["comment", "step-summary"],
        default="comment",
        help="Markdown output format (default: comment).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        artifact = json.loads(Path(args.artifact).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.stderr.write(f"error: artifact not found: {args.artifact}\n")
        return 2
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"error: artifact is not valid JSON: {exc}\n")
        return 2
    if not isinstance(artifact, dict):
        sys.stderr.write("error: artifact is not a JSON object\n")
        return 2
    if args.format == "step-summary":
        sys.stdout.write(render_step_summary(artifact, gate=args.gate))
    else:
        sys.stdout.write(render(artifact, gate=args.gate))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
