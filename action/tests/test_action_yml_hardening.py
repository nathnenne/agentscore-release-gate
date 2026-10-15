"""TSK_157 — static tests over ``action/action.yml``.

These tests are the *regression guard* against RES_154 P0 #3. They run
as plain text inspection (no YAML parser dependency, no GitHub API),
so a future contributor cannot accidentally re-introduce shell-level
script injection without breaking the suite.

Hardening contract:

1. No ``run:`` block contains a literal ``${{ inputs.`` expression
   (every input must arrive through a step-level ``env:`` map).
2. No ``run:`` block contains ``${{ steps.*.outputs.*`` for a
   ``steps.gate.outputs.artifact_path`` / ``event_path`` / ``sarif_path``
   reference inside the body (those are derived from untrusted inputs
   via the gate step) — the action must wrap them in ``env:`` like any
   other input. (Their use inside the action-level ``outputs:`` block
   and inside ``with:`` keys of `upload-artifact` is fine — those are
   evaluated by the runner, not by bash/python.)
3. No ``python -c`` invocation remains anywhere.
4. No ``echo "$AGENTSCORE_TOKEN"`` / token-shaped echo.
5. The first runtime step is the validator.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ACTION_YML = Path(__file__).resolve().parent.parent / "action.yml"


def _iter_run_blocks(text: str) -> list[str]:
    """Yield every ``run: |`` body in the file as a single string.

    YAML's block-scalar marker is ``run: |`` (with optional indentation
    modifier). We collect every contiguous indented line until the
    indent decreases below the body's level OR another top-level YAML
    key appears.

    This is text-level inspection because the action contract is text-
    level: a workflow runner reads exactly what's in this file, so the
    test should too.
    """

    lines = text.splitlines()
    bodies: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(?P<indent>\s+)run:\s*\|\s*$", line)
        if m:
            base_indent = len(m.group("indent"))
            body_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                cur = lines[j]
                if cur.strip() == "":
                    body_lines.append(cur)
                    j += 1
                    continue
                cur_indent = len(cur) - len(cur.lstrip(" "))
                if cur_indent <= base_indent:
                    break
                body_lines.append(cur)
                j += 1
            bodies.append("\n".join(body_lines))
            i = j
            continue
        i += 1
    return bodies


class _NoExpressionsInRunBlocks(unittest.TestCase):
    """The headline RES_154 P0 #3 contract."""

    def setUp(self):
        self.text = ACTION_YML.read_text(encoding="utf-8")
        self.bodies = _iter_run_blocks(self.text)

    def test_at_least_one_run_block_present(self):
        # Sanity: if the parser is broken, all the assertions below would
        # vacuously pass. Anchor that we actually see the bodies.
        self.assertGreater(len(self.bodies), 4, "expected several run: | bodies")

    def test_no_inputs_expression_inside_any_run_body(self):
        for idx, body in enumerate(self.bodies):
            with self.subTest(block_index=idx):
                self.assertNotIn(
                    "${{ inputs.",
                    body,
                    "run: block must not interpolate inputs — pass via env:",
                )
                # Some workflows write `${{inputs.foo}}` without the
                # space. Catch both spellings.
                self.assertNotIn("${{inputs.", body)

    def test_no_steps_outputs_expression_inside_any_run_body(self):
        for idx, body in enumerate(self.bodies):
            with self.subTest(block_index=idx):
                self.assertNotRegex(
                    body,
                    r"\$\{\{\s*steps\.[A-Za-z0-9_\-]+\.outputs\.",
                    "run: block must not interpolate step outputs — pass via env:",
                )

    def test_no_inline_python_c_remains(self):
        # Inline `python -c` previously held a JSON-escape sink for the
        # artifact-name input. The replacement helper is
        # action/extract_gate_outputs.py. We strip YAML comments first
        # so the file header (which *describes* the deleted pattern) is
        # not flagged as a regression.
        code = "\n".join(
            line for line in self.text.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotRegex(
            code,
            r"python\s+-c\s",
            "no `python -c` block must remain — use a checked-in helper",
        )

    def test_no_token_echo_anywhere(self):
        # Belt-and-braces — the existing logic never echoes the token,
        # but pin it so a careless debug `echo "$AGENTSCORE_TOKEN"`
        # does not slip into a future PR.
        for line in self.text.splitlines():
            self.assertNotRegex(
                line,
                r"echo\s+.*\$\{?AGENTSCORE_TOKEN\}?",
                f"never echo AGENTSCORE_TOKEN: {line!r}",
            )

    def test_first_runtime_step_is_validator(self):
        # Find the first `name:` under `steps:` and assert it is the
        # validator. This is mostly documentation-as-test — if the
        # ordering ever shifts, a reviewer should look hard at why.
        steps_idx = self.text.index("\n  steps:")
        tail = self.text[steps_idx:]
        first_step = re.search(r"^\s+-\s+name:\s+(.+)$", tail, re.MULTILINE)
        self.assertIsNotNone(first_step)
        self.assertEqual(first_step.group(1).strip(), "Validate inputs")


class _StaticContractsArePresent(unittest.TestCase):
    """The validator + helper must be referenced from action.yml itself
    so the security guarantee survives a partial revert."""

    def test_action_yml_invokes_validate_inputs(self):
        text = ACTION_YML.read_text(encoding="utf-8")
        self.assertIn("validate_inputs.py", text)

    def test_action_yml_invokes_extract_gate_outputs(self):
        text = ACTION_YML.read_text(encoding="utf-8")
        self.assertIn("extract_gate_outputs.py", text)

    def test_action_yml_declares_allow_http_local_input(self):
        text = ACTION_YML.read_text(encoding="utf-8")
        self.assertIn("allow-http-local:", text)


# --------------------------------------------------------------------------- #
# Defence in depth: the validator regex rejects every shell metacharacter we #
# pin in the static layer. This proves the YAML layer and the Python layer  #
# agree on the same allow-list (TSK_157 §"static test asserts risky shell    #
# metacharacter examples are rejected by the validator, not merely quoted"). #
# --------------------------------------------------------------------------- #
import sys  # noqa: E402

ACTION_DIR = ACTION_YML.parent
if str(ACTION_DIR) not in sys.path:
    sys.path.insert(0, str(ACTION_DIR))

import validate_inputs  # noqa: E402,F401


class _ValidatorAgreesWithStaticContract(unittest.TestCase):
    def test_known_metacharacter_payloads_are_rejected(self):
        from validate_inputs import (
            ValidationError,
            validate_api_url,
            validate_artifact_name,
            validate_gate,
            validate_suite_id,
        )

        # Every payload here is a string we KNOW used to flow into a
        # `run:` body via `${{ inputs.* }}`. Test the validator agrees
        # with the regex pinned at the YAML layer.
        cases: list[tuple[str, str, object]] = [
            ("artifact-name", "evil;curl evil.tld", validate_artifact_name),
            ("artifact-name", "evil$(id)", validate_artifact_name),
            ("artifact-name", "evil`id`", validate_artifact_name),
            ("artifact-name", "evil\n::set-output name=token::leak", validate_artifact_name),
            ("artifact-name", "../etc/passwd", validate_artifact_name),
            ("gate", "evil$(id)", validate_gate),
            ("suite-id", "11111111-2222-3333-4444-555555555555;DROP", validate_suite_id),
            ("api-url", "https://api.example`whoami`", validate_api_url),
            ("api-url", "https://api.example/$(curl)", validate_api_url),
            ("api-url", "http://api.example", validate_api_url),
        ]
        for field, payload, fn in cases:
            with self.subTest(field=field, payload=repr(payload)):
                with self.assertRaises(ValidationError):
                    fn(payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
