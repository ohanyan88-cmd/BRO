import json
import sqlite3
import unittest

from bro_runtime.action_runtime import ActionRequest, ActionRuntime, AdapterResult, EffectState
from bro_runtime.immune import AuthorityEnvelope
from bro_runtime.secret_runtime import GovernedSecretDispatch, SecretMediator, SecretRejected


def envelope() -> AuthorityEnvelope:
    return AuthorityEnvelope(
        envelope_id="auth:secret", version=1, principal="user:1", proof_ref="proof:secret",
        authority_source="user", operation="write", target="crm:customer", allowed_scope=(
            "operation:write", "target:crm:customer", "task:secret"
        ), prohibited_scope=(), task_ref="task:secret", risk_class="R1",
        valid_from="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
        revocation_ref=None, environment="production", tool_boundary=("crm",),
        decision="ALLOWED", reason="requested", audit_ref="audit:secret",
    )


def request(adapter_id="crm") -> ActionRequest:
    return ActionRequest(
        action_request_id="action:secret", task_ref="task:secret", intended_effect="create customer",
        operation="write", target="crm:customer", environment="production", adapter_id=adapter_id,
        input_parameters={"name": "Gev", "credential": "secret:crm"},
        authority_envelope_ref="auth:secret", risk_class="R1", reversibility="REVERSIBLE",
        idempotency_key="secret-1", idempotency_guaranteed=True, expected_result={"ok": True},
        verification_requirements=("external-readback",),
    )


class SecretMediationTests(unittest.TestCase):
    def setUp(self):
        self.actions = ActionRuntime(sqlite3.connect(":memory:"))
        self.auth = envelope()
        self.actions.register_authority(self.auth)
        self.secrets = SecretMediator()
        self.secrets.register("secret:crm", "crm", "TOP-SECRET-VALUE")

    def authorize(self):
        self.actions.propose(request())
        self.actions.authorize("action:secret", self.auth, "2026-09-01T00:00:00Z")

    def test_secret_never_crosses_unapproved_boundary(self):
        with self.assertRaisesRegex(SecretRejected, "approved adapter boundary"):
            self.secrets.resolve("secret:crm", "billing")
        self.authorize()
        seen = {}
        runtime = GovernedSecretDispatch(self.actions, self.secrets)
        runtime.dispatch(
            "action:secret", "v1", {"api_key": "secret:crm"},
            lambda inputs: seen.update(inputs) or AdapterResult({"ok": True}, EffectState.POSSIBLE),
        )
        self.assertEqual(seen["api_key"], "TOP-SECRET-VALUE")
        stored_request = self.actions.get_request("action:secret")["body"]
        stored_attempt = self.actions.latest_attempt("action:secret")["sanitized_inputs"]
        self.assertNotIn("TOP-SECRET-VALUE", stored_request)
        self.assertNotIn("TOP-SECRET-VALUE", stored_attempt)
        self.assertEqual(json.loads(stored_attempt)["credential"], "secret:crm")

    def test_secret_resolution_requires_authorized_action(self):
        self.actions.propose(request())
        runtime = GovernedSecretDispatch(self.actions, self.secrets)
        with self.assertRaisesRegex(SecretRejected, "AUTHORIZED"):
            runtime.dispatch("action:secret", "v1", {"api_key": "secret:crm"}, lambda _: None)


if __name__ == "__main__":
    unittest.main()

class SecretLifecycleTests(unittest.TestCase):
    def test_expired_and_revoked_secrets_fail_closed_without_value_in_error(self):
        mediator=SecretMediator()
        mediator.register("secret:expired", "github", "DO-NOT-LEAK", expires_at="2026-01-01T00:00:00Z")
        with self.assertRaisesRegex(SecretRejected, "expired") as expired:
            mediator.resolve("secret:expired", "github", now="2026-09-01T00:00:00Z")
        self.assertNotIn("DO-NOT-LEAK", str(expired.exception))
        mediator.register("secret:revoked", "github", "ALSO-SECRET")
        mediator.revoke("secret:revoked")
        with self.assertRaisesRegex(SecretRejected, "revoked") as revoked:
            mediator.resolve("secret:revoked", "github")
        self.assertNotIn("ALSO-SECRET", str(revoked.exception))
