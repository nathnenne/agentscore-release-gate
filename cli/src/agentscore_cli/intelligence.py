"""Decision-intelligence layer for AgentScore release-gate artifacts.

This module is deliberately additive: it does **not** change release
verdict math, thresholds, evaluator prompts, scoring constants, or exit
codes. It reads the already-computed :class:`DecisionReport` and turns
it into a ranked, business-readable risk/action model:

  * Which business risks are blocking release?
  * Which criteria caused each risk?
  * Is the evidence complete enough to trust the result?
  * What should the team fix or measure next?

Competitor angle: most eval tools stop at a score or a failing test
list. This layer turns the same evidence into a decision brief a PR
reviewer, product owner, or security lead can act on without hiding the
underlying criterion data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from .decision import CriterionEvaluation, DecisionReport


ENGINE_NAME = "AgentScore Decision Intelligence Engine"
ENGINE_VERSION = "1.0"


RiskPosture = Literal[
    "CRITICAL_BLOCKERS",
    "FIX_REQUIRED",
    "REVIEW_REQUIRED",
    "CANDIDATE_FOR_TESTED_SCOPE",
]

EvidenceCoverage = Literal[
    "COMPLETE",
    "THIN",
    "INCOMPLETE",
    "INVALID",
]


_TIER_WEIGHT: dict[str, int] = {
    "critical": 100,
    "architecture": 60,
    "style": 30,
}

_STATUS_WEIGHT: dict[str, int] = {
    "FAILED": 50,
    "WARNING": 25,
    "PASSED": 0,
}

_IMPACT_WEIGHT: dict[str, int] = {
    "BLOCKS_RELEASE": 30,
    "REQUIRES_REVIEW": 15,
    "ADVISORY": 0,
}

_APPETITE_ORDER: dict[str, int] = {
    "ZERO_TOLERANCE": 3,
    "LOW": 2,
    "MEDIUM": 1,
}


@dataclass(frozen=True)
class RiskCriterion:
    """A criterion contributing to one business-risk row."""

    code: str
    status: str
    tier: str
    release_impact: str | None
    actual_passed_cases: int
    required_passed_cases: int
    total_cases: int
    gap_to_gate: int
    has_error_note: bool
    has_invalid_counts: bool


@dataclass(frozen=True)
class PolicyReference:
    """Policy metadata mapped to a business-risk row."""

    id: str
    title: str
    owner_persona: str
    risk_appetite: str
    release_impact: str
    why_it_matters: str


@dataclass(frozen=True)
class RemediationPlaybook:
    """Action plan derived from failed evidence + policy ownership."""

    owner_personas: list[str]
    policy_ids: list[str]
    strongest_risk_appetite: str | None
    steps: list[str]
    acceptance_checks: list[str]


@dataclass(frozen=True)
class TopRisk:
    """One ranked business-risk row."""

    rank: int
    risk_domain: str
    status: str
    release_impact: str | None
    priority_score: int
    failed_criteria: list[str]
    warning_criteria: list[str]
    affected_criteria: list[RiskCriterion]
    policies: list[PolicyReference]
    remediation_playbook: RemediationPlaybook
    rationale: str
    next_action: str


@dataclass(frozen=True)
class EvidenceQuality:
    """Coverage/readiness of the evidence set behind the decision."""

    coverage: EvidenceCoverage
    total_cases: int
    passed_cases: int
    measured_criteria: int
    total_criteria: int
    failed_criteria: int
    warning_criteria: int
    unmeasured_criteria: list[str] = field(default_factory=list)
    invalid_count_criteria: list[str] = field(default_factory=list)
    low_sample_criteria: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateScope:
    """How the selected gate template scopes the decision brief.

    This is informational only. It helps downstream comments and JSON
    consumers understand which risk domains / criteria the selected
    gate template declares, without changing the release verdict.
    """

    template_id: str
    title: str | None
    risk_domains: list[str]
    active_criteria: list[str]
    planned_criteria: list[str]
    out_of_scope_risk_domains: list[str]


@dataclass(frozen=True)
class DecisionIntelligence:
    """JSON-safe decision-intelligence report."""

    engine_name: str
    engine_version: str
    risk_posture: RiskPosture
    gate_scope: GateScope | None
    evidence_quality: EvidenceQuality
    top_risks: list[TopRisk]
    next_actions: list[str]
    notes: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _risk_posture(report: DecisionReport) -> RiskPosture:
    if report.verdict == "BLOCKED":
        return "CRITICAL_BLOCKERS"
    if report.verdict == "NEEDS_FIXES":
        return "FIX_REQUIRED"
    if report.verdict == "REVIEW_REQUIRED":
        return "REVIEW_REQUIRED"
    return "CANDIDATE_FOR_TESTED_SCOPE"


def _criterion_priority(c: CriterionEvaluation) -> int:
    gap = max(0, c.required_passed_cases - c.actual_passed_cases)
    score = _TIER_WEIGHT.get(c.tier, 20)
    score += _STATUS_WEIGHT.get(c.status, 0)
    if c.release_impact:
        score += _IMPACT_WEIGHT.get(c.release_impact, 0)
    score += gap * 5
    if c.has_error_note:
        score += 20
    if c.has_invalid_counts:
        score += 25
    return score


def _dominant_status(criteria: list[CriterionEvaluation]) -> str:
    if any(c.status == "FAILED" for c in criteria):
        return "FAILED"
    if any(c.status == "WARNING" for c in criteria):
        return "WARNING"
    return "PASSED"


def _dominant_impact(criteria: list[CriterionEvaluation]) -> str | None:
    impacts = [c.release_impact for c in criteria if c.release_impact]
    if "BLOCKS_RELEASE" in impacts:
        return "BLOCKS_RELEASE"
    if "REQUIRES_REVIEW" in impacts:
        return "REQUIRES_REVIEW"
    if "ADVISORY" in impacts:
        return "ADVISORY"
    return None


def _criterion_row(c: CriterionEvaluation) -> RiskCriterion:
    return RiskCriterion(
        code=c.code,
        status=c.status,
        tier=c.tier,
        release_impact=c.release_impact,
        actual_passed_cases=c.actual_passed_cases,
        required_passed_cases=c.required_passed_cases,
        total_cases=c.total_cases,
        gap_to_gate=max(0, c.required_passed_cases - c.actual_passed_cases),
        has_error_note=c.has_error_note,
        has_invalid_counts=c.has_invalid_counts,
    )


def _build_rationale(domain: str, criteria: list[CriterionEvaluation]) -> str:
    failed = [c.code for c in criteria if c.status == "FAILED"]
    warnings = [
        c.code
        for c in criteria
        if c.status == "WARNING" or c.has_error_note or c.has_invalid_counts
    ]
    if failed:
        return (
            f"{domain} is blocked by failed criterion evidence: "
            f"{', '.join(failed)}."
        )
    if warnings:
        return (
            f"{domain} needs review because evidence is thin, at-threshold, "
            f"or unmeasured for: {', '.join(warnings)}."
        )
    return f"{domain} passed on the measured criteria in this suite."


def _build_next_action(domain: str, criteria: list[CriterionEvaluation]) -> str:
    blockers = [
        c
        for c in criteria
        if c.status == "FAILED" or c.has_error_note or c.has_invalid_counts
    ]
    if not blockers:
        return f"Keep {domain} in the gate and monitor it on the next run."
    ordered = sorted(
        blockers,
        key=lambda c: (-_criterion_priority(c), c.code),
    )
    codes = ", ".join(c.code for c in ordered[:3])
    if any(c.has_error_note or c.has_invalid_counts for c in ordered):
        return (
            f"Restore measurable evidence for {codes}, then rerun the gate "
            f"before release."
        )
    return (
        f"Fix {codes}, rerun the same gate, and compare the new evidence "
        f"against this suite."
    )


def _policy_registry_by_id(
    policy_registry: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not policy_registry:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for p in policy_registry.get("policies") or []:
        if isinstance(p, dict) and isinstance(p.get("id"), str):
            out[p["id"]] = p
    return out


def _policies_for_domain(
    domain: str,
    criteria: list[CriterionEvaluation],
    policies_by_id: dict[str, dict[str, Any]],
) -> list[PolicyReference]:
    refs: dict[str, PolicyReference] = {}
    for c in criteria:
        for policy_id in c.policy_ids:
            raw = policies_by_id.get(policy_id)
            if not raw or raw.get("risk_domain") != domain:
                continue
            refs[policy_id] = PolicyReference(
                id=policy_id,
                title=str(raw.get("title") or policy_id),
                owner_persona=str(raw.get("owner_persona") or "PRODUCT"),
                risk_appetite=str(raw.get("risk_appetite") or "MEDIUM"),
                release_impact=str(
                    raw.get("release_impact") or c.release_impact or "ADVISORY"
                ),
                why_it_matters=str(raw.get("why_it_matters") or ""),
            )
    return sorted(refs.values(), key=lambda p: p.id)


def _strongest_risk_appetite(policies: list[PolicyReference]) -> str | None:
    if not policies:
        return None
    return max(
        (p.risk_appetite for p in policies),
        key=lambda a: _APPETITE_ORDER.get(a, 0),
    )


def _owner_personas(policies: list[PolicyReference]) -> list[str]:
    return sorted({p.owner_persona for p in policies})


def _acceptance_checks(criteria: list[CriterionEvaluation]) -> list[str]:
    checks: list[str] = []
    for c in sorted(criteria, key=lambda c: (-_criterion_priority(c), c.code)):
        if c.has_invalid_counts:
            checks.append(
                f"{c.code}: restore valid case counts before evaluating release."
            )
        elif c.has_error_note or c.total_cases == 0:
            checks.append(f"{c.code}: produce measurable evaluator output.")
        elif c.status != "PASSED":
            checks.append(
                f"{c.code}: reach at least "
                f"{c.required_passed_cases}/{c.total_cases} passing cases "
                f"(currently {c.actual_passed_cases}/{c.total_cases})."
            )
    return checks[:5]


def _remediation_playbook(
    domain: str,
    criteria: list[CriterionEvaluation],
    policies: list[PolicyReference],
) -> RemediationPlaybook:
    owners = _owner_personas(policies)
    blockers = [
        c
        for c in criteria
        if c.status == "FAILED" or c.has_error_note or c.has_invalid_counts
    ]
    blocker_codes = ", ".join(
        c.code
        for c in sorted(
            blockers,
            key=lambda c: (-_criterion_priority(c), c.code),
        )[:3]
    )
    steps: list[str] = []
    if owners:
        steps.append(f"Route {domain} remediation to: {', '.join(owners)}.")
    if blocker_codes:
        steps.append(f"Fix or measure the blocking criteria: {blocker_codes}.")
    if policies:
        policy_titles = ", ".join(p.title for p in policies[:3])
        steps.append(f"Review mapped policy intent: {policy_titles}.")
    steps.append("Rerun the same gate and compare the new artifact against this one.")
    checks = _acceptance_checks(blockers or criteria)
    if not checks:
        checks = [f"{domain}: keep monitored in CI on the next run."]
    return RemediationPlaybook(
        owner_personas=owners,
        policy_ids=[p.id for p in policies],
        strongest_risk_appetite=_strongest_risk_appetite(policies),
        steps=steps,
        acceptance_checks=checks,
    )


def _group_by_risk_domain(
    criteria: list[CriterionEvaluation],
) -> dict[str, list[CriterionEvaluation]]:
    grouped: dict[str, list[CriterionEvaluation]] = {}
    for c in criteria:
        domains = c.risk_domains or [c.tier.upper()]
        for domain in domains:
            grouped.setdefault(domain, []).append(c)
    return grouped


def _top_risks(
    criteria: list[CriterionEvaluation],
    policies_by_id: dict[str, dict[str, Any]] | None = None,
) -> list[TopRisk]:
    rows: list[TopRisk] = []
    policies_by_id = policies_by_id or {}
    for domain, domain_criteria in _group_by_risk_domain(criteria).items():
        priority = sum(_criterion_priority(c) for c in domain_criteria)
        policies = _policies_for_domain(domain, domain_criteria, policies_by_id)
        playbook = _remediation_playbook(domain, domain_criteria, policies)
        failed = sorted(c.code for c in domain_criteria if c.status == "FAILED")
        warnings = sorted(
            c.code
            for c in domain_criteria
            if c.status == "WARNING" or c.has_error_note or c.has_invalid_counts
        )
        affected = sorted(
            (_criterion_row(c) for c in domain_criteria),
            key=lambda r: (-r.gap_to_gate, r.code),
        )
        rows.append(
            TopRisk(
                rank=0,
                risk_domain=domain,
                status=_dominant_status(domain_criteria),
                release_impact=_dominant_impact(domain_criteria),
                priority_score=priority,
                failed_criteria=failed,
                warning_criteria=warnings,
                affected_criteria=affected,
                policies=policies,
                remediation_playbook=playbook,
                rationale=_build_rationale(domain, domain_criteria),
                next_action=_build_next_action(domain, domain_criteria),
            )
        )
    ordered = sorted(
        rows,
        key=lambda r: (
            -r.priority_score,
            r.status != "FAILED",
            r.risk_domain,
        ),
    )
    return [
        TopRisk(
            rank=i,
            risk_domain=r.risk_domain,
            status=r.status,
            release_impact=r.release_impact,
            priority_score=r.priority_score,
            failed_criteria=r.failed_criteria,
            warning_criteria=r.warning_criteria,
            affected_criteria=r.affected_criteria,
            policies=r.policies,
            remediation_playbook=r.remediation_playbook,
            rationale=r.rationale,
            next_action=r.next_action,
        )
        for i, r in enumerate(ordered, 1)
    ]


def _evidence_quality(report: DecisionReport) -> EvidenceQuality:
    criteria = report.criteria
    failed = [c for c in criteria if c.status == "FAILED"]
    warnings = [c for c in criteria if c.status == "WARNING"]
    unmeasured = sorted(c.code for c in criteria if c.has_error_note)
    invalid = sorted(c.code for c in criteria if c.has_invalid_counts)
    low_sample = sorted(
        c.code
        for c in criteria
        if c.total_cases > 0 and c.total_cases < 5
    )
    if invalid:
        coverage: EvidenceCoverage = "INVALID"
    elif unmeasured or report.insufficient_evidence:
        coverage = "INCOMPLETE"
    elif low_sample or report.confidence == "LOW":
        coverage = "THIN"
    else:
        coverage = "COMPLETE"
    return EvidenceQuality(
        coverage=coverage,
        total_cases=report.evidence_total,
        passed_cases=report.evidence_passed,
        measured_criteria=sum(
            1
            for c in criteria
            if not c.has_error_note and not c.has_invalid_counts and c.total_cases > 0
        ),
        total_criteria=len(criteria),
        failed_criteria=len(failed),
        warning_criteria=len(warnings),
        unmeasured_criteria=unmeasured,
        invalid_count_criteria=invalid,
        low_sample_criteria=low_sample,
    )


def _global_actions(
    report: DecisionReport,
    top_risks: list[TopRisk],
    quality: EvidenceQuality,
) -> list[str]:
    actions: list[str] = []
    if quality.coverage in {"INVALID", "INCOMPLETE"}:
        actions.append(
            "Repair missing or invalid criterion evidence before trusting "
            "the release decision."
        )
    elif quality.coverage == "THIN":
        actions.append(
            "Collect more evidence for low-sample criteria before treating "
            "the result as high-confidence."
        )
    if report.verdict == "BLOCKED":
        actions.append(
            "Do not release; fix the top failed business risks and rerun "
            "the same gate."
        )
    elif report.verdict == "NEEDS_FIXES":
        actions.append("Fix the important failed checks before release.")
    elif report.verdict == "REVIEW_REQUIRED":
        actions.append("Route this suite to manual review with the evidence artifact.")
    else:
        actions.append(
            "Candidate for the tested scope; keep the gate in CI and monitor "
            "for drift."
        )
    for r in top_risks[:3]:
        if r.next_action not in actions:
            actions.append(r.next_action)
    return actions[:5]


def _gate_scope(
    gate_template: dict[str, Any] | None,
    top_risks: list[TopRisk],
) -> GateScope | None:
    if not gate_template:
        return None
    bindings = [
        b for b in (gate_template.get("criteria") or []) if isinstance(b, dict)
    ]
    active = sorted(
        str(b.get("code"))
        for b in bindings
        if b.get("status") == "ACTIVE" and b.get("code")
    )
    planned = sorted(
        str(b.get("code"))
        for b in bindings
        if b.get("status") == "PLANNED" and b.get("code")
    )
    risk_domains = [
        str(d)
        for d in (gate_template.get("risk_domains") or [])
        if isinstance(d, str)
    ]
    scoped = set(risk_domains)
    out_of_scope = sorted(
        r.risk_domain
        for r in top_risks
        if scoped and r.risk_domain not in scoped
    )
    return GateScope(
        template_id=str(gate_template.get("id") or ""),
        title=(
            str(gate_template.get("title"))
            if gate_template.get("title") is not None
            else None
        ),
        risk_domains=risk_domains,
        active_criteria=active,
        planned_criteria=planned,
        out_of_scope_risk_domains=out_of_scope,
    )


def build_decision_intelligence(
    report: DecisionReport,
    *,
    gate_template: dict[str, Any] | None = None,
    policy_registry: dict[str, Any] | None = None,
) -> DecisionIntelligence:
    """Build the ranked decision-intelligence layer for one report."""

    top = _top_risks(
        report.criteria,
        policies_by_id=_policy_registry_by_id(policy_registry),
    )
    quality = _evidence_quality(report)
    notes: list[str] = [
        "This block is an explanation layer over the existing release gate; "
        "it does not change verdict math or scoring thresholds.",
        "Release Candidate means candidate for the tested scope, not a "
        "universal safety guarantee.",
    ]
    if not top:
        notes.append("No criterion evidence was available to rank business risks.")
    return DecisionIntelligence(
        engine_name=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        risk_posture=_risk_posture(report),
        gate_scope=_gate_scope(gate_template, top),
        evidence_quality=quality,
        top_risks=top,
        next_actions=_global_actions(report, top, quality),
        notes=notes,
    )
