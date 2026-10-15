"""TSK_123 — `agentscore.yml` config parser tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agentscore_cli.config import (
    Config,
    ConfigError,
    load_config_file,
    merge,
    parse_fail_on_flag,
)


def test_missing_file_yields_default_config(tmp_path: Path):
    cfg = load_config_file(tmp_path / "missing.yml")
    assert cfg == Config()


def test_full_config(tmp_path: Path):
    p = tmp_path / "agentscore.yml"
    p.write_text(
        textwrap.dedent(
            """\
            api_url: https://api.agentscore.tech
            suite_id: 648e65cd-f206-4668-812c-f99bb49dd262
            gate: support-v1
            fail_on:
              - BLOCKED
              - NEEDS_FIXES
              - LOW_CONFIDENCE_CRITICAL
            output:
              json: out/release.json
              event: out/release.event.json
              sarif: out/release.sarif
            """
        ),
        encoding="utf-8",
    )
    cfg = load_config_file(p)
    assert cfg.api_url == "https://api.agentscore.tech"
    assert cfg.suite_id == "648e65cd-f206-4668-812c-f99bb49dd262"
    assert cfg.gate == "support-v1"
    assert cfg.fail_on == ("BLOCKED", "NEEDS_FIXES", "LOW_CONFIDENCE_CRITICAL")
    assert cfg.output_json == "out/release.json"
    assert cfg.output_event == "out/release.event.json"
    assert cfg.output_sarif == "out/release.sarif"


def test_unknown_fail_signal_raises(tmp_path: Path):
    p = tmp_path / "agentscore.yml"
    p.write_text(
        "fail_on: [BLOCKED, INVENTED_SIGNAL]\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="unknown fail_on signal"):
        load_config_file(p)


def test_non_mapping_yaml_raises(tmp_path: Path):
    p = tmp_path / "agentscore.yml"
    p.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="top-level YAML must be a mapping"):
        load_config_file(p)


def test_parse_fail_on_flag_happy_path():
    assert parse_fail_on_flag("BLOCKED,NEEDS_FIXES") == (
        "BLOCKED",
        "NEEDS_FIXES",
    )


def test_parse_fail_on_flag_rejects_unknown():
    with pytest.raises(ConfigError, match="unknown --fail-on signal"):
        parse_fail_on_flag("BLOCKED,WHAT_IS_THIS")


def test_merge_precedence_cli_beats_env_beats_file():
    file_cfg = Config(api_url="https://file.example", gate="baseline-agent-v1")
    merged = merge(
        file_cfg,
        cli_api_url="https://cli.example",
        env_api_url="https://env.example",
    )
    assert merged.api_url == "https://cli.example"

    merged = merge(file_cfg, env_api_url="https://env.example")
    assert merged.api_url == "https://env.example"

    merged = merge(file_cfg)
    assert merged.api_url == "https://file.example"


def test_merge_cli_gate_overrides_file():
    file_cfg = Config(gate="baseline-agent-v1")
    merged = merge(file_cfg, cli_gate="support-v1")
    assert merged.gate == "support-v1"


def test_merge_cli_integration_outputs_override_file():
    file_cfg = Config(
        output_event="file.event.json",
        output_sarif="file.sarif",
    )
    merged = merge(
        file_cfg,
        cli_event_output="cli.event.json",
        cli_sarif_output="cli.sarif",
    )
    assert merged.output_event == "cli.event.json"
    assert merged.output_sarif == "cli.sarif"
