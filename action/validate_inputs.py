#!/usr/bin/env python3
"""TSK_157 — strict validator for inputs flowing into action/action.yml.

Why this exists
---------------
RES_154 P0 #3: the composite GitHub Action previously inlined
`${{ inputs.* }}` directly into ``run: |`` bash and ``python -c``
command bodies. A downstream workflow that piped PR-author-controlled
metadata (e.g. ``${{ github.event.pull_request.title }}``) into an
input could break out of shell/Python quoting and execute arbitrary
commands on the caller's runner — exfiltrating ``AGENTSCORE_TOKEN``,
``GITHUB_TOKEN``, or other workflow secrets.

This module is the *first* runtime gate the action calls. It is
deliberately:

* offline — no network, no DB, no file IO beyond stdout/stderr;
* dependency-free — stdlib only, so the action can run before
  ``pip install`` has placed the CLI on PATH;
* explicit — every accepted shape is a literal regex / allow-list, so a
  future contributor can audit the contract at a glance;
* fail-closed — anything not matching the allow-list rejects, never
  "best-effort quotes".

The contract here is mirrored in ``action/tests/test_validate_inputs.py``.
Both files must move in lockstep.

CLI contract
------------
Read inputs from these env vars (set by the action via step-level
``env:``), validate, and exit non-zero on the first failure:

* ``INPUT_SUITE_ID``                — required, UUID string
* ``INPUT_GATE``                    — required (default 'baseline-agent-v1')
* ``INPUT_FAIL_ON``                 — required (default fail-on list)
* ``INPUT_API_URL``                 — required, ``https://...``
* ``INPUT_PYTHON_VERSION``          — required
* ``INPUT_ARTIFACT_NAME``           — required, safe file stem
* ``INPUT_INTEGRATION_ARTIFACT_NAME`` — required, safe file stem
* ``INPUT_COMMENT_ON_PR``           — required, exactly ``true`` / ``false``
* ``INPUT_FAIL_WORKFLOW_ON_GATE``   — required, exactly ``true`` / ``false``
* ``INPUT_ALLOW_HTTP_LOCAL``        — optional, ``"true"`` opts into local
                                       http://127.0.0.1 / http://localhost
                                       targets for examples ONLY.

On failure: prints exactly one ``::error::`` line naming the invalid
input AND a generic reason, with NO echo of the offending value. Exits 2.
On success: prints nothing. Exits 0.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable
from urllib.parse import urlparse
from uuid import UUID

# Hard-coded fail-signal allow-list — must stay in sync with the gate
# implementation in app/criteria/gates.py. Adding a new fail-signal is a
# deliberate change: appending to this set AND to the gate template
# registry, in the same PR.
ALLOWED_FAIL_SIGNALS: frozenset[str] = frozenset(
    {
        "BLOCKED",
        "NEEDS_FIXES",
        "REVIEW_REQUIRED",
        "LOW_CONFIDENCE_CRITICAL",
    }
)

# Conservative slug shapes. The point is to reject anything a shell would
# treat as syntax (``;`` ``|`` ``&`` ``$`` `` ` `` ``\n`` ``"``  ``'``
# ``(`` ``)``  ``<`` ``>``) AND anything a filesystem could interpret as a
# path (``/`` ``\`` ``..``).
# `\Z` anchors the regex to the *true* end of string — `$` would let a
# trailing `\n` slip through (e.g. ``"true\n"`` would match ``^(?:true|false)$``
# because Python's `$` matches before a final newline by default). The
# malicious-input matrix relies on these regexes rejecting trailing
# whitespace.
GATE_SLUG_RE = re.compile(r"\A[A-Za-z0-9_.:\-]{1,80}\Z")
ARTIFACT_NAME_RE = re.compile(r"\A[A-Za-z0-9_.\-]{1,80}\Z")
PYTHON_VERSION_RE = re.compile(r"\A[0-9]+(?:\.[0-9]+){0,2}\Z")

# Single-word boolean — neither ``True`` nor ``yes`` nor whitespace nor
# trailing newline is acceptable. Tracked exactly because the YAML inputs
# default to ``'true'`` / ``'false'`` strings.
BOOL_RE = re.compile(r"\A(?:true|false)\Z")


class ValidationError(Exception):
    """Raised when an input fails its allow-list.

    The exception ``args`` carry the input *name* and a generic
    *reason* only — never the offending value. The reason is safe to
    surface in workflow logs.
    """


def _emit_error(name: str, reason: str) -> None:
    """Write a single bounded ``::error::`` line to stderr.

    GitHub's runner picks ``::error::`` lines off stderr and surfaces
    them in the workflow UI. We deliberately do not echo the offending
    value — a malicious input could include workflow-control sequences
    (``%0A``, ``::set-output``, …) that the runner would honour. The
    reason text is constant per case.
    """

    print(f"::error::Invalid action input '{name}': {reason}", file=sys.stderr)


def _require(name: str, value: str | None) -> str:
    if value is None:
        raise ValidationError(name, "missing value (action input not set)")
    return value


def validate_suite_id(value: str) -> str:
    """UUID per RFC 4122, in any case. Returns the canonical lower form."""

    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError(
            "suite-id", "expected a UUID (e.g. 11111111-2222-3333-4444-555555555555)"
        ) from exc


RUN_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def validate_run_target(env: dict[str, str]) -> None:
    """TSK_1065 — exactly one of suite-id (read a finished run) or agent-id
    (start a run and wait). run-key is optional and slug-shaped."""

    suite = (env.get("INPUT_SUITE_ID") or "").strip()
    agent = (env.get("INPUT_AGENT_ID") or "").strip()
    if bool(suite) == bool(agent):
        raise ValidationError("suite-id/agent-id", "set exactly one of suite-id or agent-id")
    if suite:
        validate_suite_id(suite)
    else:
        try:
            UUID(agent)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError("agent-id", "expected a UUID") from exc
    run_key = (env.get("INPUT_RUN_KEY") or "").strip()
    if run_key and not RUN_KEY_RE.match(run_key):
        raise ValidationError("run-key", "expected 1-128 chars from [A-Za-z0-9._:-]")


def validate_gate(value: str) -> str:
    if not GATE_SLUG_RE.match(value):
        raise ValidationError(
            "gate",
            "expected 1–80 chars from [A-Za-z0-9_.:-]; got a value with "
            "disallowed characters",
        )
    return value


def validate_fail_on(value: str) -> str:
    """Comma-separated allow-list. Empty list is rejected."""

    parts = [tok.strip() for tok in value.split(",")]
    if not parts or not all(parts):
        raise ValidationError(
            "fail-on",
            "expected comma-separated list of fail signals (no empty entries)",
        )
    bad = [tok for tok in parts if tok not in ALLOWED_FAIL_SIGNALS]
    if bad:
        # Don't echo the offending values — they could contain workflow
        # control sequences. The allow-list is constant and safe.
        raise ValidationError(
            "fail-on",
            "every value must be one of "
            "{BLOCKED, NEEDS_FIXES, REVIEW_REQUIRED, LOW_CONFIDENCE_CRITICAL}",
        )
    # Re-emit the canonical comma-joined form so downstream callers see
    # a normalised string (no whitespace).
    return ",".join(parts)


def validate_api_url(value: str, *, allow_http_local: bool = False) -> str:
    """Require ``https://...`` by default.

    The opt-in ``allow_http_local`` flag permits *only*
    ``http://localhost`` / ``http://127.0.0.1`` / ``http://[::1]``
    targets, which the published examples need for local smoke tests.
    It is NOT enabled by default — the action ships with
    ``INPUT_ALLOW_HTTP_LOCAL=`` empty.
    """

    try:
        parsed = urlparse(value)
    except ValueError as exc:
        raise ValidationError("api-url", "expected an https URL") from exc

    if not parsed.scheme or not parsed.netloc:
        raise ValidationError("api-url", "expected an https URL with a host")

    # Reject anything a shell could misinterpret if accidentally
    # word-split later (we always quote, but defence in depth).
    forbidden = set(' \t\n\r"\'`$();|&<>')
    if any(c in forbidden for c in value):
        raise ValidationError(
            "api-url", "URL contains characters that are not allowed (shell-unsafe)"
        )

    if parsed.scheme == "https":
        return value

    if parsed.scheme == "http" and allow_http_local:
        host = parsed.hostname or ""
        if host in {"localhost", "127.0.0.1", "::1"}:
            return value
        raise ValidationError(
            "api-url",
            "http:// is only allowed for localhost/127.0.0.1/::1 when "
            "allow-http-local is true",
        )

    raise ValidationError(
        "api-url",
        "scheme must be https:// (or http:// to localhost when "
        "allow-http-local is true)",
    )


def validate_python_version(value: str) -> str:
    if not PYTHON_VERSION_RE.match(value):
        raise ValidationError(
            "python-version",
            "expected a version like '3.12' or '3.12.4' (digits and dots only)",
        )
    return value


def validate_artifact_name(value: str, *, field: str = "artifact-name") -> str:
    """Safe file stem.

    Rejects shell metacharacters (``;`` `` ` `` ``$`` newline …) AND path
    separators (``/`` ``\\``) AND directory traversal ('..'). Empty
    string is rejected; a 1-char artifact name is allowed but unusual.
    """

    if not ARTIFACT_NAME_RE.match(value):
        raise ValidationError(
            field,
            "expected 1–80 chars from [A-Za-z0-9_.-]; reject /, \\, whitespace, "
            "quotes, $, backticks, semicolons, newlines",
        )
    if ".." in value:
        raise ValidationError(field, "must not contain '..' (path traversal)")
    return value


def validate_bool(value: str, *, field: str) -> str:
    if not BOOL_RE.match(value):
        raise ValidationError(
            field, "expected the exact string 'true' or 'false'"
        )
    return value


def _read(env: dict[str, str], name: str) -> str:
    return _require(name, env.get(name))


# Mapping from input env var -> (display name, validator). The validators
# are stored as callables that take only ``value`` so the dispatch loop in
# ``main`` stays a flat for-loop without special-cases.
_BASIC_INPUTS: list[tuple[str, str, Callable[[str], str]]] = [
    ("INPUT_GATE", "gate", validate_gate),
    ("INPUT_FAIL_ON", "fail-on", validate_fail_on),
    ("INPUT_PYTHON_VERSION", "python-version", validate_python_version),
    (
        "INPUT_ARTIFACT_NAME",
        "artifact-name",
        lambda v: validate_artifact_name(v, field="artifact-name"),
    ),
    (
        "INPUT_INTEGRATION_ARTIFACT_NAME",
        "integration-artifact-name",
        lambda v: validate_artifact_name(v, field="integration-artifact-name"),
    ),
    (
        "INPUT_COMMENT_ON_PR",
        "comment-on-pr",
        lambda v: validate_bool(v, field="comment-on-pr"),
    ),
    (
        "INPUT_FAIL_WORKFLOW_ON_GATE",
        "fail-workflow-on-gate",
        lambda v: validate_bool(v, field="fail-workflow-on-gate"),
    ),
]


def validate_all(env: dict[str, str]) -> None:
    """Run every validator against ``env``. Raises ``ValidationError`` on
    the first failure so the action's first step exits before any other
    work runs.
    """

    validate_run_target(env)
    for env_key, _field, validator in _BASIC_INPUTS:
        validator(_read(env, env_key))

    # api-url has an opt-in test flag, so it gets its own line.
    allow_http_local = env.get("INPUT_ALLOW_HTTP_LOCAL", "").strip().lower() == "true"
    validate_api_url(_read(env, "INPUT_API_URL"), allow_http_local=allow_http_local)


def main(argv: list[str] | None = None) -> int:
    """Entrypoint used by the action's first step."""

    _ = argv  # No flags today; argv is reserved for future opt-in toggles.
    try:
        validate_all(dict(os.environ))
    except ValidationError as exc:
        name, reason = exc.args
        _emit_error(name, reason)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
