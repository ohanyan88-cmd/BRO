import sqlite3
import unittest

from bro_runtime.action_runtime import ActionRequest, ActionRuntime, AdapterResult, EffectState
from bro_runtime.immune import AuthorityEnvelope
from bro_runtime.live_readback import ExternalObservation, LiveReadbackRejected, LiveReadbackRuntime


class LiveReadbackTests(unittest.TestCase):
    def setUp(self):
        self.actions = ActionRuntime(sqlite3.connect(":memory:"))
        self.envelope = AuthorityEnvelope(
            envelope_id="env-live",
            version=1,
            principal="bro",
            proof_ref="proof:live",
            authority_source="user",
            operation="customer.create",
            target="crm",
            allowed_scope=("operation:customer.create", "target:crm", "task:1"),
            prohibited_scope=(),
            task_ref="task:1",
            risk_class="R1",
            valid_from="2026-01-01T00:00:00Z",
            expires_at="2027-01-01T00:00:00Z",
            revocation_ref=None,
            environment="production",
            tool_boundary=("crm",),
            decision="ALLOWED",
            reason="requested",
            audit_ref="audit:live",
        )
        self.actions.register_authority(self.envelope)

    def request(self, request_id="action-live"):
        request = ActionRequest(
            request_id, "task:1", "create customer", "customer.create", "crm", "production", "crm",
            {"name": "Gev"}, "env-live", "R1", "reversible", "idem-1", True,
            {"customer_exists": True}, ("external-readback",),
        )
        self.actions.propose(request)
        self.actions.authorize(request_id, self.envelope, now="2026-09-01T00:00:00Z")
        self.actions.dispatch(request_id, "crm", "v1", lambda _: AdapterResult({"accepted": True}, EffectState.POSSIBLE))
        return request_id

    def test_live_effect_is_reconciled_from_external_state(self):
        request_id = self.request()
        runtime = LiveReadbackRuntime(self.actions)
        observation = runtime.reconcile_from_external_state(
            request_id,
            read=lambda: ExternalObservation("acme:crm@v1", "customer:C-1", {"customer_exists": True}, "evidence:readback:C-1"),
            expected=lambda state: state.get("customer_exists") is True,
        )
        attempt = self.actions.latest_attempt(request_id)
        self.assertEqual(observation.resource_ref, "customer:C-1")
        self.assertEqual(self.actions.effective_effect(attempt), EffectState.CONFIRMED)
        self.assertEqual(self.actions.get_request(request_id)["state"], "EFFECT_RECONCILED")

    def test_write_result_cannot_substitute_for_live_readback(self):
        request_id = self.request("action-no-read")
        runtime = LiveReadbackRuntime(self.actions)
        with self.assertRaisesRegex(LiveReadbackRejected, "ExternalObservation"):
            runtime.reconcile_from_external_state(request_id, read=lambda: {"customer_exists": True}, expected=lambda _: True)
        self.assertEqual(self.actions.effective_effect(self.actions.latest_attempt(request_id)), EffectState.POSSIBLE)


if __name__ == "__main__":
    unittest.main()
