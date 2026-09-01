from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bro_runtime import (
    ActionRequest,
    AdapterResult,
    AssignmentState,
    AuthorityEnvelope,
    BoundaryViolation,
    CompletionVerdict,
    ConcurrencyConflict,
    EffectState,
    Evidence,
    EvidenceFreshness,
    EvidenceValidity,
    FlowBinding,
    InvalidTransition,
    NextAction,
    RetryBlocked,
    SpecialistAssignment,
    SQLiteTaskStore,
    StaleWorkerResult,
    SupervisionRejected,
    TaskState,
    TaskSupervisor,
    evidence_scope,
)
from bro_runtime.action_runtime import ActionRejected

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"
T2 = "2026-09-01T00:00:02Z"
SCOPE = evidence_scope("project:BRO", "task:1")


def assignment(**changes) -> SpecialistAssignment:
    values = dict(
        assignment_id="assignment:1", task_ref="task:1", step_ref="step:1", project_boundary="project:BRO",
        required_capability="capability:code", context_manifest_ref="context:1",
        expected_output_contract="contract:output", authority_envelope_ref="auth:1",
        allowed_tools=("github",), deadline=None, budget={"seconds": 60}, evidence_requirements=("tests pass",),
    )
    values.update(changes)
    return SpecialistAssignment(**values)


def envelope(**changes) -> AuthorityEnvelope:
    values = dict(
        envelope_id="auth:1", version=1, principal="user:1", proof_ref="proof:1", authority_source="user",
        operation="write", target="repo:BRO",
        allowed_scope=("operation:write", "target:repo:BRO", "task:1", "project:BRO"),
        prohibited_scope=(), task_ref="task:1", risk_class="R3", valid_from="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z", revocation_ref=None, environment="github",
        tool_boundary=("github",), decision="ALLOWED", reason="owner authorised the bounded repair",
        audit_ref="audit:1",
    )
    values.update(changes)
    return AuthorityEnvelope(**values)


def action(**changes) -> ActionRequest:
    values = dict(
        action_request_id="action:1", task_ref="task:1", intended_effect="write the fix",
        operation="write", target="repo:BRO", environment="github", adapter_id="github",
        input_parameters={"path": "src/x.py"}, authority_envelope_ref="auth:1", risk_class="R3",
        reversibility="DIFFICULT", idempotency_key="key:1", idempotency_guaranteed=False,
        expected_result={"ok": True}, verification_requirements=("remote read",),
        assignment_ref="assignment:1", project_boundary="project:BRO",
    )
    values.update(changes)
    return ActionRequest(**values)


def evidence(evidence_id: str = "evidence:1", criterion: str = "tests pass", **changes) -> Evidence:
    values = dict(
        evidence_id=evidence_id, criterion=criterion, evidence_type="test-run", source="unittest",
        provenance={"suite": "regression"}, collection_method="executed", collected_at=T1,
        result={"failed": 0}, scope=SCOPE, limitations=(), validity=EvidenceValidity.VALID,
        freshness=EvidenceFreshness.CURRENT, verifier="IMMUNE_SYSTEM",
    )
    values.update(changes)
    return Evidence(**values)


def confirmed(_: dict) -> AdapterResult:
    return AdapterResult({"ok": True}, EffectState.CONFIRMED, artifact_refs=("artifact:commit",))


def times_out(_: dict) -> AdapterResult:
    raise TimeoutError("transport timeout")


class SupervisionFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteTaskStore()
        self.addCleanup(self.store.close)
        self.supervisor = TaskSupervisor(self.store)

    def open(self, **changes) -> FlowBinding:
        values = dict(
            task_id="task:1", goal_ref="goal:1", plan_ref="plan:1", assignment=assignment(),
            envelope=envelope(), worker_id="worker:1", now=T0,
        )
        values.update(changes)
        return self.supervisor.open_flow(**values)

    def run_to_settled(self, binding: FlowBinding, *, state=AssignmentState.SUCCEEDED, limitations=()) -> None:
        self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                adapter=confirmed, now=T1)
        self.supervisor.settle_assignment(binding, result_state=state, output_ref="artifact:commit",
                                          evidence=(evidence(),), limitations=limitations, now=T2)

    # ---------------------------------------------------------------- happy

    def test_valid_end_to_end_completion(self) -> None:
        binding = self.open()
        self.run_to_settled(binding)
        manifest = self.supervisor.complete(
            binding, outcome_statement="the fix is written and verified",
            required_criteria=("tests pass",), now=T2,
        )
        self.assertIs(manifest.verdict, CompletionVerdict.VERIFIED)
        task = self.store.fetch_task("task:1")
        self.assertEqual(task["state"], TaskState.COMPLETED)
        self.assertIn("evidence:1", task["evidence_refs"])
        self.assertIn("artifact:commit", task["artifact_refs"])

        record = self.store.canonical_task("task:1")
        self.assertEqual(record["plan_ref"], "plan:1")
        self.assertEqual(record["context_manifest_ref"], "context:1")
        self.assertEqual(record["authority_state"], "ALLOWED")
        self.assertEqual(record["accountable_identity"], "BRO")

    def test_the_task_context_is_the_assignment_context(self) -> None:
        binding = self.open()
        self.assertEqual(self.store.fetch_task("task:1")["context_manifest_ref"], "context:1")
        self.assertEqual(binding.context_manifest_ref, "context:1")

    # -------------------------------------------------------------- evidence

    def test_missing_evidence_blocks_completion(self) -> None:
        binding = self.open()
        self.run_to_settled(binding)
        manifest = self.supervisor.complete(
            binding, outcome_statement="claimed", required_criteria=("documentation updated",), now=T2,
        )
        self.assertIs(manifest.verdict, CompletionVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(manifest.criteria_unsatisfied, ("documentation updated",))
        task = self.store.fetch_task("task:1")
        self.assertEqual(task["state"], TaskState.BLOCKED)
        self.assertEqual(task["blocker_ref"], manifest.manifest_id)

    def test_stale_evidence_cannot_satisfy_completion(self) -> None:
        binding = self.open()
        self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                adapter=confirmed, now=T1)
        self.supervisor.settle_assignment(
            binding, result_state=AssignmentState.SUCCEEDED, output_ref="artifact:commit",
            evidence=(evidence(freshness=EvidenceFreshness.STALE),), now=T2,
        )
        manifest = self.supervisor.complete(binding, outcome_statement="claimed",
                                            required_criteria=("tests pass",), now=T2)
        self.assertIs(manifest.verdict, CompletionVerdict.INSUFFICIENT_EVIDENCE)

    def test_evidence_from_another_boundary_is_refused(self) -> None:
        binding = self.open()
        self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                adapter=confirmed, now=T1)
        foreign = evidence(scope=evidence_scope("project:OTHER", "task:1"))
        with self.assertRaisesRegex(BoundaryViolation, "scoped to"):
            self.supervisor.settle_assignment(binding, result_state=AssignmentState.SUCCEEDED,
                                              output_ref="artifact:commit", evidence=(foreign,), now=T2)

    # ------------------------------------------------------------- authority

    def test_authority_mismatch_blocks_execution(self) -> None:
        binding = self.open()
        with self.assertRaisesRegex(ActionRejected, "target mismatch"):
            self.supervisor.execute(binding, action(action_request_id="action:x", target="repo:OTHER"),
                                    executor="github", interface_version="1", adapter=confirmed, now=T1)
        self.assertIsNone(self.supervisor.actions.latest_attempt("action:x"))

    def test_expired_authority_blocks_execution(self) -> None:
        # The lease is still live, so the refusal is the authority's own expiry.
        binding = self.open(envelope=envelope(expires_at=T0))
        with self.assertRaisesRegex(ActionRejected, "expired"):
            self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                    adapter=confirmed, now=T1)
        self.assertIsNone(self.supervisor.actions.latest_attempt("action:1"))

    def test_revoked_authority_blocks_execution(self) -> None:
        binding = self.open(envelope=envelope(revocation_ref="revocation:1"))
        with self.assertRaisesRegex(ActionRejected, "revoked"):
            self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                    adapter=confirmed, now=T1)

    def test_denied_authority_never_reaches_execution(self) -> None:
        with self.assertRaisesRegex(BoundaryViolation, "not ALLOWED"):
            self.open(envelope=envelope(decision="DENIED"))
        task = self.store.fetch_task("task:1")
        self.assertEqual(task["state"], TaskState.BLOCKED)
        self.assertEqual(task["authority_state"], "DENIED")

    def test_approval_required_authority_never_reaches_execution(self) -> None:
        with self.assertRaisesRegex(BoundaryViolation, "not ALLOWED"):
            self.open(envelope=envelope(decision="APPROVAL_REQUIRED"))
        self.assertEqual(self.store.fetch_task("task:1")["authority_state"], "APPROVAL_REQUIRED")

    def test_authority_decision_is_recorded_for_every_action(self) -> None:
        binding = self.open()
        self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                adapter=confirmed, now=T1)
        decisions = self.supervisor.actions.authority.decisions("action:1")
        self.assertEqual([row["decision"] for row in decisions], ["ALLOW"])

    # -------------------------------------------------------------- boundary

    def test_project_boundary_mismatch_on_the_request_fails_closed(self) -> None:
        binding = self.open()
        with self.assertRaisesRegex(BoundaryViolation, "crosses the assignment project boundary"):
            self.supervisor.execute(binding, action(project_boundary="project:OTHER"), executor="github",
                                    interface_version="1", adapter=confirmed, now=T1)

    def test_missing_project_boundary_on_the_request_fails_closed(self) -> None:
        binding = self.open()
        with self.assertRaisesRegex(BoundaryViolation, "crosses the assignment project boundary"):
            self.supervisor.execute(binding, action(project_boundary=None), executor="github",
                                    interface_version="1", adapter=confirmed, now=T1)

    def test_envelope_without_the_boundary_token_cannot_open_a_flow(self) -> None:
        ungranted = envelope(allowed_scope=("operation:write", "target:repo:BRO", "task:1"))
        with self.assertRaisesRegex(BoundaryViolation, "does not grant the project boundary project:BRO"):
            self.open(envelope=ungranted)

    def test_boundary_token_is_normalised_once_end_to_end(self) -> None:
        binding = self.open(assignment=assignment(project_boundary="BRO"))
        self.assertEqual(binding.project_boundary, "BRO")
        self.supervisor.execute(binding, action(project_boundary="BRO"), executor="github",
                                interface_version="1", adapter=confirmed, now=T1)
        self.assertEqual(self.supervisor.actions.get_request("action:1")["state"], "RESULT_RECEIVED")
        stored = json.loads(self.supervisor.actions.get_request("action:1")["body"])
        self.assertEqual(stored["project_boundary"], "BRO")

    def test_context_drift_fails_closed(self) -> None:
        binding = self.open()
        drifted = FlowBinding(binding.task_id, binding.task_revision, binding.assignment_id, binding.lease,
                              binding.project_boundary, "context:other", binding.authority_envelope_ref,
                              binding.correlation_ref)
        with self.assertRaisesRegex(BoundaryViolation, "context manifest no longer matches"):
            self.supervisor.execute(drifted, action(), executor="github", interface_version="1",
                                    adapter=confirmed, now=T1)

    # ------------------------------------------------------------------ tools

    def test_adapter_outside_the_assignment_tool_grant_fails_closed(self) -> None:
        binding = self.open()
        with self.assertRaisesRegex(BoundaryViolation, "outside the assignment tool grant"):
            self.supervisor.execute(binding, action(adapter_id="shell"), executor="shell",
                                    interface_version="1", adapter=confirmed, now=T1)

    def test_target_outside_allowed_scope_fails_closed_separately_from_tools(self) -> None:
        narrow = envelope(allowed_scope=("operation:write", "task:1", "project:BRO"))
        binding = self.open(envelope=narrow)
        with self.assertRaisesRegex(ActionRejected, "allowed scope is insufficient"):
            self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                    adapter=confirmed, now=T1)

    def test_delegated_tools_cannot_exceed_the_envelope(self) -> None:
        with self.assertRaisesRegex(BoundaryViolation, "delegated tools exceed"):
            self.open(assignment=assignment(allowed_tools=("github", "shell")))

    # ------------------------------------------------------------- concurrency

    def test_stale_fencing_token_cannot_execute(self) -> None:
        binding = self.open(now=T0)
        self.supervisor.assignments.expire_leases("2026-09-01T00:10:00Z")
        self.supervisor.assignments.claim("assignment:1", "worker:2", "2026-09-01T00:10:01Z")
        with self.assertRaises(StaleWorkerResult):
            self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                    adapter=confirmed, now="2026-09-01T00:10:02Z")

    def test_stale_fencing_token_cannot_settle(self) -> None:
        binding = self.open(now=T0)
        self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                adapter=confirmed, now=T1)
        self.supervisor.assignments.expire_leases("2026-09-01T00:10:00Z")
        self.supervisor.assignments.claim("assignment:1", "worker:2", "2026-09-01T00:10:01Z")
        with self.assertRaises(StaleWorkerResult):
            self.supervisor.settle_assignment(binding, result_state=AssignmentState.SUCCEEDED,
                                              output_ref="artifact:commit", evidence=(evidence(),),
                                              now="2026-09-01T00:10:02Z")

    def test_stale_task_revision_cannot_act(self) -> None:
        binding = self.open()
        task = self.store.fetch_task("task:1")
        self.supervisor.tasks.transition("task:1", TaskState.PAUSED, "user", "interrupted",
                                         task["revision"], resume_checkpoint_ref="checkpoint:1")
        with self.assertRaises(ConcurrencyConflict):
            self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                    adapter=confirmed, now=T1)

    def test_execution_requires_the_executing_state(self) -> None:
        binding = self.open()
        task = self.store.fetch_task("task:1")
        paused = self.supervisor.tasks.transition("task:1", TaskState.PAUSED, "user", "interrupted",
                                                  task["revision"], resume_checkpoint_ref="checkpoint:1")
        with self.assertRaisesRegex(SupervisionRejected, "not EXECUTING"):
            self.supervisor.execute(binding.with_revision(paused["revision"]), action(), executor="github",
                                    interface_version="1", adapter=confirmed, now=T1)

    def test_terminal_task_state_is_immutable(self) -> None:
        binding = self.open()
        self.run_to_settled(binding)
        self.supervisor.complete(binding, outcome_statement="done", required_criteria=("tests pass",), now=T2)
        completed = self.store.fetch_task("task:1")
        with self.assertRaisesRegex(InvalidTransition, "terminal"):
            self.supervisor.tasks.transition("task:1", TaskState.EXECUTING, "worker", "reopen",
                                             completed["revision"])

    # ------------------------------------------------------------ unknown effect

    def test_timeout_blocks_completion_and_unsafe_retry(self) -> None:
        binding = self.open()
        attempt = self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                          adapter=times_out, now=T1)
        self.assertEqual(attempt["status"], "TIMED_OUT")
        self.assertEqual(attempt["effect_state"], EffectState.UNKNOWN)
        with self.assertRaisesRegex(RetryBlocked, "reconciled"):
            self.supervisor.actions.prepare_retry("action:1")
        self.supervisor.settle_assignment(binding, result_state=AssignmentState.FAILED,
                                          output_ref=None, evidence=(), now=T2)
        manifest = self.supervisor.complete(binding, outcome_statement="unclear",
                                            required_criteria=("tests pass",), now=T2)
        self.assertIs(manifest.verdict, CompletionVerdict.EFFECT_UNRECONCILED)
        self.assertEqual(self.store.fetch_task("task:1")["state"], TaskState.BLOCKED)

    def test_reconciliation_enables_the_correct_next_transition(self) -> None:
        binding = self.open()
        self.supervisor.execute(binding, action(), executor="github", interface_version="1",
                                adapter=times_out, now=T1)
        step = self.supervisor.resume("task:1")
        self.assertIs(step.action, NextAction.RECONCILE_EFFECT)

        self.supervisor.reconcile(binding, "action:1", EffectState.CONFIRMED,
                                  evidence("evidence:reality", criterion="effect confirmed"), now=T1)
        self.assertIs(self.supervisor.resume("task:1").action, NextAction.SETTLE_ASSIGNMENT)

        self.supervisor.settle_assignment(binding, result_state=AssignmentState.SUCCEEDED,
                                          output_ref="artifact:commit", evidence=(evidence(),), now=T2)
        self.assertIs(self.supervisor.resume("task:1").action, NextAction.EVALUATE_COMPLETION)

        manifest = self.supervisor.complete(binding, outcome_statement="the effect landed",
                                            required_criteria=("tests pass", "effect confirmed"), now=T2)
        self.assertIs(manifest.verdict, CompletionVerdict.VERIFIED)
        self.assertEqual(self.store.fetch_task("task:1")["state"], TaskState.COMPLETED)
        self.assertIs(self.supervisor.resume("task:1").action, NextAction.NONE)

    # ------------------------------------------------------------------ partial

    def test_partial_result_cannot_appear_completed(self) -> None:
        binding = self.open()
        self.run_to_settled(binding, state=AssignmentState.PARTIAL, limitations=("integration untested",))
        manifest = self.supervisor.complete(binding, outcome_statement="most of it",
                                            required_criteria=("tests pass",), now=T2)
        self.assertIs(manifest.verdict, CompletionVerdict.PARTIAL)
        self.assertEqual(manifest.exclusions, ("integration untested",))
        task = self.store.fetch_task("task:1")
        self.assertNotEqual(task["state"], TaskState.COMPLETED)
        self.assertEqual(task["excluded_scope"], ["integration untested"])

    # ------------------------------------------------------------------- events

    def test_events_preserve_an_end_to_end_causal_trace(self) -> None:
        binding = self.open()
        self.run_to_settled(binding)
        self.supervisor.complete(binding, outcome_statement="done", required_criteria=("tests pass",), now=T2)

        events = self.store.events("task:1")
        types = [event["event_type"] for event in events]
        for expected in ("task.received", "task.planning", "task.authorizing", "assignment.leased",
                         "task.executing", "action.proposed", "action.authorized", "action.attempted",
                         "assignment.settled", "completion.evaluated", "task.verifying", "task.completed"):
            self.assertIn(expected, types)

        self.assertTrue(all(event["correlation_ref"] == "task:1" for event in events))
        by_id = {event["event_id"]: event for event in events}
        proposed = next(e for e in events if e["event_type"] == "action.proposed")
        authorized = next(e for e in events if e["event_type"] == "action.authorized")
        attempted = next(e for e in events if e["event_type"] == "action.attempted")
        self.assertEqual(authorized["causal_ref"], proposed["event_id"])
        self.assertEqual(attempted["causal_ref"], authorized["event_id"])
        self.assertIn(attempted["causal_ref"], by_id)

    def test_a_denied_action_is_recorded_in_the_trace(self) -> None:
        binding = self.open()
        with self.assertRaises(ActionRejected):
            self.supervisor.execute(binding, action(action_request_id="action:x", target="repo:OTHER"),
                                    executor="github", interface_version="1", adapter=confirmed, now=T1)
        denied = [e for e in self.store.events("task:1") if e["event_type"] == "action.denied"]
        self.assertEqual(len(denied), 1)
        self.assertIn("target mismatch", denied[0]["reason"])


class CrashRecoveryTests(unittest.TestCase):
    def test_restart_reconstructs_the_next_step_without_replaying_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.db"
            store = SQLiteTaskStore(path)
            supervisor = TaskSupervisor(store)
            binding = supervisor.open_flow(
                task_id="task:1", goal_ref="goal:1", plan_ref="plan:1", assignment=assignment(),
                envelope=envelope(), worker_id="worker:1", now=T0,
            )
            supervisor.execute(binding, action(), executor="github", interface_version="1",
                               adapter=times_out, now=T1)
            attempts_before = store.connection.execute("SELECT count(*) FROM action_attempts").fetchone()[0]
            store.close()

            reopened = SQLiteTaskStore(path)
            try:
                resumed = TaskSupervisor(reopened)
                step = resumed.resume("task:1")
                self.assertIs(step.action, NextAction.RECONCILE_EFFECT)
                self.assertEqual(step.action_request_id, "action:1")
                self.assertEqual(step.task_state, TaskState.EXECUTING)
                self.assertIn("before any retry", step.reason)

                attempts_after = reopened.connection.execute("SELECT count(*) FROM action_attempts").fetchone()[0]
                self.assertEqual(attempts_after, attempts_before)
                self.assertEqual(reopened.fetch_task("task:1")["revision"], binding.task_revision)

                # The durable trace survived, and resume() added nothing to it.
                restored = reopened.events("task:1")
                self.assertIn("action.attempted", [event["event_type"] for event in restored])
                resumed.resume("task:1")
                self.assertEqual(len(reopened.events("task:1")), len(restored))
            finally:
                reopened.close()

    def test_resume_reports_a_terminal_task_and_proposes_nothing(self) -> None:
        store = SQLiteTaskStore()
        try:
            supervisor = TaskSupervisor(store)
            binding = supervisor.open_flow(
                task_id="task:1", goal_ref="goal:1", plan_ref="plan:1", assignment=assignment(),
                envelope=envelope(), worker_id="worker:1", now=T0,
            )
            supervisor.execute(binding, action(), executor="github", interface_version="1",
                               adapter=confirmed, now=T1)
            supervisor.settle_assignment(binding, result_state=AssignmentState.SUCCEEDED,
                                         output_ref="artifact:commit", evidence=(evidence(),), now=T2)
            supervisor.complete(binding, outcome_statement="done", required_criteria=("tests pass",), now=T2)
            step = supervisor.resume("task:1")
            self.assertIs(step.action, NextAction.NONE)
            self.assertIn("terminal", step.reason)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
