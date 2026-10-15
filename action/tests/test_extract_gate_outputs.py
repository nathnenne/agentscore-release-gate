"""TSK_157 — contract for action/extract_gate_outputs.py.

The helper replaces the deleted inline ``python -c '...'`` in
action.yml. These tests ensure it:

* writes ``verdict=...`` / ``confidence=...`` for a valid artifact;
* writes ``UNKNOWN`` / ``UNKNOWN`` for missing or malformed artifacts;
* never raises (so a workflow output stays predictable);
* never echoes secret-shaped strings to stdout/stderr.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ACTION_DIR = HERE.parent
if str(ACTION_DIR) not in sys.path:
    sys.path.insert(0, str(ACTION_DIR))

import extract_gate_outputs  # noqa: E402


VALID_ARTIFACT = {
    "release_decision": {
        "verdict": "BLOCKED",
        "confidence": "HIGH",
        # Extra payload that must NOT leak into outputs.
        "evidence": "<bounded snippet>",
    },
    "policy_id": "baseline-agent-v1",
}


class _ExtractGateOutputs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.gh_output = self.tmp / "github_output"
        self.gh_output.touch()

    def _run(self, *, artifact_path: str | None) -> str:
        env = {
            "GITHUB_OUTPUT": str(self.gh_output),
        }
        if artifact_path is not None:
            env["AGENTSCORE_ARTIFACT_PATH"] = artifact_path
        with mock.patch.dict(os.environ, env, clear=True):
            rc = extract_gate_outputs.main()
        self.assertEqual(rc, 0)
        return self.gh_output.read_text(encoding="utf-8")

    def _write_artifact(self, payload) -> str:
        path = self.tmp / "artifact.json"
        if isinstance(payload, (dict, list)):
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path.write_text(payload, encoding="utf-8")
        return str(path)

    # ----------------------------- happy path ----------------------------- #
    def test_valid_artifact_writes_verdict_and_confidence(self):
        out = self._run(artifact_path=self._write_artifact(VALID_ARTIFACT))
        self.assertIn("verdict=BLOCKED\n", out)
        self.assertIn("confidence=HIGH\n", out)
        # No evidence leak.
        self.assertNotIn("bounded snippet", out)
        self.assertNotIn("policy_id", out)

    def test_release_candidate_passes_through(self):
        artifact = {"release_decision": {"verdict": "release_candidate", "confidence": "low"}}
        out = self._run(artifact_path=self._write_artifact(artifact))
        # Helper normalises to upper-case allow-list entries.
        self.assertIn("verdict=RELEASE_CANDIDATE\n", out)
        self.assertIn("confidence=LOW\n", out)

    # --------------------------- failure paths ---------------------------- #
    def test_missing_file_writes_unknown(self):
        out = self._run(artifact_path=str(self.tmp / "nope.json"))
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)

    def test_invalid_json_writes_unknown(self):
        out = self._run(artifact_path=self._write_artifact("{not json"))
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)

    def test_non_dict_root_writes_unknown(self):
        out = self._run(artifact_path=self._write_artifact(["not", "a", "dict"]))
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)

    def test_missing_release_decision_writes_unknown(self):
        out = self._run(artifact_path=self._write_artifact({"policy_id": "x"}))
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)

    def test_unknown_verdict_label_writes_unknown(self):
        artifact = {"release_decision": {"verdict": "DOOM", "confidence": "TOTAL"}}
        out = self._run(artifact_path=self._write_artifact(artifact))
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)

    # ------------------------- env edge cases ---------------------------- #
    def test_empty_artifact_env_writes_unknown(self):
        # `AGENTSCORE_ARTIFACT_PATH=""` (passed by the action when the
        # gate step itself crashed). Helper must still write a record.
        out = self._run(artifact_path="")
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)

    def test_no_github_output_is_a_noop(self):
        # Caller without GITHUB_OUTPUT (e.g. running locally) must not
        # raise and must not write to a random path.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(extract_gate_outputs.main(), 0)
        # Original output file unchanged.
        self.assertEqual(self.gh_output.read_text(encoding="utf-8"), "")

    def test_helper_never_raises_on_directory_artifact(self):
        # IsADirectoryError path — happens when a downstream step deletes
        # the .json file and `artifact_path` resolves to a folder.
        out = self._run(artifact_path=str(self.tmp))
        self.assertIn("verdict=UNKNOWN\n", out)
        self.assertIn("confidence=UNKNOWN\n", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
