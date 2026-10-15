"""`agentscore` CLI entrypoint (TSK_123).

Sub-commands:

  release-gate    Fetch a v2 suite's release decision and write a JSON
                  artifact. Exits 0 for RELEASE_CANDIDATE, 1 when the
                  configured gate fails, 2 on usage / network errors.

Token handling:

  AGENTSCORE_TOKEN          required env var: an API key (ags_key_…, created
                            in Settings → API keys). A Clerk session JWT also
                            works but expires within minutes — not for CI.
  --token                   optional flag; never logged.
  No flag value is ever echoed back to the terminal.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import replace
from typing import Sequence, TextIO

from . import release_gate
from .config import ConfigError, load_config_file, merge, parse_fail_on_flag


_TOKEN_ENV = "AGENTSCORE_TOKEN"
_API_URL_ENV = "AGENTSCORE_API_URL"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentscore",
        description=(
            "AgentScore release-gate CLI. Reads a v2 suite, returns a "
            "verdict, writes a JSON artifact, and exits 0/1 for CI."
        ),
    )
    parser.add_argument(
        "--version", action="store_true", help="print CLI version and exit"
    )
    sub = parser.add_subparsers(dest="command", required=False)

    rg = sub.add_parser(
        "release-gate",
        help="Fetch a suite's release decision and write a JSON artifact.",
    )
    rg.add_argument(
        "--suite",
        dest="suite",
        help="suite UUID (overrides agentscore.yml `suite_id`)",
    )
    # TSK_1065 — run the gate from CI instead of only reading a finished one.
    rg.add_argument(
        "--agent",
        dest="agent",
        help=(
            "bot UUID: start a full gate run for it, wait for the result, "
            "then evaluate that suite (instead of --suite)"
        ),
    )
    rg.add_argument(
        "--run-key",
        dest="run_key",
        help=(
            "idempotency key for --agent (e.g. the commit SHA) so a retried "
            "job reuses its run instead of paying twice"
        ),
    )
    rg.add_argument(
        "--wait-timeout",
        dest="wait_timeout",
        type=int,
        default=1800,
        help="seconds to wait for an --agent run to finish (default 1800)",
    )
    rg.add_argument(
        "--api-url",
        dest="api_url",
        help=(
            "backend API base URL (overrides agentscore.yml `api_url` "
            f"and ${_API_URL_ENV})"
        ),
    )
    rg.add_argument(
        "--gate",
        dest="gate",
        help="gate template id (default: baseline-agent-v1)",
    )
    rg.add_argument(
        "--config",
        dest="config",
        default="agentscore.yml",
        help="path to agentscore.yml (default: ./agentscore.yml)",
    )
    rg.add_argument(
        "--fail-on",
        dest="fail_on",
        help=(
            "comma-separated fail signals "
            "(BLOCKED, NEEDS_FIXES, REVIEW_REQUIRED, LOW_CONFIDENCE_CRITICAL)"
        ),
    )
    rg.add_argument(
        "--output",
        dest="output",
        help=(
            "JSON artifact path (default: agentscore-release-decision.json)"
        ),
    )
    rg.add_argument(
        "--event-output",
        dest="event_output",
        help=(
            "optional CloudEvents-compatible event JSON path "
            "(also configurable as output.event in agentscore.yml)"
        ),
    )
    rg.add_argument(
        "--sarif-output",
        dest="sarif_output",
        help=(
            "optional SARIF 2.1.0 output path "
            "(also configurable as output.sarif in agentscore.yml)"
        ),
    )
    rg.add_argument(
        "--token",
        dest="token",
        help=(
            f"Clerk JWT (overrides ${_TOKEN_ENV}); never logged or "
            "written to the artifact"
        ),
    )
    rg.add_argument(
        "--no-evidence",
        dest="no_evidence",
        action="store_true",
        help=(
            "skip the /evidence endpoint; emit an aggregate-only artifact"
        ),
    )

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.version:
        from . import __version__

        stdout.write(f"agentscore-cli {__version__}\n")
        return 0

    if args.command != "release-gate":
        parser.print_help(file=stderr)
        return 2

    try:
        file_cfg = load_config_file(args.config)
    except ConfigError as exc:
        stderr.write(f"error: {exc}\n")
        return 2

    cli_fail_on = None
    if args.fail_on:
        try:
            cli_fail_on = parse_fail_on_flag(args.fail_on)
        except ConfigError as exc:
            stderr.write(f"error: {exc}\n")
            return 2

    config = merge(
        file_cfg,
        cli_api_url=args.api_url,
        cli_suite=args.suite,
        cli_gate=args.gate,
        cli_fail_on=cli_fail_on,
        cli_output=args.output,
        cli_event_output=args.event_output,
        cli_sarif_output=args.sarif_output,
        env_api_url=os.environ.get(_API_URL_ENV),
    )

    token = args.token or os.environ.get(_TOKEN_ENV)
    if not token:
        stderr.write(
            f"error: no token. Set ${_TOKEN_ENV} or pass --token. "
            "Never paste your token into a log line.\n"
        )
        return 2
    # Defensive: scrub the args namespace so a future logging call cannot
    # leak the token by accident.
    args.token = None

    if args.agent and not args.suite:
        suite_id = _run_and_wait(
            config=config,
            token=token,
            agent_id=args.agent,
            run_key=args.run_key,
            timeout_s=args.wait_timeout,
            stderr=stderr,
        )
        if suite_id is None:
            return 2
        config = replace(config, suite_id=suite_id)

    return release_gate.run(
        config=config,
        token=token,
        stdout=stdout,
        stderr=stderr,
        fetch_evidence=not args.no_evidence,
    )


#: Statuses after which a run will not change any more.
_TERMINAL = {"COMPLETED", "FAILED"}


def _run_and_wait(
    *,
    config,
    token: str,
    agent_id: str,
    run_key: str | None,
    timeout_s: int,
    stderr: TextIO,
    poll_s: float = 15.0,
    sleep=time.sleep,
) -> str | None:
    """Start a full gate for `agent_id`, wait for it, return its suite id.

    None (exit 2) when the run could not start, failed to measure, or did not
    finish in time — never a verdict invented from an incomplete run.
    """

    from .api import DEFAULT_API_URL, AgentScoreApiError, AgentScoreClient

    key = run_key or f"ci-{uuid.uuid4()}"
    api_url = config.api_url or DEFAULT_API_URL
    try:
        with AgentScoreClient(api_url=api_url, token=token) as client:
            started = client.start_run(agent_id, idempotency_key=key)
            suite_id = started.get("suite_id")
            if not suite_id:
                stderr.write(f"error: the run did not start: {started.get('message') or started}\n")
                return None
            stderr.write(f"run started: suite {suite_id}\n")
            deadline = time.monotonic() + timeout_s
            while True:
                status = client.get_suite_dashboard(suite_id).get("status")
                if status in _TERMINAL:
                    break
                if time.monotonic() >= deadline:
                    stderr.write(f"error: suite {suite_id} still {status} after {timeout_s}s\n")
                    return None
                sleep(poll_s)
    except AgentScoreApiError as exc:
        stderr.write(f"error: {exc}\n")
        return None
    if status == "FAILED":
        stderr.write(
            f"error: suite {suite_id} failed to measure (not a verdict on the bot); "
            "the wallet hold was released\n"
        )
        return None
    return suite_id


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
