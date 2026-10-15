"""`agentscore.yml` config loader (TSK_123).

Tiny, defensive loader: every field is optional, every type is checked,
and a malformed config raises a clear error rather than booting with
half-initialised defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .decision import DEFAULT_FAIL_ON, FailSignal


_KNOWN_FAIL_SIGNALS: frozenset[str] = frozenset(
    {"BLOCKED", "NEEDS_FIXES", "REVIEW_REQUIRED", "LOW_CONFIDENCE_CRITICAL"}
)


@dataclass(frozen=True)
class Config:
    """Resolved CLI configuration. Values are merged from
    (in priority order): explicit CLI flags > env vars > config file >
    built-in defaults.
    """

    api_url: str | None = None
    suite_id: str | None = None
    gate: str = "baseline-agent-v1"
    fail_on: tuple[FailSignal, ...] = DEFAULT_FAIL_ON
    output_json: str = "agentscore-release-decision.json"
    output_event: str | None = None
    output_sarif: str | None = None


class ConfigError(ValueError):
    """Raised when ``agentscore.yml`` is structurally invalid."""


def load_config_file(path: str | Path) -> Config:
    """Load ``agentscore.yml`` from disk. Missing files yield the
    default :class:`Config` (so a flag-only invocation works).
    """

    p = Path(path)
    if not p.exists():
        return Config()
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{p}: invalid YAML — {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{p}: top-level YAML must be a mapping, got {type(raw).__name__}"
        )

    api_url = raw.get("api_url")
    if api_url is not None and not isinstance(api_url, str):
        raise ConfigError(f"{p}: `api_url` must be a string")

    suite_id = raw.get("suite_id")
    if suite_id is not None and not isinstance(suite_id, str):
        raise ConfigError(f"{p}: `suite_id` must be a string")

    gate = raw.get("gate", "baseline-agent-v1")
    if not isinstance(gate, str):
        raise ConfigError(f"{p}: `gate` must be a string")

    fail_on_raw = raw.get("fail_on", list(DEFAULT_FAIL_ON))
    if not isinstance(fail_on_raw, list) or not all(
        isinstance(s, str) for s in fail_on_raw
    ):
        raise ConfigError(
            f"{p}: `fail_on` must be a list of strings; "
            f"allowed values: {sorted(_KNOWN_FAIL_SIGNALS)}"
        )
    unknown = [s for s in fail_on_raw if s not in _KNOWN_FAIL_SIGNALS]
    if unknown:
        raise ConfigError(
            f"{p}: unknown fail_on signal(s) {unknown!r}; "
            f"allowed values: {sorted(_KNOWN_FAIL_SIGNALS)}"
        )

    output_block = raw.get("output", {})
    if not isinstance(output_block, dict):
        raise ConfigError(f"{p}: `output` must be a mapping")
    output_json = output_block.get("json", "agentscore-release-decision.json")
    if not isinstance(output_json, str):
        raise ConfigError(f"{p}: `output.json` must be a string")
    output_event = output_block.get("event")
    if output_event is not None and not isinstance(output_event, str):
        raise ConfigError(f"{p}: `output.event` must be a string")
    output_sarif = output_block.get("sarif")
    if output_sarif is not None and not isinstance(output_sarif, str):
        raise ConfigError(f"{p}: `output.sarif` must be a string")

    return Config(
        api_url=api_url,
        suite_id=suite_id,
        gate=gate,
        fail_on=tuple(fail_on_raw),  # type: ignore[arg-type]
        output_json=output_json,
        output_event=output_event,
        output_sarif=output_sarif,
    )


def parse_fail_on_flag(value: str) -> tuple[FailSignal, ...]:
    """Parse a `--fail-on BLOCKED,NEEDS_FIXES` flag value. Raises on
    unknown signals."""

    parts = [p.strip() for p in value.split(",") if p.strip()]
    unknown = [p for p in parts if p not in _KNOWN_FAIL_SIGNALS]
    if unknown:
        raise ConfigError(
            f"unknown --fail-on signal(s) {unknown!r}; "
            f"allowed values: {sorted(_KNOWN_FAIL_SIGNALS)}"
        )
    return tuple(parts)  # type: ignore[return-value]


def merge(
    file_cfg: Config,
    *,
    cli_api_url: str | None = None,
    cli_suite: str | None = None,
    cli_gate: str | None = None,
    cli_fail_on: tuple[FailSignal, ...] | None = None,
    cli_output: str | None = None,
    cli_event_output: str | None = None,
    cli_sarif_output: str | None = None,
    env_api_url: str | None = None,
) -> Config:
    """Merge file + env + CLI flags. Precedence: CLI > env > file > default."""

    return Config(
        api_url=cli_api_url or env_api_url or file_cfg.api_url,
        suite_id=cli_suite or file_cfg.suite_id,
        gate=cli_gate or file_cfg.gate,
        fail_on=cli_fail_on if cli_fail_on is not None else file_cfg.fail_on,
        output_json=cli_output or file_cfg.output_json,
        output_event=cli_event_output or file_cfg.output_event,
        output_sarif=cli_sarif_output or file_cfg.output_sarif,
    )
