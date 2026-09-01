import unittest

from bro_runtime import (
    ActionRequest,
    AdapterResult,
    AuthorityEnvelope,
    BoundaryViolation,
    EffectState,
    Evidence,
    EvidenceFreshness,
    EvidenceValidity,
    SpecialistAssignment,
    SQLiteTaskStore,
    TaskSupervisor,
    evidence_scope,
)

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"


def envelope(task: str, auth: str, assignment: str) -> AuthorityEnvelope:
    return AuthorityEnvelope(
        envelope_id=auth, version=1, principal="user:1", proof_ref="proof:1", authority_source="user",
        operation="write", target=f"resource:{task}",
        allowed_scope=("operation:write", f"target:resource:{task}", task, "project:BRO"),
        prohibited_scope=(), task_ref=task, risk_class="R2", valid_from="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z", revocation_ref=None, environment="prod",
        tool_boundary=("adapter:test",), decision="ALLOWED", reason="bounded test", audit_ref=f"audit:{task}",
    )


def assignment(task: str, auth: str, assignment_id: str) -> SpecialistAssignment:
    return SpecialistAssignment(
        assignment_id, task, f"step:{task}", "BRO", "cap:test", f"context:{task}", "artifact:test",
        auth, ("adapter:test",), None, {}, ("verified",),
    )


def action(task: str, auth: str, assignment_id: str, action_id: str) -> ActionRequest:
    return ActionRequest(
        action_id, task, "write", "write", f"resource:{task}", "prod", "adapter:test", {}, auth, "R2",
        "REVERSIBLE", f"idem:{action_id}", True, "ok", ("readback",), assignment_id, "BRO",
    )


class AuditBoundaryRegressionTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteTaskStore()
        self.addCleanup(self.store.close)
        self.runtime = TaskSupervisor(self.store)

    def open(self, task: str, auth: str, assignment_id: str):
        return self.runtime.open_flow(
            task_id=task, goal_ref=f"goal:{task}", plan_ref=f"plan:{task}",
            assignment=assignment(task, auth, assignment_id), envelope=envelope(task, auth, assignment_id),
            worker_id=f"worker:{task}", now=T0,
        )

    def test_cross_task_reconciliation_is_rejected_before_mutating_other_action(self):
        a = self.open("task:A", "auth:A", "assignment:A")
        b = self.open("task:B", "auth:B", "assignment:B")
        self.runtime.execute(
            b, action("task:B", "auth:B", "assignment:B", "action:B"), executor="worker:B",
            interface_version="1", adapter=lambda _: AdapterResult("ok", EffectState.POSSIBLE), now=T1,
        )
        evidence = Evidence(
            "evidence:A", "verified", "readback", "test", {}, "readback", T1, True,
            evidence_scope("BRO", "task:A"), (), EvidenceValidity.VALID, EvidenceFreshness.CURRENT,
            "IMMUNE_SYSTEM",
        )
        with self.assertRaisesRegex(BoundaryViolation, "different task"):
            self.runtime.reconcile(a, "action:B", EffectState.CONFIRMED, evidence, now=T1)
        attempt = self.runtime.actions.latest_attempt("action:B")
        self.assertEqual(self.runtime.actions.effective_effect(attempt), EffectState.POSSIBLE)


if __name__ == "__main__":
    unittest.main()
