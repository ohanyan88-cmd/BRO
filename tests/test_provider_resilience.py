"""A brief throttle is worth one more try. A wall is not, and must say so."""
import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass

from bro_runtime.inference import BROInference, InferenceRejected, TransientInferenceError
from scripts.bro_interact import BOUNDARY_FAILURES, handle


@dataclass(frozen=True)
class Settings:
    model_ref: str = "stub:backend"
    max_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    max_retry_wait_seconds: float = 10.0


class Backend(BROInference):
    """A backend that only decides how a conversation becomes text -- like any other."""

    def __init__(self, outcomes, settings=Settings()):
        self.config = settings
        self.outcomes = list(outcomes)
        self.calls = 0
        self.slept = []
        self.sleep = self.slept.append

    def _complete(self, messages):
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def guarded(self):
        return self._with_retries(lambda: self._complete([{"role": "user", "content": "x"}]))


class BoundedRetryTests(unittest.TestCase):
    def transient(self, message="throttled", retry_after=None):
        return TransientInferenceError(message, retry_after=retry_after)

    def test_a_transient_failure_is_retried_and_can_succeed(self):
        backend = Backend([self.transient(), "answer"])
        self.assertEqual(backend.guarded(), "answer")
        self.assertEqual(backend.calls, 2)
        self.assertEqual(backend.slept, [1.0])

    def test_retries_are_bounded_and_the_failure_says_how_many(self):
        backend = Backend([self.transient("status 429")])
        with self.assertRaises(InferenceRejected) as caught:
            backend.guarded()
        self.assertEqual(backend.calls, 3, "bounded: three attempts, not an endless loop")
        self.assertIn("gave up after 3 attempts", str(caught.exception))
        self.assertIn("429", str(caught.exception))
        self.assertEqual(backend.slept, [1.0, 2.0], "backoff doubles between attempts")

    def test_backoff_is_capped(self):
        backend = Backend([self.transient()], Settings(max_attempts=5, retry_backoff_seconds=10.0,
                                                       max_retry_wait_seconds=3.0))
        with self.assertRaises(InferenceRejected):
            backend.guarded()
        self.assertEqual(backend.slept, [3.0, 3.0, 3.0, 3.0])

    def test_a_retry_after_hint_is_honoured_within_the_cap(self):
        backend = Backend([self.transient(retry_after=2.5), "answer"])
        backend.guarded()
        self.assertEqual(backend.slept, [2.5])

    def test_a_non_transient_failure_is_not_retried(self):
        backend = Backend([InferenceRejected("model did not return valid JSON")])
        with self.assertRaisesRegex(InferenceRejected, "valid JSON"):
            backend.guarded()
        self.assertEqual(backend.calls, 1, "a determinate failure must not be retried into silence")
        self.assertEqual(backend.slept, [])

    def test_a_single_attempt_configuration_never_sleeps(self):
        backend = Backend([self.transient()], Settings(max_attempts=1))
        with self.assertRaises(InferenceRejected):
            backend.guarded()
        self.assertEqual(backend.calls, 1)
        self.assertEqual(backend.slept, [])

    def test_the_retry_policy_belongs_to_the_boundary_not_to_a_backend(self):
        for shared in ("_with_retries", "_wait_before"):
            self.assertIn(shared, BROInference.__dict__,
                          f"{shared} must be defined once, above every backend")


class Surface:
    def __init__(self, error):
        self.error = error

    def submit(self, request):
        raise self.error


class InteractiveResilienceTests(unittest.TestCase):
    def test_a_provider_failure_is_reported_not_raised(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = handle(Surface(InferenceRejected(
                "Claude Code CLI reported upstream status 429 (gave up after 3 attempts)")), "study yourself")
        self.assertEqual(status, 1)
        message = stderr.getvalue()
        self.assertIn("could not complete that request", message)
        self.assertIn("429", message, "the real cause is shown, not swallowed")
        self.assertIn("gave up after 3 attempts", message)
        self.assertIn("Nothing was executed", message)

    def test_every_boundary_failure_type_is_covered(self):
        from bro_runtime.github_provider import GitHubProviderRejected

        self.assertEqual(set(BOUNDARY_FAILURES), {InferenceRejected, GitHubProviderRejected})
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
