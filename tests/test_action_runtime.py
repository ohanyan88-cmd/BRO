from __future__ import annotations

import sqlite3
import unittest

from bro_runtime import ActionRequest, ActionRuntime, ActionState, AdapterResult, AuthorityEnvelope, EffectState, RetryBlocked
from bro_runtime.action_runtime import ActionRejected


def envelope(**changes) -> AuthorityEnvelope:
    values = dict(envelope_id="auth:1", version=1, principal="user:1", proof_ref="proof:1", authority_source="user", operation="write", target="repo:BRO", allowed_scope=("operation:write", "target:repo:BRO", "task:1"), prohibited_scope=(), task_ref="task:1", risk_class="R3", valid_from="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z", revocation_ref=None, environment="github", tool_boundary=("github",), decision="ALLOWED", reason="requested", audit_ref="audit:1")
    values.update(changes)
    return AuthorityEnvelope(**values)


def request(**changes) -> ActionRequest:
    values = dict(action_request_id="action:1", task_ref="task:1", intended_effect="write file", operation="write", target="repo:BRO", environment="github", adapter_id="github", input_parameters={"path": "x"}, authority_envelope_ref="auth:1", risk_class="R3", reversibility="DIFFICULT", idempotency_key="key:1", idempotency_guaranteed=False, expected_result={"ok": True}, verification_requirements=("remote read",))
    values.update(changes)
    return ActionRequest(**values)


class ActionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = ActionRuntime(sqlite3.connect(":memory:"))
        self.auth = envelope()
        self.runtime.register_authority(self.auth)
        self.runtime.propose(request())

    def authorize(self) -> None:
        self.runtime.authorize("action:1", self.auth, "2026-09-01T00:00:00Z")

    def dispatch(self, adapter, *, now="2026-09-01T00:00:01Z"):
        return self.runtime.dispatch("action:1", "github", "1", adapter, envelope=self.auth, now=now)

    def test_scope_intersection_authorizes_exact_request(self) -> None:
        self.authorize()
        self.assertEqual(self.runtime.get_request("action:1")["state"], ActionState.AUTHORIZED)

    def test_scope_or_tool_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(ActionRejected, "tool boundary"):
            self.runtime.authorize("action:1", envelope(tool_boundary=("shell",)), "2026-09-01T00:00:00Z")

    def test_envelope_is_immutable(self) -> None:
        with self.assertRaisesRegex(ActionRejected, "immutable"):
            self.runtime.register_authority(self.auth)

    def test_one_attempt_is_recorded_per_actual_try(self) -> None:
        self.authorize()
        attempt = self.dispatch(lambda _: AdapterResult({"ok": True}, EffectState.CONFIRMED))
        self.assertEqual(attempt["effect_state"], EffectState.CONFIRMED)
        self.assertEqual(self.runtime.connection.execute("SELECT count(*) FROM action_attempts").fetchone()[0], 1)

    def test_dispatch_rechecks_authority_and_blocks_expired_grant(self) -> None:
        expiring = envelope(expires_at="2026-09-01T00:00:01Z")
        other = ActionRuntime(sqlite3.connect(":memory:"))
        other.register_authority(expiring)
        other.propose(request())
        other.authorize("action:1", expiring, "2026-09-01T00:00:00Z")
        called = []
        with self.assertRaisesRegex(ActionRejected, "expired"):
            other.dispatch("action:1", "github", "1", lambda _: called.append(True), envelope=expiring, now="2026-09-01T00:00:02Z")
        self.assertEqual(called, [])
        self.assertEqual(other.get_request("action:1")["state"], ActionState.DENIED)

    def test_timeout_is_unknown_and_raw_exception_text_is_redacted(self) -> None:
        self.authorize()
        secret = "TOP-SECRET-TOKEN"
        def timeout(_): raise TimeoutError(f"transport timeout bearer={secret}")
        attempt = self.dispatch(timeout)
        self.assertEqual(attempt["status"], "TIMED_OUT")
        self.assertEqual(attempt["effect_state"], EffectState.UNKNOWN)
        self.assertEqual(attempt["error"], "TimeoutError: adapter error details redacted")
        self.assertNotIn(secret, attempt["error"])

    def test_failed_adapter_error_is_possible_and_raw_exception_text_is_redacted(self) -> None:
        self.authorize()
        secret = "TOP-SECRET-TOKEN"
        def fail(_): raise RuntimeError(f"SDK echoed credential {secret}")
        attempt = self.dispatch(fail)
        self.assertEqual(attempt["status"], "FAILED")
        self.assertEqual(attempt["effect_state"], EffectState.POSSIBLE)
        self.assertEqual(attempt["error"], "AdapterFailure: adapter error details redacted")
        self.assertNotIn(secret, attempt["error"])

    def test_unknown_effect_blocks_non_idempotent_retry_until_reconciled(self) -> None:
        self.authorize()
        def timeout(_): raise TimeoutError("timeout")
        self.dispatch(timeout)
        with self.assertRaisesRegex(RetryBlocked, "reconciled"):
            self.runtime.prepare_retry("action:1")
        self.runtime.reconcile("action:1", EffectState.NONE, "observation:remote")
        retriable = self.runtime.prepare_retry("action:1")
        self.assertEqual(retriable["state"], ActionState.AUTHORIZED)

    def test_valid_idempotency_proof_allows_unknown_retry(self) -> None:
        other = ActionRuntime(sqlite3.connect(":memory:"))
        other.register_authority(self.auth)
        other.propose(request(idempotency_guaranteed=True))
        other.authorize("action:1", self.auth, "2026-09-01T00:00:00Z")
        def timeout(_): raise TimeoutError("timeout")
        other.dispatch("action:1", "github", "1", timeout, envelope=self.auth, now="2026-09-01T00:00:01Z")
        self.assertEqual(other.prepare_retry("action:1")["state"], ActionState.AUTHORIZED)

    def test_confirmed_effect_cannot_retry(self) -> None:
        self.authorize()
        self.dispatch(lambda _: AdapterResult("done", EffectState.CONFIRMED))
        with self.assertRaisesRegex(RetryBlocked, "confirmed"):
            self.runtime.prepare_retry("action:1")


if __name__ == "__main__": unittest.main()
