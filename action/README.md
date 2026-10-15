# AgentScore release-gate GitHub Action

Block risky AI-agent PRs with evidence-backed release decisions. This is
a thin composite action wrapping the [agentscore CLI](../cli/README.md)
(TSK_123). It runs the CLI, uploads the JSON artifact, and posts a
sticky PR comment summarising the verdict.

> Score is not opinion. Score is weighted evidence.

## Copy-paste usage

```yaml
name: AgentScore release gate

on:
  pull_request:
    branches: [main]

permissions:
  contents: read
  pull-requests: write   # required to post the PR comment via ${{ github.token }}

jobs:
  release-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: nathnenne/agentscore-release-gate/action@v1
        with:
          # Start a full gate for the bot, wait, gate the PR on the verdict.
          # The commit SHA is the run key, so a re-run job does not pay twice.
          agent-id: ${{ vars.AGENTSCORE_AGENT_ID }}
          gate: baseline-agent-v1
          fail-on: BLOCKED,NEEDS_FIXES,LOW_CONFIDENCE_CRITICAL
        env:
          # An API key (ags_key_…) from Settings → API keys. A Clerk session
          # token expires within minutes and is not usable as a CI secret.
          AGENTSCORE_TOKEN: ${{ secrets.AGENTSCORE_TOKEN }}
```

Pin to a release tag (`@v1`) or, stricter, to a commit SHA in production.

## Inputs

| Name | Required | Default | What it does |
| --- | --- | --- | --- |
| `agent-id` | one of | — | Bot UUID: start a full gate run, wait for it, evaluate it. |
| `suite-id` | one of | — | v2 suite UUID of a finished run to evaluate instead. |
| `run-key` | no | commit SHA | Idempotency key for `agent-id` runs. |
| `gate` | no | `baseline-agent-v1` | Gate template id; must exist in `/v2/evaluations/gates/registry`. |
| `fail-on` | no | `BLOCKED,NEEDS_FIXES,LOW_CONFIDENCE_CRITICAL` | Comma-separated fail signals. |
| `api-url` | no | `https://api.agentscore.tech` | Backend API base URL. |
| `python-version` | no | `3.12` | Python version used to install + run the CLI. |
| `artifact-name` | no | `agentscore-release-decision` | Name for the uploaded JSON artifact. |
| `integration-artifact-name` | no | `agentscore-release-integrations` | Uploaded bundle containing CloudEvents JSON + SARIF. |
| `comment-on-pr` | no | `true` | Post/update a sticky PR comment on `pull_request` events. |
| `fail-workflow-on-gate` | no | `true` | Propagate the CLI's non-zero exit to the workflow. |

## Outputs

| Name | Description |
| --- | --- |
| `verdict` | `BLOCKED` / `NEEDS_FIXES` / `REVIEW_REQUIRED` / `RELEASE_CANDIDATE`. |
| `confidence` | `LOW` / `MEDIUM` / `HIGH`. |
| `exit-code` | CLI exit code (`0` / `1` / `2`). |
| `artifact-path` | Path to the JSON artifact written on disk. |
| `event-path` | Path to the CloudEvents-compatible event JSON. |
| `sarif-path` | Path to the SARIF 2.1.0 file. |

## Integration artifacts

The action uploads two artifact groups:

| Artifact | Contents |
| --- | --- |
| `agentscore-release-decision` | The canonical AgentScore JSON artifact. |
| `agentscore-release-integrations` | `*.event.json` CloudEvents-compatible envelope + `*.sarif` SARIF 2.1.0 projection. |

It also writes a GitHub Step Summary using the same token-free artifact
as the PR comment. The summary is available even when `comment-on-pr:
false` or when the workflow is not running on a pull request.

## What the PR comment looks like

```
AgentScore release gate: BLOCKED (MEDIUM confidence)

Gate: baseline-agent-v1

Do not release this agent yet.

Agent: TSK_112 Smoke Echo Agent (httpbin) · Suite: 648e65cd

Top blockers:
1. SECURITY, DATA_PRIVACY, COMPLIANCE — prompt_injection failed 4/10 vs gate 8/10
2. BRAND_REPUTATION, TASK_SUCCESS, COMPLIANCE — hallucination failed 3/10 vs gate 8/10
3. TASK_SUCCESS, OPERATIONAL_RISK — constraint_ignorance failed 1/10 vs gate 8/10

Decision intelligence:
1. TASK_SUCCESS: FAILED · priority 420 · constraint_ignorance, hallucination
   Owners: PRODUCT · appetite: LOW
   Check: constraint_ignorance: reach at least 8/10 passing cases (currently 1/10).
2. COMPLIANCE: FAILED · priority 405 · hallucination, prompt_injection

Next actions:
- Do not release; fix the top failed business risks and rerun the same gate.
- Fix constraint_ignorance, hallucination, rerun the same gate, and compare the new evidence against this suite.

Evidence quality: COMPLETE (3/3 criteria measured).

Evidence: 8 / 30 tests passed.
Diagnostic score: 28.7/100.

Evidence report: https://app.agentscore.tech/v2/suites/648e65cd-…

Methodology: AgentScore release gate v1.
```

The comment never uses *"certified"*, *"guaranteed safe"*,
*"production-ready"*, or *"EU AI Act PASS"* wording — asserted by test.

## Stickiness

The action embeds a hidden marker
(`<!-- agentscore-release-gate-comment-marker -->`) at the top of the
comment body. On re-run, the action finds the existing AgentScore comment
by marker and edits it; new PRs get a fresh one.

## Secret-handling note

- `AGENTSCORE_TOKEN` flows in as `env:` on the calling step. The action
  passes it through to the CLI's environment and **never** echoes it.
- The CLI scrubs known secret-shaped substrings from any HTTP error.
- The action's `actions/upload-artifact@v4` step uploads the JSON
  artifact which the CLI guarantees is token-free (TSK_123).
- The PR-comment writer uses `${{ github.token }}` (the workflow's
  built-in token) — no extra setup, no third-party app install.

## Exit codes

The action's "Propagate gate exit code" step exits with the CLI's exit
code (0/1/2) when `fail-workflow-on-gate: true` (default). Soft
rollouts can set `fail-workflow-on-gate: false` to keep the workflow
green while still uploading the artifact and posting the comment.

## Local development

```bash
# Render the PR comment markdown locally from a JSON artifact:
python action/render_pr_comment.py \
  --artifact agentscore-release-decision.json \
  --gate baseline-agent-v1

# Run the renderer's unit tests:
cd action && python -m pytest tests -q
```

The action.yml itself is exercised end-to-end via `act` or a sandbox
GitHub repo; see `RES_124` for the verification approach.
