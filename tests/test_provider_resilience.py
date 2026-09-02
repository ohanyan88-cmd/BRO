"""A brief throttle is worth one more try. A wall is not, and must say so."""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from urllib.error import HTTPError, URLError

from bro_runtime.external_model import (
    RETRYABLE_STATUSES,
    ExternalModel,
    ExternalModelConfig,
    ExternalModelRejected,
    TransientExternalModelError,
)
from scripts.bro_interact import BOUNDARY_FAILURES, handle

OK = {"choices": [{"finish_reason": "stop", "message": {"content": '{"a": 1}'}}]}


class BoundedRetryTests(unittest.TestCase):
    def build(self, outcomes, **config):
        self.calls = 0
        self.slept = []

        def transport(method, url, headers, data, timeout):
            outcome = outcomes[min(self.calls, len(outcomes) - 1)]
            self.calls += 1
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        settings = {"provider": "stub", "api_key": "k", "model": "m",
                    "api_url": "https://example.invalid/v1", "retry_backoff_seconds": 1.0}
        settings.update(config)
        return ExternalModel(ExternalModelConfig(**settings), transport=transport,
                             sleep=self.slept.append)

    def transient(self, message="throttled", retry_after=None):
        return TransientExternalModelError(message, retry_after=retry_after)

    def test_a_transient_failure_is_retried_and_can_succeed(self):
        model = self.build([self.transient(), OK])
        self.assertEqual(model.json_object(instruction="i", request="r"), {"a": 1})
        self.assertEqual(self.calls, 2)
        self.assertEqual(self.slept, [1.0])

    def test_retries_are_bounded_and_the_failure_says_how_many(self):
        model = self.build([self.transient("status 429")], max_attempts=3)
        with self.assertRaises(ExternalModelRejected) as caught:
            model.json_object(instruction="i", request="r")
        self.assertEqual(self.calls, 3, "bounded: three attempts, not an endless loop")
        self.assertIn("gave up after 3 attempts", str(caught.exception))
        self.assertIn("429", str(caught.exception))
        self.assertEqual(self.slept, [1.0, 2.0], "backoff doubles between attempts")

    def test_backoff_is_capped(self):
        model = self.build([self.transient()], max_attempts=5, retry_backoff_seconds=10.0,
                           max_retry_wait_seconds=3.0)
        with self.assertRaises(ExternalModelRejected):
            model.json_object(instruction="i", request="r")
        self.assertEqual(self.slept, [3.0, 3.0, 3.0, 3.0])

    def test_a_retry_after_header_is_honoured_within_the_cap(self):
        model = self.build([self.transient(retry_after=2.5), OK], max_retry_wait_seconds=10.0)
        model.json_object(instruction="i", request="r")
        self.assertEqual(self.slept, [2.5])

    def test_a_configuration_failure_is_not_retried(self):
        model = self.build([ExternalModelRejected("external model API rejected request with status 401")])
        with self.assertRaisesRegex(ExternalModelRejected, "401"):
            model.json_object(instruction="i", request="r")
        self.assertEqual(self.calls, 1, "an authorisation fact must not be retried into silence")
        self.assertEqual(self.slept, [])

    def test_a_single_attempt_configuration_never_sleeps(self):
        model = self.build([self.transient()], max_attempts=1)
        with self.assertRaises(ExternalModelRejected):
            model.json_object(instruction="i", request="r")
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.slept, [])

    def test_the_retryable_set_is_throttling_and_gateway_faults_only(self):
        self.assertEqual(RETRYABLE_STATUSES, frozenset({429, 500, 502, 503, 504}))
        for refused in (400, 401, 403, 404, 422):
            self.assertNotIn(refused, RETRYABLE_STATUSES)

    def test_the_real_transport_classifies_statuses_correctly(self):
        def raise_http(code):
            raise HTTPError("https://example.invalid", code, "boom", {}, None)

        for code in (429, 503):
            with self.assertRaises(TransientExternalModelError):
                try:
                    raise_http(code)
                except HTTPError as exc:
                    ExternalModel._classify(exc)
        with self.assertRaises(ExternalModelRejected) as caught:
            try:
                raise_http(401)
            except HTTPError as exc:
                ExternalModel._classify(exc)
        self.assertNotIsInstance(caught.exception, TransientExternalModelError)

    def test_a_dropped_connection_is_transient(self):
        model = self.build([TransientExternalModelError("external model API request failed"), OK])
        self.assertEqual(model.json_object(instruction="i", request="r"), {"a": 1})
        self.assertEqual(self.calls, 2)

    def test_invalid_retry_configuration_is_refused(self):
        for bad in ({"max_attempts": 0}, {"retry_backoff_seconds": -1}, {"max_retry_wait_seconds": -1}):
            with self.assertRaises(ExternalModelRejected):
                ExternalModelConfig(provider="s", api_key="k", model="m",
                                    api_url="https://example.invalid/v1", **bad)


class Surface:
    def __init__(self, error):
        self.error = error

    def submit(self, request):
        raise self.error


class InteractiveResilienceTests(unittest.TestCase):
    def test_a_provider_failure_is_reported_not_raised(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = handle(Surface(ExternalModelRejected(
                "external model API rejected request with status 429 (gave up after 3 attempts)")), "study yourself")
        self.assertEqual(status, 1)
        message = stderr.getvalue()
        self.assertIn("could not complete that request", message)
        self.assertIn("429", message, "the real cause is shown, not swallowed")
        self.assertIn("gave up after 3 attempts", message)
        self.assertIn("Nothing was executed", message)

    def test_every_boundary_failure_type_is_covered(self):
        from bro_runtime.anthropic_messages import AnthropicMessagesRejected
        from bro_runtime.github_provider import GitHubProviderRejected

        self.assertEqual(set(BOUNDARY_FAILURES),
                         {ExternalModelRejected, AnthropicMessagesRejected, GitHubProviderRejected})
        for failure in BOUNDARY_FAILURES:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(handle(Surface(failure("unavailable")), "hello"), 1)

    def test_a_governance_refusal_is_deliberately_not_caught(self):
        from bro_runtime.final_delivery import FinalDeliveryRejected

        with self.assertRaises(FinalDeliveryRejected):
            handle(Surface(FinalDeliveryRejected("scope digest does not match")), "post a comment")

    def test_a_successful_turn_returns_zero(self):
        class Talking:
            def submit(self, request):
                return {"mode": "TALK", "response": "hello", "requires_confirmation": False}

        with redirect_stdout(io.StringIO()):
            self.assertEqual(handle(Talking(), "hi"), 0)


if __name__ == "__main__":
    unittest.main()
