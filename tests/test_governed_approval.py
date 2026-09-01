import json
import unittest

from bro_runtime import (
    ActionRequest, AdapterResult, Approval, ApprovalDecision, ApprovalRequired,
    AuthorityEnvelope, EffectState, GovernedTaskSupervisor, KnowledgeState,
    MindRuntime, RevocationState, SpecialistAssignment, SQLiteMindStore,
    SQLiteTaskStore, TaskState,
)

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"


class GovernedApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteTaskStore()
        self.mind_store = SQLiteMindStore()
        self.addCleanup(self.store.close)
        self.addCleanup(self.mind_store.close)
        mind = MindRuntime(self.mind_store)
        goal = mind.form_goal(
            intent_ref="intent:1", desired_outcome="apply governed change",
            interpreted_scope=("project:BRO",), success_conditions=("change verified",),
            authority_basis="authority:user", materiality="MATERIAL", risk_class="R3",
            uncertainty=KnowledgeState.CONFIRMED, goal_id="goal:1",
        )
        decision = mind.decide(
            goal_ref=goal.goal_id, question="execute?", conclusion="yes",
            rationale="bounded requested work", authority_basis="authority:user",
            uncertainty=KnowledgeState.CONFIRMED, reversibility="DIFFICULT",
            decision_id="decision:1",
        )
        mind.plan(
            goal_ref=goal.goal_id, decision_ref=decision.decision_id,
            step_refs=("step:1",), checkpoints=("approval",),
            recovery_options=("resume",), completion_path=("verify",),
            reason="guarded execution", plan_id="plan:1",
        )
        self.supervisor = GovernedTaskSupervisor(self.store, mind_store=self.mind_store)
        self.supervisor.nervous_records.create_step(
            step_id="step:1", task_ref="task:1", plan_ref="plan:1", plan_revision=1,
            purpose="write bounded change", expected_output="commit",
            authority_class="GUARDED", verification_requirement="tests",
            retry_policy="reconcile before retry",
        )
        self.supervisor.nervous_records.create_context_manifest(
            manifest_id="context:1", task_ref="task:1", isolation_boundary="project:BRO",
            entries=(), excluded_refs=(),
        )
        self.assignment = SpecialistAssignment(
            assignment_id="assignment:1", task_ref="task:1", step_ref="step:1",
            project_boundary="project:BRO", required_capability="capability:code",
            context_manifest_ref="context:1", expected_output_contract="contract:commit",
            authority_envelope_ref="auth:1", allowed_tools=("github",), deadline=None,
            budget={"seconds": 60}, evidence_requirements=("tests",),
        )
        self.envelope = AuthorityEnvelope(
            envelope_id="auth:1", version=1, principal="user:1", proof_ref="proof:1",
            authority_source="user", operation="write", target="repo:BRO",
            allowed_scope=("operation:write", "target:repo:BRO", "task:1", "project:BRO"),
            prohibited_scope=(), task_ref="task:1", risk_class="R3",
            valid_from="2026-01-01T00:00:00Z", expires_at="2027-01-01T00:00:00Z",
            revocation_ref=None, environment="github", tool_boundary=("github",),
            decision="APPROVAL_REQUIRED", reason="human approval required", audit_ref="audit:1",
        )

    def approval(self, **changes):
        values = dict(
            approval_id="approval:1", approver="user:1", proof_ref="proof:approval",
            requested_action="write", target="repo:BRO", scope=self.envelope.allowed_scope,
            risk_class="R3", consequences=("repository changes",), conditions=("tests required",),
            valid_from=T0, expires_at="2026-09-02T00:00:00Z",
            decision=ApprovalDecision.APPROVED, revocation_state=RevocationState.ACTIVE,
            task_ref="task:1", action_request_ref=None, audit_ref="audit:approval", step_ref="step:1",
        )
        values.update(changes)
        return Approval(**values)

    def test_approval_required_resumes_same_task_and_authorizes_action(self):
        with self.assertRaises(ApprovalRequired):
            self.supervisor.open_flow(
                task_id="task:1", goal_ref="goal:1", plan_ref="plan:1",
                assignment=self.assignment, envelope=self.envelope,
                worker_id="worker:1", now=T0,
            )
        blocked = self.store.fetch_task("task:1")
        self.assertEqual(blocked["state"], TaskState.BLOCKED)
        self.assertEqual(blocked["blocker_ref"], "auth:1")
        self.assertEqual(self.supervisor.assignments.assignments_for_task("task:1")[0]["state"], "READY")

        self.supervisor.approvals.record(self.approval())
        binding = self.supervisor.resume_with_approval(
            "task:1", "approval:1", "worker:1", now=T1,
        )
        resumed = self.store.fetch_task("task:1")
        self.assertEqual(resumed["state"], TaskState.EXECUTING)
        self.assertEqual(resumed["approval_refs"], ["approval:1"])
        self.assertIsNone(resumed["blocker_ref"])
        self.assertEqual(binding.task_id, "task:1")
        self.assertEqual(binding.assignment_id, "assignment:1")

        request = ActionRequest(
            action_request_id="action:1", task_ref="task:1", intended_effect="write change",
            operation="write", target="repo:BRO", environment="github", adapter_id="github",
            input_parameters={"path": "src/x.py"}, authority_envelope_ref="auth:1",
            risk_class="R3", reversibility="DIFFICULT", idempotency_key="key:1",
            idempotency_guaranteed=False, expected_result={"ok": True},
            verification_requirements=("tests",), assignment_ref="assignment:1",
            project_boundary="project:BRO",
        )
        attempt = self.supervisor._execute_registered_provider(
            binding, request, executor="github", interface_version="1",
            adapter=lambda _: AdapterResult({"ok": True}, EffectState.CONFIRMED), now=T1,
        )
        self.assertEqual(attempt["status"], "SUCCEEDED")
        decisions = self.supervisor.actions.authority.decisions("action:1")
        self.assertEqual([row["decision"] for row in decisions], ["APPROVAL_REQUIRED", "ALLOW"])
        self.assertEqual(self.supervisor.approvals.get("approval:1")["decision"], "CONSUMED")

    def test_expired_approval_cannot_resume(self):
        with self.assertRaises(ApprovalRequired):
            self.supervisor.open_flow(
                task_id="task:1", goal_ref="goal:1", plan_ref="plan:1",
                assignment=self.assignment, envelope=self.envelope,
                worker_id="worker:1", now=T0,
            )
        self.supervisor.approvals.record(self.approval(expires_at=T1))
        with self.assertRaisesRegex(Exception, "does not satisfy"):
            self.supervisor.resume_with_approval(
                "task:1", "approval:1", "worker:1", now=T1,
            )
        blocked = self.store.fetch_task("task:1")
        self.assertEqual(blocked["state"], TaskState.BLOCKED)
        self.assertEqual(blocked["blocker_ref"], "auth:1")


if __name__ == "__main__":
    unittest.main()
