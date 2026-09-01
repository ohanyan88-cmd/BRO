"""Reference-closed NERVOUS SYSTEM entrypoint for governed flows."""
from __future__ import annotations

import json

from .action_runtime import ApprovalRequired
from .approval import ApprovalRegistry
from .governed_authority import GovernedAuthorityEvaluator
from .immune import AUTHORITY_DECISION_TO_TASK_STATE, ENVELOPE_DECISION_TO_AUTHORITY, AuthorityDecision
from .mind import SQLiteMindStore
from .nervous_records import NervousRecordStore
from .reference_integrity import ReferenceIntegrity
from .supervision import BoundaryViolation, FlowBinding, NextAction, NextStep, TaskSupervisor
from .task_runtime import TaskState, utc_now


class GovernedTaskSupervisor(TaskSupervisor):
    """Reference-closed supervisor with a recoverable Approval gate."""

    def __init__(self, store, *, mind_store: SQLiteMindStore, verifier: str = "IMMUNE_SYSTEM") -> None:
        super().__init__(store, verifier=verifier)
        self.mind_store = mind_store
        self.nervous_records = NervousRecordStore(store.connection)
        self.approvals = ApprovalRegistry(store.connection)
        self.actions.authority = GovernedAuthorityEvaluator(store.connection, self.approvals)
        self.reference_integrity = ReferenceIntegrity(
            mind=mind_store, nervous=self.nervous_records,
            approvals=self.approvals, evidence=self.evidence,
        )

    def open_flow(self, *, task_id, goal_ref, plan_ref, assignment, envelope, worker_id,
                  plan_revision=1, actor="BRO", now=None, lease_seconds=30):
        self.reference_integrity.require_flow(
            task_id=task_id, goal_ref=goal_ref, plan_ref=plan_ref, plan_revision=plan_revision,
            step_ref=assignment.step_ref, context_manifest_ref=assignment.context_manifest_ref,
            project_boundary=assignment.project_boundary,
        )
        if envelope.decision != "APPROVAL_REQUIRED":
            return super().open_flow(
                task_id=task_id, goal_ref=goal_ref, plan_ref=plan_ref, assignment=assignment,
                envelope=envelope, worker_id=worker_id, plan_revision=plan_revision,
                actor=actor, now=now, lease_seconds=lease_seconds,
            )

        moment = now or utc_now()
        self._require_bindable(task_id, assignment, envelope)
        task = self.tasks.create_task(task_id, goal_ref, actor, "intent received", correlation_ref=task_id)
        task = self.tasks.transition(task_id, TaskState.INTERPRETING, actor, "framing the required outcome", task["revision"], correlation_ref=task_id)
        task = self.tasks.transition(task_id, TaskState.READY, actor, "no blocker prevents planning", task["revision"], correlation_ref=task_id)
        task = self.tasks.transition(
            task_id, TaskState.PLANNING, actor, "execution route formed", task["revision"],
            correlation_ref=task_id, plan_ref=plan_ref, plan_revision=plan_revision,
        )
        decision = ENVELOPE_DECISION_TO_AUTHORITY[envelope.decision]
        task = self.tasks.transition(
            task_id, TaskState.AUTHORIZING, actor, "resolving authority for the planned work", task["revision"],
            correlation_ref=task_id, context_manifest_ref=assignment.context_manifest_ref,
            authority_state=AUTHORITY_DECISION_TO_TASK_STATE[decision],
        )
        self.actions.register_authority(envelope)
        self.assignments.create_assignment(assignment, actor, moment)
        self.tasks.transition(
            task_id, TaskState.BLOCKED, self.verifier,
            f"authority state APPROVAL_REQUIRED: {envelope.reason}", task["revision"],
            correlation_ref=task_id, blocker_ref=envelope.envelope_id,
        )
        raise ApprovalRequired(f"task {task_id} is waiting for Approval")

    def resume_with_approval(self, task_id: str, approval_id: str, worker_id: str, *,
                             now: str | None = None, lease_seconds: int = 30,
                             actor: str = "BRO") -> FlowBinding:
        moment = now or utc_now()
        task = self.store.fetch_task(task_id)
        if task["state"] != TaskState.BLOCKED or task["authority_state"] != "APPROVAL_REQUIRED":
            raise BoundaryViolation("Task is not blocked on APPROVAL_REQUIRED authority")
        assignments = self.assignments.assignments_for_task(task_id)
        if len(assignments) != 1:
            raise BoundaryViolation("approval resume requires exactly one pending assignment")
        assignment_row = assignments[0]
        if assignment_row["state"] != "READY":
            raise BoundaryViolation("approval resume requires the pending assignment to remain READY")
        assignment = json.loads(assignment_row["body"])
        envelope = self.actions.authority_envelope(assignment["authority_envelope_ref"])
        approval = self.approvals.get(approval_id)
        approval_body = json.loads(approval["body"])
        if approval["decision"] != "APPROVED" or approval_body["task_ref"] != task_id:
            raise BoundaryViolation("Approval is not an APPROVED record for this Task")
        matched = self.approvals.approved_for(
            task_ref=task_id, action_request_ref=None, step_ref=assignment["step_ref"],
            operation=envelope.operation, target=envelope.target,
            required_scope=envelope.allowed_scope, risk_class=envelope.risk_class, now=moment,
        )
        if matched is None or matched["approval_id"] != approval_id:
            raise BoundaryViolation("Approval does not satisfy this Task, Step, scope, target and risk")

        authorizing = self.tasks.transition(
            task_id, TaskState.AUTHORIZING, actor, "fresh Approval resolved the authority gate",
            task["revision"], correlation_ref=task_id, authority_state="ALLOWED",
            approval_refs=(approval_id,),
        )
        lease = self.assignments.claim(assignment["assignment_id"], worker_id, moment, lease_seconds)
        executing = self.tasks.transition(
            task_id, TaskState.EXECUTING, actor, "approved work is progressing",
            authorizing["revision"], correlation_ref=task_id, active_step_ref=assignment["step_ref"],
        )
        self.tasks.record_event(
            task_id, "approval.resumed", self.verifier, "Approval reopened the guarded execution path",
            correlation_ref=task_id,
            payload={"approval_id": approval_id, "assignment_id": assignment["assignment_id"],
                     "fencing_token": lease.fencing_token},
        )
        return FlowBinding(
            task_id=task_id, task_revision=executing["revision"], assignment_id=assignment["assignment_id"],
            lease=lease, project_boundary=assignment["project_boundary"],
            context_manifest_ref=assignment["context_manifest_ref"],
            authority_envelope_ref=envelope.envelope_id, correlation_ref=task_id,
        )

    def resume(self, task_id: str) -> NextStep:
        """Read-only recovery that recognizes the human Approval wait state."""
        task = self.store.fetch_task(task_id)
        if task["state"] == TaskState.BLOCKED and task["authority_state"] == "APPROVAL_REQUIRED":
            return NextStep(
                TaskState.BLOCKED,
                NextAction.NONE,
                "task is waiting for a fresh Approval; no assignment claim or command is safe yet",
            )
        return super().resume(task_id)

    def canonical_task(self, task_id: str) -> dict:
        task = self.store.canonical_task(task_id)
        self.reference_integrity.require_task_refs(task)
        return task
