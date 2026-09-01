"""Reference-closed NERVOUS SYSTEM entrypoint for governed flows."""
from __future__ import annotations

import json

from .action_runtime import ApprovalRequired
from .approval import ApprovalRegistry
from .evidence_verification import is_trusted_evidence
from .governed_authority import GovernedAuthorityEvaluator
from .immune import (
    AUTHORITY_DECISION_TO_TASK_STATE,
    ENVELOPE_DECISION_TO_AUTHORITY,
    AuthorityDecision,
    EvidenceLedger,
)
from .mind import SQLiteMindStore
from .nervous_records import NervousRecordStore
from .reference_integrity import ReferenceIntegrity
from .supervision import BoundaryViolation, FlowBinding, NextAction, NextStep, TaskSupervisor
from .task_runtime import ConcurrencyConflict, TaskState, utc_now


class TrustedEvidenceLedger(EvidenceLedger):
    """Canonical IMMUNE ledger that refuses caller-controlled truth writes."""

    def record(self, evidence):
        if not is_trusted_evidence(evidence):
            raise BoundaryViolation(
                "untrusted evidence cannot enter the canonical ledger; use a registered evidence verifier"
            )
        return super().record(evidence)

    def evaluate_completion(self, *args, **kwargs):
        raise BoundaryViolation(
            "direct completion evaluation is disabled on the canonical ledger; use the governed supervisor"
        )

    def _evaluate_bound_completion(self, **kwargs):
        """Internal writer used only after GovernedTaskSupervisor validates the bound flow."""
        return super().evaluate_completion(**kwargs)


class GovernedTaskSupervisor(TaskSupervisor):
    """Reference-closed supervisor with recoverable Approval and evidence gates.

    Production callers must not inject arbitrary execution callables, self-minted
    Evidence, or completion verdicts. External effects enter through
    ProviderExecutionGateway; Evidence comes from registered trusted verifiers;
    completion manifests are minted only from a currently bound governed flow.
    """

    def __init__(self, store, *, mind_store: SQLiteMindStore, verifier: str = "IMMUNE_SYSTEM") -> None:
        super().__init__(store, verifier=verifier)
        self.evidence = TrustedEvidenceLedger(store.connection)
        self.mind_store = mind_store
        self.nervous_records = NervousRecordStore(store.connection)
        self.approvals = ApprovalRegistry(store.connection)
        self.actions.authority = GovernedAuthorityEvaluator(store.connection, self.approvals)
        self.reference_integrity = ReferenceIntegrity(
            mind=mind_store, nervous=self.nervous_records,
            approvals=self.approvals, evidence=self.evidence,
        )

    def execute(self, *args, **kwargs):
        """Reject raw callable execution on the canonical governed supervisor."""
        raise BoundaryViolation(
            "raw execution is disabled on GovernedTaskSupervisor; use the registered provider gateway"
        )

    def _execute_registered_provider(self, binding, request, *, executor, interface_version, adapter, now=None):
        """Internal gateway hook after provider identity/version has been resolved."""
        return super().execute(
            binding,
            request,
            executor=executor,
            interface_version=interface_version,
            adapter=adapter,
            now=now,
        )

    def reconcile(self, binding, request_id, effect_state, evidence, *, now=None):
        """Reject caller-minted Evidence on canonical effect reconciliation."""
        if not is_trusted_evidence(evidence):
            raise BoundaryViolation(
                "untrusted evidence is disabled on GovernedTaskSupervisor; use the registered evidence verifier"
            )
        return super().reconcile(binding, request_id, effect_state, evidence, now=now)

    def settle_assignment(self, binding, *, result_state, output_ref, evidence=(), limitations=(), now=None):
        """Reject caller-minted Evidence on canonical assignment settlement."""
        items = tuple(evidence)
        if any(not is_trusted_evidence(item) for item in items):
            raise BoundaryViolation(
                "untrusted evidence is disabled on GovernedTaskSupervisor; use the registered evidence verifier"
            )
        return super().settle_assignment(
            binding,
            result_state=result_state,
            output_ref=output_ref,
            evidence=items,
            limitations=limitations,
            now=now,
        )

    def complete(self, binding, *, outcome_statement, required_criteria, artifact_refs=(), actor="BRO", now=None):
        """Mint completion only from the currently bound canonical Task/Assignment truth."""
        moment = now or utc_now()
        task = self.store.fetch_task(binding.task_id)
        if task["revision"] != binding.task_revision:
            raise ConcurrencyConflict(f"expected revision {binding.task_revision}, found {task['revision']}")
        assignment = self.assignments.get_assignment(binding.assignment_id)
        if assignment["task_ref"] != binding.task_id:
            raise BoundaryViolation("completion assignment belongs to a different Task")
        result = self.assignments.result(assignment["result_ref"]) if assignment["result_ref"] else None
        exclusions = tuple(json.loads(result["limitations"])) if result else ()
        produced = (result["output_ref"],) if result and result["output_ref"] else ()
        artifacts = tuple(dict.fromkeys((*produced, *artifact_refs)))
        manifest = self.evidence._evaluate_bound_completion(
            task_ref=binding.task_id,
            task_revision=binding.task_revision,
            assignment_ref=binding.assignment_id,
            scope=self._scope(binding),
            required_criteria=required_criteria,
            assignment_result_state=assignment["state"],
            effects=self._effects(binding.task_id),
            artifact_refs=artifacts,
            outcome_exists=bool(result and result["output_ref"]),
            outcome_statement=outcome_statement,
            exclusions=exclusions,
            verifier=self.verifier,
            now=moment,
        )
        self.tasks.record_event(
            binding.task_id,
            "completion.evaluated",
            self.verifier,
            manifest.reason,
            correlation_ref=binding.correlation_ref,
            payload={
                "manifest_id": manifest.manifest_id,
                "verdict": str(manifest.verdict),
                "criteria_unsatisfied": list(manifest.criteria_unsatisfied),
            },
        )
        if not manifest.is_verified():
            self.tasks.transition(
                binding.task_id,
                TaskState.BLOCKED,
                self.verifier,
                f"completion gate {manifest.verdict}: {manifest.reason}",
                binding.task_revision,
                correlation_ref=binding.correlation_ref,
                blocker_ref=manifest.manifest_id,
                excluded_scope=manifest.exclusions,
                artifact_refs=manifest.artifact_refs,
            )
            return manifest
        verifying = self.tasks.transition(
            binding.task_id,
            TaskState.VERIFYING,
            actor,
            "evaluating evidence against completion criteria",
            binding.task_revision,
            correlation_ref=binding.correlation_ref,
        )
        self.tasks.transition(
            binding.task_id,
            TaskState.COMPLETED,
            self.verifier,
            manifest.reason,
            verifying["revision"],
            correlation_ref=binding.correlation_ref,
            completion=manifest.to_completion_evidence(),
            evidence_refs=manifest.evidence_refs,
            artifact_refs=manifest.artifact_refs,
            payload={"manifest_id": manifest.manifest_id},
        )
        return manifest

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
            approval_refs=(approval_id,), blocker_ref=None,
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
