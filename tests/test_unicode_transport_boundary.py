"""No lone surrogate reaches a subprocess, and every real character reaches it untouched.

A lone UTF-16 surrogate is not a character. It exists in a Python string only because
something decoded bytes that were not valid UTF-8 -- and Python decodes argv, the
environment and the standard streams with surrogateescape, which is how a truncated paste
or a terminal that is not sending UTF-8 produces one. Handed to subprocess with text=True
it raises UnicodeEncodeError inside subprocess itself, before the model call starts.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bro_runtime.claude_code_cli import ClaudeCodeCLIConfig, ClaudeCodeCLIModel
from bro_runtime.inference import BROInference, InferenceRejected, first_lone_surrogate

ARMENIAN = "բարև Բրո ջան"
MIXED = "բարև 🇦🇲 Բրո ջան 👋 — ուղղագրություն, ёлка, ok"
HIGH = chr(0xD800)
LOW = chr(0xDC00)


class RecordingBackend(BROInference):
    """A backend that records every call, so "no model call happened" is checkable."""

    def __init__(self):
        self.calls: list[list[dict[str, str]]] = []
        self.config = ClaudeCodeCLIConfig()
        self.sleep = lambda _seconds: None

    def _complete(self, messages):
        self.calls.append([dict(message) for message in messages])
        return '{"mode": "TALK"}'


class UnicodeScalarBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.backend = RecordingBackend()

    # ------------------------------------------------ every real character survives
    def test_valid_armenian_reaches_the_backend_byte_for_byte(self):
        self.backend.complete([{"role": "user", "content": ARMENIAN}])
        delivered = self.backend.calls[0][0]["content"]
        self.assertEqual(delivered, ARMENIAN)
        self.assertEqual(delivered.encode("utf-8"), ARMENIAN.encode("utf-8"))

    def test_armenian_mixed_with_emoji_and_cyrillic_reaches_the_backend_unchanged(self):
        self.backend.complete([{"role": "user", "content": MIXED}])
        self.assertEqual(self.backend.calls[0][0]["content"], MIXED)
        self.assertEqual(self.backend.calls[0][0]["content"].encode("utf-8"), MIXED.encode("utf-8"))

    def test_the_boundary_alters_nothing_it_accepts(self):
        messages = [{"role": "system", "content": MIXED}, {"role": "user", "content": ARMENIAN}]
        self.backend.complete(messages)
        self.assertEqual(self.backend.calls[0], messages)

    # ------------------------------------------------------- malformed input is refused
    def test_a_lone_high_surrogate_is_refused_before_any_model_call(self):
        with self.assertRaises(InferenceRejected) as raised:
            self.backend.complete([{"role": "user", "content": ARMENIAN + HIGH}])
        self.assertIn("U+D800", str(raised.exception))
        self.assertIn("lone UTF-16 surrogate", str(raised.exception))
        self.assertEqual(self.backend.calls, [], "no model call may happen with invalid Unicode")

    def test_a_lone_low_surrogate_is_refused_before_any_model_call(self):
        with self.assertRaises(InferenceRejected) as raised:
            self.backend.complete([{"role": "user", "content": LOW + ARMENIAN}])
        self.assertIn("U+DC00", str(raised.exception))
        self.assertEqual(self.backend.calls, [])

    def test_the_diagnostic_names_which_part_of_the_prompt_carried_it(self):
        """Evidence about where it came from: the role that carried the bad scalar."""
        with self.assertRaises(InferenceRejected) as raised:
            self.backend.complete([
                {"role": "system", "content": "clean durable record"},
                {"role": "assistant", "content": "earlier turn" + HIGH},
                {"role": "user", "content": ARMENIAN},
            ])
        message = str(raised.exception)
        self.assertIn("message 1", message)
        self.assertIn("'assistant'", message)
        self.assertIn("surrogateescape", message)

    def test_a_malformed_role_is_refused_too(self):
        with self.assertRaises(InferenceRejected):
            self.backend.complete([{"role": "user" + HIGH, "content": ARMENIAN}])
        self.assertEqual(self.backend.calls, [])

    # --------------------------------------------- the paths a person actually reaches
    def test_malformed_conversation_history_cannot_crash_routing(self):
        with self.assertRaises(InferenceRejected):
            self.backend.route_interaction(ARMENIAN, history=[
                {"role": "user", "content": "earlier" + HIGH},
                {"role": "assistant", "content": "reply"},
            ])
        self.assertEqual(self.backend.calls, [])

    def test_malformed_durable_record_cannot_crash_a_conversational_response(self):
        with self.assertRaises(InferenceRejected):
            self.backend.conversational_response(
                "TALK", ARMENIAN, record="prior verified experience" + LOW)
        self.assertEqual(self.backend.calls, [])

    def test_a_malformed_request_cannot_crash_a_conversational_response(self):
        with self.assertRaises(InferenceRejected):
            self.backend.conversational_response("TALK", ARMENIAN + HIGH)
        self.assertEqual(self.backend.calls, [])

    def test_a_clean_conversation_still_reaches_the_backend(self):
        self.backend.conversational_response("TALK", ARMENIAN, record="record with 🇦🇲 and ёлка")
        self.assertTrue(self.backend.calls)
        for message in self.backend.calls[0]:
            message["content"].encode("utf-8")


class SubprocessTransportTests(unittest.TestCase):
    """The real adapter: what the boundary is actually standing in front of."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.executable = Path(directory.name) / "fake-claude"
        self.executable.write_text(
            "#!/bin/sh\ncat > /dev/null\n"
            'printf \'{"type":"result","subtype":"success","is_error":false,"result":"ok"}\'\n',
            encoding="utf-8")
        self.executable.chmod(0o755)
        self.model = ClaudeCodeCLIModel(ClaudeCodeCLIConfig(
            executable=str(self.executable), timeout_seconds=30, max_attempts=1))

    def test_subprocess_really_does_raise_on_a_lone_surrogate(self):
        """The failure this boundary exists for, reproduced at its true origin."""
        with self.assertRaises(UnicodeEncodeError):
            subprocess.run([sys.executable, "-c", "import sys; sys.stdin.read()"],
                           input=ARMENIAN + HIGH, text=True, capture_output=True, check=False)

    def test_the_real_adapter_refuses_before_it_can_reach_subprocess(self):
        with self.assertRaises(InferenceRejected) as raised:
            self.model.complete([{"role": "user", "content": ARMENIAN + HIGH}])
        self.assertIn("lone UTF-16 surrogate", str(raised.exception))

    def test_the_real_adapter_still_carries_armenian_and_emoji_through(self):
        answer = self.model.complete([{"role": "user", "content": MIXED}])
        self.assertEqual(answer, "ok")

    def test_a_backend_never_calls_complete_itself(self):
        """One boundary means one caller of _complete; a second would be a way around it."""
        source = Path(__file__).resolve().parents[1] / "src/bro_runtime/inference.py"
        self.assertEqual(source.read_text(encoding="utf-8").count("self._complete("), 1)
        backend = Path(__file__).resolve().parents[1] / "src/bro_runtime/claude_code_cli.py"
        self.assertNotIn("self._complete(", backend.read_text(encoding="utf-8"))


class SurrogateDetectionTests(unittest.TestCase):
    def test_real_text_has_none(self):
        for text in (ARMENIAN, MIXED, "", "plain ascii", "ёлка", "🇦🇲"):
            self.assertEqual(first_lone_surrogate(text), -1, text)

    def test_both_halves_of_the_surrogate_range_are_found(self):
        for codepoint in (0xD800, 0xDBFF, 0xDC00, 0xDFFF):
            self.assertEqual(first_lone_surrogate("ab" + chr(codepoint)), 2, hex(codepoint))


if __name__ == "__main__":
    unittest.main()
