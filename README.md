# AgentScore release gate — GitHub Action and CLI

Block a pull request when your AI agent would not pass an independent release
gate. [AgentScore](https://agentscore.tech) runs your live bot through the
checks for its kind — instruction following, made-up facts, prompt injection,
personal-data and secret leakage, and the industry exam for its category —
and returns a decision: **Blocked**, **Needs fixes**, **Review required** or
**Release candidate**, with the evidence behind it.

```yaml
- uses: nathnenne/agentscore-release-gate/action@v1
  with:
    agent-id: ${{ vars.AGENTSCORE_AGENT_ID }}
  env:
    AGENTSCORE_TOKEN: ${{ secrets.AGENTSCORE_TOKEN }}   # an API key from Settings → API keys
```

- [`action/`](action/README.md) — the composite action: runs the gate, uploads
  the JSON decision and a SARIF file, and posts a sticky PR comment.
- [`cli/`](cli/README.md) — the `agentscore` command the action wraps; use it
  from any CI: `pip install "git+https://github.com/nathnenne/agentscore-release-gate#subdirectory=cli"`.

The commit SHA is used as the run key, so a re-run job does not start (or pay
for) a second gate. Results can be issued as signed attestations that anyone
can verify at [agentscore.tech/verify](https://agentscore.tech/verify).

A release gate is test evidence for the scope it ran — not a certification
and not a guarantee of safety.
