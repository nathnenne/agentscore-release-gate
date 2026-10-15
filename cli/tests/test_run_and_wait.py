"""TSK_1065 — `release-gate --agent` starts a run, waits, returns its suite."""

from __future__ import annotations

import io

from agentscore_cli import __main__ as cli
from agentscore_cli.config import Config


class _Client:
    def __init__(self, statuses, started=None):
        self.statuses = list(statuses)
        self.started = started or {"suite_id": "s-1"}
        self.keys = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def start_run(self, agent_id, *, idempotency_key):
        self.keys.append(idempotency_key)
        return self.started

    def get_suite_dashboard(self, suite_id):
        return {"status": self.statuses.pop(0)}


def _run(monkeypatch, client, **kw):
    import agentscore_cli.api as api

    monkeypatch.setattr(api, "AgentScoreClient", lambda **_k: client)
    err = io.StringIO()
    out = cli._run_and_wait(
        config=Config(), token="ags_key_x", agent_id="a-1", run_key=kw.get("run_key"),
        timeout_s=kw.get("timeout", 60), stderr=err, poll_s=0, sleep=lambda _s: None,
    )
    return out, err.getvalue()


def test_waits_until_completed(monkeypatch):
    client = _Client(["RUNNING", "RUNNING", "COMPLETED"])
    suite, _ = _run(monkeypatch, client, run_key="sha-abc")
    assert suite == "s-1"
    assert client.keys == ["sha-abc"]


def test_a_failed_measurement_is_not_a_verdict(monkeypatch):
    suite, err = _run(monkeypatch, _Client(["FAILED"]))
    assert suite is None and "failed to measure" in err


def test_a_run_that_did_not_start_says_why(monkeypatch):
    suite, err = _run(monkeypatch, _Client([], started={"message": "capacity"}))
    assert suite is None and "did not start" in err


def test_a_timeout_is_reported(monkeypatch):
    suite, err = _run(monkeypatch, _Client(["RUNNING"] * 100), timeout=0)
    assert suite is None and "still RUNNING" in err
