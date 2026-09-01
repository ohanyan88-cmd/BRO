import sqlite3
import unittest

from bro_runtime.approval import Approval, ApprovalDecision, RevocationState
from bro_runtime.human_loop import HumanApprovalLoop, HumanLoopRejected, InteractionState, NotificationState


class HumanApprovalLoopTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.loop = HumanApprovalLoop(self.connection)
        self.approval = Approval(
            approval_id="approval:1",
            approver="human:owner",
            proof_ref="proof:requested",
            requested_action="calendar.event.ensure",
            target="calendar:primary",
            scope=("project:alpha",),
            risk_class="HIGH",
            consequences=("creates external calendar state",),
            conditions=("confirm target",),
            valid_from="2026-09-01T00:00:00Z",
            expires_at=None,
            decision=ApprovalDecision.REQUESTED,
            revocation_state=RevocationState.ACTIVE,
            task_ref="task:1",
            action_request_ref="action:1",
            audit_ref="audit:1",
            step_ref="step:1",
        )

    def tearDown(self):
        self.connection.close()

    def test_request_delivery_and_human_response_return_to_same_task(self):
        interaction, token = self.loop.request(self.approval, channel="email", recipient="owner@example.test", response_token="secret-response-token")
        self.assertEqual(interaction.task_ref, "task:1")
        self.assertEqual(interaction.state, InteractionState.WAITING)
        claimed = self.loop.claim_notification(
            "approval:1", owner="notifier:1", lease_until="2026-09-01T00:05:00Z", now="2026-09-01T00:00:00Z"
        )
        self.assertEqual(claimed.notification_state, NotificationState.LEASED)
        with self.assertRaises(HumanLoopRejected):
            self.loop.claim_notification(
                "approval:1", owner="notifier:2", lease_until="2026-09-01T00:06:00Z", now="2026-09-01T00:01:00Z"
            )
        sent = self.loop.mark_sent("approval:1", owner="notifier:1", now="2026-09-01T00:01:00Z")
        self.assertEqual(sent.notification_state, NotificationState.SENT)
        recorded = self.loop.respond(
            "approval:1", responder="human:owner", response_token=token,
            decision=ApprovalDecision.APPROVED, proof_ref="proof:human-response",
        )
        self.assertEqual(recorded["version"], 2)
        self.assertEqual(recorded["task_ref"], "task:1")
        self.assertEqual(recorded["decision"], "APPROVED")
        self.assertEqual(self.loop.fetch("approval:1").state, InteractionState.RESOLVED)

    def test_wrong_human_or_token_cannot_resolve_approval(self):
        _, token = self.loop.request(self.approval, channel="chat", recipient="owner")
        with self.assertRaises(HumanLoopRejected):
            self.loop.respond("approval:1", responder="human:other", response_token=token, decision=ApprovalDecision.APPROVED, proof_ref="proof:x")
        with self.assertRaises(HumanLoopRejected):
            self.loop.respond("approval:1", responder="human:owner", response_token="wrong", decision=ApprovalDecision.APPROVED, proof_ref="proof:x")
        self.assertEqual(self.loop.fetch("approval:1").state, InteractionState.WAITING)


if __name__ == "__main__":
    unittest.main()
