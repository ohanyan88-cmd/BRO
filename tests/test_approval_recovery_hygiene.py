import sqlite3
import unittest

from bro_runtime import (
    Approval, ApprovalDecision, ApprovalRegistry, ApprovalRejected, GovernedTaskSupervisor,
    NextAction, RevocationState, SQLiteMindStore, SQLiteTaskStore,
    TaskRuntime, TaskState,
)

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"


class ApprovalReplayTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.registry = ApprovalRegistry(self.connection)
        self.addCleanup(self.connection.close)

    def approval(self, *, action_request_ref="action:1"):
        return Approval(
            approval_id="approval:1", approver="user:1", proof_ref="proof:1",
            requested_action="write", target="repo:BRO",
            scope=("operation:write", "target:repo:BRO", "task:1", "project:BRO"),
            risk_class="R3", consequences=("change",), conditions=(), valid_from=T0,
            expires_at="2026-09-02T00:00:00Z", decision=ApprovalDecision.APPROVED,
            revocation_state=RevocationState.ACTIVE, task_ref="task:1",
            action_request_ref=action_request_ref, audit_ref="audit:1", step_ref="step:1",
        )

    def test_consumed_approval_cannot_be_replayed_from_older_version(self):
        self.registry.record(self.approval())
        kwargs = dict(
            task_ref="task:1", action_request_ref="action:1", step_ref="step:1",
            operation="write", target="repo:BRO",
            required_scope=("operation:write", "target:repo:BRO", "task:1", "project:BRO"),
            risk_class="R3", now=T1,
        )
        self.assertIsNotNone(self.registry.approved_for(**kwargs))
        self.registry.consume("approval:1", task_ref="task:1", action_request_ref="action:1")
        self.assertEqual(self.registry.get("approval:1")["decision"], "CONSUMED")
        self.assertIsNone(self.registry.approved_for(**kwargs))

    def test_consumption_cannot_rebind_task_or_action(self):
        self.registry.record(self.approval())
        with self.assertRaises(ApprovalRejected):
            self.registry.consume("approval:1", task_ref="task:other", action_request_ref="action:1")
        with self.assertRaises(ApprovalRejected):
            self.registry.consume("approval:1", task_ref="task:1", action_request_ref="action:other")
        latest = self.registry.get("approval:1")
        self.assertEqual(latest["decision"], "APPROVED")
        self.assertEqual(latest["version"], 1)

    def test_unbound_approval_cannot_gain_action_binding_when_consumed(self):
        self.registry.record(self.approval(action_request_ref=None))
        with self.assertRaises(ApprovalRejected):
            self.registry.consume("approval:1", task_ref="task:1", action_request_ref="action:1")
        self.assertEqual(self.registry.get("approval:1")["decision"], "APPROVED")


class ApprovalRecoveryRoutingTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.supervisor = GovernedTaskSupervisor(self.store, mind_store=self.mind)
        self.addCleanup(self.store.close)
        self.addCleanup(self.mind.close)

    def test_resume_does_not_claim_work_while_approval_is_missing(self):
        runtime = TaskRuntime(self.store)
        task = runtime.create_task("task:1", "goal:1", "BRO", "received")
        task = runtime.transition("task:1", TaskState.INTERPRETING, "BRO", "frame", task["revision"])
        task = runtime.transition("task:1", TaskState.READY, "BRO", "ready", task["revision"])
        task = runtime.transition(
            "task:1", TaskState.PLANNING, "BRO", "plan", task["revision"],
            plan_ref="plan:1", plan_revision=1,
        )
        task = runtime.transition(
            "task:1", TaskState.AUTHORIZING, "BRO", "approval gate", task["revision"],
            context_manifest_ref="context:1", authority_state="APPROVAL_REQUIRED",
        )
        runtime.transition(
            "task:1", TaskState.BLOCKED, "IMMUNE_SYSTEM", "approval required",
            task["revision"], blocker_ref="auth:1",
        )
        next_step = self.supervisor.resume("task:1")
        self.assertEqual(next_step.action, NextAction.NONE)
        self.assertIn("waiting for a fresh Approval", next_step.reason)
        self.assertEqual(self.store.fetch_task("task:1")["state"], TaskState.BLOCKED)


if __name__ == "__main__":
    unittest.main()
