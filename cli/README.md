# agentscore-cli

Developer-led release gate for AI agents. Reads a v2 suite from the
AgentScore backend, returns a verdict, writes a JSON artifact, and exits
0/1 for CI.

> Score is not opinion. Score is weighted evidence.

## Install (MVP, source)

```bash
pip install "git+https://github.com/nathnenne/agentscore-release-gate#subdirectory=cli"
# or: pipx install ./cli
```

A standalone PyPI release lands in a follow-up task.

## Usage

```bash
export AGENTSCORE_TOKEN=$YOUR_CLERK_JWT       # template: agentscore_api
agentscore release-gate --suite 648e65cd-f206-4668-812c-f99bb49dd262
echo $?                                       # 0 / 1 / 2
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Configured gate passed — `RELEASE_CANDIDATE` (and no `LOW_CONFIDENCE_CRITICAL` trigger). |
| `1` | Configured gate failed (`BLOCKED`, `NEEDS_FIXES`, or `LOW_CONFIDENCE_CRITICAL`). |
| `2` | Usage / configuration / network error (no decision could be made). |

The set of verdicts that cause exit `1` is configured by `--fail-on`
(comma-separated) or `fail_on:` in `agentscore.yml`. Allowed values:
`BLOCKED`, `NEEDS_FIXES`, `REVIEW_REQUIRED`, `LOW_CONFIDENCE_CRITICAL`.

### `agentscore.yml`

```yaml
api_url: https://api.agentscore.tech
suite_id: 648e65cd-f206-4668-812c-f99bb49dd262
gate: baseline-agent-v1
fail_on:
  - BLOCKED
  - NEEDS_FIXES
  - LOW_CONFIDENCE_CRITICAL
output:
  json: agentscore-release-decision.json
  event: agentscore-release-decision.event.json
  sarif: agentscore-release-decision.sarif
```

Precedence: explicit CLI flags > env vars > `agentscore.yml` > built-in
defaults.

### Token handling

| Surface | Behaviour |
| --- | --- |
| Source | `AGENTSCORE_TOKEN` env var or `--token`. |
| Logging | Never echoed to stdout, stderr, or the JSON artifact. |
| HTTP errors | Scrubbed for known secret-shaped substrings before being shown. |

`AGENTSCORE_TOKEN` is an AgentScore API key (`ags_key_…`, created in
Settings → API keys). A Clerk session JWT from the `agentscore_api`
template also works, but expires within minutes — use a key in CI.

`agentscore release-gate --agent <bot-uuid> --run-key <commit-sha>` starts
a full gate run, waits for it (`--wait-timeout`, default 30 min), and then
evaluates it. A run that fails to measure exits 2 — never a verdict.

## JSON artifact shape

```jsonc
{
  "evidence_format_version": "1.0",
  "methodology": "AgentScore release gate v1",
  "evidence_source": "backend_per_case",        // or "dashboard_aggregate"
  "cli": { "tool": "agentscore-cli", "version": "0.1.0", "gate": "...", "fail_on": [...] },
  "suite": {
    "suite_id": "...",
    "agent_name": "...",
    "started_at": "...",
    "completed_at": "..."
  },
  "release_decision": {
    "verdict": "BLOCKED",                       // BLOCKED|NEEDS_FIXES|REVIEW_REQUIRED|RELEASE_CANDIDATE
    "confidence": "MEDIUM",                     // LOW|MEDIUM|HIGH
    "diagnostic_score": 28.7,
    "evidence_passed": 8,
    "evidence_total": 30,
    "critical_failures": 3,
    "blocking_reasons": [...],
    "methodology": "AgentScore release gate v1"
  },
  "decision_intelligence": {
    "engine_name": "AgentScore Decision Intelligence Engine",
    "engine_version": "1.0",
    "risk_posture": "CRITICAL_BLOCKERS",
    "gate_scope": {
      "template_id": "baseline-agent-v1",
      "title": "Baseline agent release gate (v1)",
      "risk_domains": ["SECURITY", "DATA_PRIVACY", "COMPLIANCE", "BRAND_REPUTATION", "TASK_SUCCESS", "OPERATIONAL_RISK"],
      "active_criteria": ["constraint_ignorance", "hallucination", "prompt_injection"],
      "planned_criteria": [],
      "out_of_scope_risk_domains": []
    },
    "evidence_quality": {
      "coverage": "COMPLETE",
      "total_cases": 30,
      "passed_cases": 8,
      "measured_criteria": 3,
      "total_criteria": 3
    },
    "top_risks": [
      {
        "rank": 1,
        "risk_domain": "TASK_SUCCESS",
        "status": "FAILED",
        "priority_score": 420,
        "failed_criteria": ["constraint_ignorance", "hallucination"],
        "policies": [
          {
            "id": "baseline.constraint_following",
            "title": "Stays within the operator's stated scope",
            "owner_persona": "PRODUCT",
            "risk_appetite": "LOW",
            "release_impact": "BLOCKS_RELEASE",
            "why_it_matters": "Ignoring constraints makes task success unreliable."
          }
        ],
        "remediation_playbook": {
          "owner_personas": ["PRODUCT"],
          "policy_ids": ["baseline.constraint_following"],
          "strongest_risk_appetite": "LOW",
          "steps": [
            "Route TASK_SUCCESS remediation to: PRODUCT.",
            "Fix or measure the blocking criteria: constraint_ignorance, hallucination.",
            "Review mapped policy intent: Stays within the operator's stated scope.",
            "Rerun the same gate and compare the new artifact against this one."
          ],
          "acceptance_checks": [
            "constraint_ignorance: reach at least 8/10 passing cases (currently 1/10).",
            "hallucination: reach at least 8/10 passing cases (currently 3/10)."
          ]
        },
        "next_action": "Fix constraint_ignorance, hallucination, rerun the same gate, and compare the new evidence against this suite."
      }
    ],
    "next_actions": [
      "Do not release; fix the top failed business risks and rerun the same gate."
    ],
    "notes": [
      "This block is an explanation layer over the existing release gate; it does not change verdict math or scoring thresholds."
    ]
  },
  "criteria": [
    {
      "code": "constraint_ignorance",
      "tier": "critical",
      "status": "FAILED",
      "risk_domains": ["TASK_SUCCESS", "OPERATIONAL_RISK"],
      "policy_ids": ["baseline.constraint_following", "baseline.constraint_operational_risk"],
      "release_impact": "BLOCKS_RELEASE",
      "evidence": [
        {
          "case_id": "...",
          "prompt": "...",
          "passed": false,
          "agent_response_excerpt": "...",      // bounded excerpt; not a full transcript
          "reasoning": "...",
          "error": null,
          "raw_metadata": { "judge_score": 0 }
        }
      ]
    }
  ],
  "evidence_url": "https://app.agentscore.tech/v2/suites/<suite_id>"
}
```

Optional integration outputs:

```bash
agentscore release-gate \
  --suite 648e65cd-f206-4668-812c-f99bb49dd262 \
  --output agentscore-release-decision.json \
  --event-output agentscore-release-decision.event.json \
  --sarif-output agentscore-release-decision.sarif
```

`--event-output` writes a CloudEvents-compatible envelope:

```json
{
  "specversion": "1.0",
  "type": "tech.agentscore.release_gate.decision.v1",
  "source": "https://agentscore.tech/release-gate",
  "subject": "suite/648e65cd-f206-4668-812c-f99bb49dd262",
  "datacontenttype": "application/json",
  "data": {
    "gate": "baseline-agent-v1",
    "release_decision": { "verdict": "BLOCKED", "confidence": "MEDIUM" },
    "risk_posture": "CRITICAL_BLOCKERS",
    "top_risks": []
  }
}
```

`--sarif-output` writes SARIF `2.1.0`: one rule per criterion and one
result for each failed / warning / unmeasured criterion. It is suitable
for artifact upload today and can be connected to code-scanning style
workflows later without changing the core release-gate artifact.

The shape matches the frontend `EvidenceExport` (TSK_117 / TSK_120) so a
JSON artifact downloaded from the dashboard is interchangeable with one
produced by the CLI. `decision_intelligence` is additive: it ranks
business risks and next actions from the same criterion evidence,
attaches policy-owned remediation playbooks, but does **not** change
verdict math, thresholds, or exit codes.

The CLI fetches `/v2/evaluations/policies/registry` for policy titles,
owner personas, appetite, and acceptance checks. If the policy registry
is temporarily unavailable, the CLI prints one warning, still writes the
artifact, and leaves `policies` / `remediation_playbook` empty rather
than changing the release decision.
`agent_response_excerpt` is a bounded excerpt —
**not** a full transcript.

## Endpoints used

```
GET /v2/evaluations/gates/registry              (validate --gate)
GET /v2/evaluations/policies/registry           (policy-backed remediation playbooks; soft-fails)
GET /v2/evaluations/criteria/registry            (policy_ids / risk_domains / release_impact)
GET /v2/evaluations/suites/{id}/dashboard        (release decision input)
GET /v2/evaluations/suites/{id}/evidence         (per-case evidence; soft-fails to aggregate)
```

All endpoints are BOLA-scoped per the backend contract — the CLI's
release-gate command is read-only.

## Development

```bash
cd cli
pip install -e '.[dev]'
pytest -q
```

The test suite uses `httpx.MockTransport` so no live HTTP is needed.

## Scope

- No new scoring constants or calibration math.
- No judge prompt or judge model changes.
- No fake or seeded data — the JSON artifact mirrors the backend exactly.
- No new authentication system; tokens come from Clerk via env.
- `agent_response_excerpt` stays a bounded excerpt; the CLI never claims
  to export a full transcript.

## What's next

- TSK_124 wraps this CLI in a GitHub Action that posts a PR comment.
- A future task can split this package into a standalone `agentscore-cli`
  GitHub repo + PyPI release without changing the wire contract.
