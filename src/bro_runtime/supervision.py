"""NERVOUS SYSTEM supervision: the end-to-end governed runtime slice.

Owner: NERVOUS SYSTEM. Coordination, specialist-assignment sequencing and
runtime-event progression are its declared responsibilities, and this module is
its controller surface.

It introduces no new domain record. Task state stays in `task_runtime`,
assignment and lease state in `orchestration`, execution truth in
`action_runtime`, and every authority decision, Evidence record and completion
verdict in `immune`. The supervisor sequences those owners and enforces the
cross-owner invariants none of them can see alone: that the worker acting still
holds the current fenced lease, that the Task revision bound at the start is
still current, that the assignment has not drifted from the Task's canonical
context, and that nothing crosses the project boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Iterable

from .action_runtime import ActionRequest, ActionRuntime, ActionState, AdapterResult, EffectState
from .immune import (
    AUTHORITY_DECISION_TO_TASK_STATE,
    ENVELOPE_DECISION_TO_AUTHORITY,
    AuthorityDecision,
    AuthorityEnvelope,
    CompletionManifest,
    EffectRecord,
    Evidence,
    EvidenceLedger,
    evidence_scope,
    normalize_boundary_scope,
)
from .orchestration import AssignmentState, LeaseGrant, SpecialistAssignment, Supervisor
from .task_runtime import (
    TERMINAL_STATES,
    ConcurrencyConflict,
    SQLiteTaskStore,
    TaskRuntime,
    TaskState,
    utc_now,
)


class SupervisionRejected(Exception):
    pass


class BoundaryViolation(SupervisionRejected):
    """A project, context, tool, or authority boundary was crossed."""


class NextAction(StrEnum):
    CLAIM_ASSIGNMENT = "CLAIM_ASSIGNMENT"
    EXECUTE_ACTION = "EXECUTE_ACTION"
    RECONCILE_EFFECT = "RECONCILE_EFFECT"
    SETTLE_ASSIGNMENT = "SETTLE_ASSIGNMENT"
    EVALUATE_COMPLETION = "EVALUATE_COMPLETION"
    COMPLETE_TASK = "COMPLETE_TASK"
    NONE = "NONE"


@dataclass(frozen=True)
class FlowBinding:
    """What this flow is bound to. Every field is a reference to another owner's state."""

    task_id: str
    task_revision: int
    assignment_id: str
    lease: LeaseGrant
    project_boundary: str
    context_manifest_ref: str
    authority_envelope_ref: str
    correlation_ref: str

    def with_revision(self, revision: int) -> "FlowBinding":
        return FlowBinding(self.task_id, revision, self.assignment_id, self.lease, self.project_boundary,
                           self.context_manifest_ref, self.authority_envelope_ref, self.correlation_ref)


@dataclass(frozen=True)
class NextStep:
    task_state: str
    action: NextAction
    reason: str
    action_request_id: str | None = None
    assignment_id: str | None = None


class TaskSupervisor:
    """The NERVOUS SYSTEM controller for one durable runtime store."""

    def __init__(self, store: SQLiteTaskStore, *, verifier: str = "IMMUNE_SYSTEM") -> None:
        self.store = store
        self.tasks = TaskRuntime(store)
        self.assignments = Supervisor(store.connection)
        self.actions = ActionRuntime(store.connection)
        self.evidence = EvidenceLedger(store.connection)
        self.verifier = verifier

    def open_flow(
        self,
        *,
        task_id: str,
        goal_ref: str,
        plan_ref: str,
        assignment: SpecialistAssignment,
        envelope: AuthorityEnvelope,
        worker_id: str,
        plan_revision: int = 1,
        actor: str = "BRO",
        now: str | None = None,
        lease_seconds: int = 30,
    ) -> FlowBinding:
        moment = now or utc_now()
        self._require_bindable(task_id, assignment, envelope)
        task = self.tasks.create_task(task_id, goal_ref, actor, "intent received", correlation_ref=task_id)
        for state, reason in ((TaskState.INTERPRETING, "framing the required outcome"),(TaskState.READY, "no blocker prevents planning")):
            task = self.tasks.transition(task_id, state, actor, reason, task["revision"], correlation_ref=task_id)
        task = self.tasks.transition(task_id, TaskState.PLANNING, actor, "execution route formed", task["revision"], correlation_ref=task_id, plan_ref=plan_ref, plan_revision=plan_revision)
        decision = ENVELOPE_DECISION_TO_AUTHORITY.get(envelope.decision, AuthorityDecision.DENY)
        task = self.tasks.transition(task_id, TaskState.AUTHORIZING, actor, "resolving authority for the planned work", task["revision"], correlation_ref=task_id, context_manifest_ref=assignment.context_manifest_ref, authority_state=AUTHORITY_DECISION_TO_TASK_STATE[decision])
        self.actions.register_authority(envelope)
        if decision is not AuthorityDecision.ALLOW:
            self.tasks.transition(task_id, TaskState.BLOCKED, self.verifier, f"authority state {AUTHORITY_DECISION_TO_TASK_STATE[decision]}: {envelope.reason}", task["revision"], correlation_ref=task_id, blocker_ref=envelope.envelope_id)
            raise BoundaryViolation(f"authority envelope is not ALLOWED: {envelope.decision}")
        self.assignments.create_assignment(assignment, actor, moment)
        lease = self.assignments.claim(assignment.assignment_id, worker_id, moment, lease_seconds)
        task = self.tasks.transition(task_id, TaskState.EXECUTING, actor, "authorized work is progressing", task["revision"], correlation_ref=task_id, active_step_ref=assignment.step_ref)
        self.tasks.record_event(task_id, "assignment.leased", worker_id, "worker leased a bounded assignment", correlation_ref=task_id, payload={"assignment_id": assignment.assignment_id, "fencing_token": lease.fencing_token, "project_boundary": assignment.project_boundary})
        return FlowBinding(task_id=task_id, task_revision=task["revision"], assignment_id=assignment.assignment_id, lease=lease, project_boundary=assignment.project_boundary, context_manifest_ref=assignment.context_manifest_ref, authority_envelope_ref=envelope.envelope_id, correlation_ref=task_id)

    def execute(
        self,
        binding: FlowBinding,
        request: ActionRequest,
        *,
        executor: str,
        interface_version: str,
        adapter: Callable[[dict], AdapterResult],
        now: str | None = None,
    ) -> dict:
        """Propose, authorize, and dispatch one action inside the bound flow.

        The authority envelope is re-evaluated by HANDS immediately before the
        adapter call, so queue/lease delay cannot turn stale authority into an effect.
        """
        moment = now or utc_now()
        self._require_current(binding, moment)
        self._require_request_bound(binding, request)
        envelope = self.actions.authority_envelope(binding.authority_envelope_ref)
        self.actions.propose(request)
        proposed = self.tasks.record_event(binding.task_id, "action.proposed", executor, request.intended_effect, correlation_ref=binding.correlation_ref, payload={"action_request_id": request.action_request_id, "operation": request.operation, "target": request.target, "adapter_id": request.adapter_id})
        try:
            self.actions.authorize(request.action_request_id, envelope, moment)
        except Exception as exc:
            self.tasks.record_event(binding.task_id, "action.denied", self.verifier, str(exc), correlation_ref=binding.correlation_ref, causal_ref=proposed, payload={"action_request_id": request.action_request_id})
            raise
        authorized = self.tasks.record_event(binding.task_id, "action.authorized", self.verifier, envelope.reason, correlation_ref=binding.correlation_ref, causal_ref=proposed, payload={"action_request_id": request.action_request_id, "envelope_id": envelope.envelope_id, "envelope_version": envelope.version})
        attempt = self.actions.dispatch(request.action_request_id, executor, interface_version, adapter, envelope=envelope, now=moment)
        self.tasks.record_event(binding.task_id, "action.attempted", executor, f"attempt {attempt['status']}", correlation_ref=binding.correlation_ref, causal_ref=authorized, payload={"action_request_id": request.action_request_id, "attempt_id": attempt["attempt_id"], "status": attempt["status"], "effect_state": attempt["effect_state"]})
        return attempt

    def reconcile(self, binding: FlowBinding, request_id: str, effect_state: EffectState, evidence: Evidence, *, now: str | None = None) -> dict:
        """Resolve an effect only when the request belongs to this exact live flow."""
        moment = now or utc_now()
        self._require_current(binding, moment)
        self._require_existing_request_bound(binding, request_id)
        self._require_evidence_scope(binding, (evidence,))
        self.evidence.record(evidence)
        attempt = self.actions.reconcile(request_id, effect_state, evidence.evidence_id)
        self.tasks.record_event(binding.task_id, "action.effect_reconciled", self.verifier, f"effect resolved to {effect_state}", correlation_ref=binding.correlation_ref, payload={"action_request_id": request_id, "effect_state": str(effect_state), "evidence_id": evidence.evidence_id, "command_replayed": False})
        return attempt

    def settle_assignment(self, binding: FlowBinding, *, result_state: AssignmentState, output_ref: str | None, evidence: Iterable[Evidence] = (), limitations: Iterable[str] = (), now: str | None = None) -> dict:
        moment = now or utc_now()
        self._require_current(binding, moment)
        items = tuple(evidence)
        self._require_evidence_scope(binding, items)
        for item in items:
            self.evidence.record(item)
        refs = tuple(item.evidence_id for item in items)
        result = self.assignments.submit_result(binding.lease, result_state, output_ref, refs, tuple(limitations), moment)
        self.tasks.record_event(binding.task_id, "assignment.settled", binding.lease.worker_id, f"worker reported {result_state}", correlation_ref=binding.correlation_ref, payload={"assignment_id": binding.assignment_id, "result_state": str(result_state), "result_id": result["result_id"], "evidence_refs": list(refs)})
        return result

    def complete(self, binding: FlowBinding, *, outcome_statement: str, required_criteria: Iterable[str], artifact_refs: Iterable[str] = (), actor: str = "BRO", now: str | None = None) -> CompletionManifest:
        moment = now or utc_now()
        task = self.store.fetch_task(binding.task_id)
        if task["revision"] != binding.task_revision:
            raise ConcurrencyConflict(f"expected revision {binding.task_revision}, found {task['revision']}")
        assignment = self.assignments.get_assignment(binding.assignment_id)
        result = self.assignments.result(assignment["result_ref"]) if assignment["result_ref"] else None
        exclusions = tuple(json.loads(result["limitations"])) if result else ()
        produced = (result["output_ref"],) if result and result["output_ref"] else ()
        artifacts = tuple(dict.fromkeys((*produced, *artifact_refs)))
        manifest = self.evidence.evaluate_completion(task_ref=binding.task_id, task_revision=binding.task_revision, assignment_ref=binding.assignment_id, scope=self._scope(binding), required_criteria=required_criteria, assignment_result_state=assignment["state"], effects=self._effects(binding.task_id), artifact_refs=artifacts, outcome_exists=bool(result and result["output_ref"]), outcome_statement=outcome_statement, exclusions=exclusions, verifier=self.verifier, now=moment)
        self.tasks.record_event(binding.task_id, "completion.evaluated", self.verifier, manifest.reason, correlation_ref=binding.correlation_ref, payload={"manifest_id": manifest.manifest_id, "verdict": str(manifest.verdict), "criteria_unsatisfied": list(manifest.criteria_unsatisfied)})
        if not manifest.is_verified():
            self.tasks.transition(binding.task_id, TaskState.BLOCKED, self.verifier, f"completion gate {manifest.verdict}: {manifest.reason}", binding.task_revision, correlation_ref=binding.correlation_ref, blocker_ref=manifest.manifest_id, excluded_scope=manifest.exclusions, artifact_refs=manifest.artifact_refs)
            return manifest
        verifying = self.tasks.transition(binding.task_id, TaskState.VERIFYING, actor, "evaluating evidence against completion criteria", binding.task_revision, correlation_ref=binding.correlation_ref)
        self.tasks.transition(binding.task_id, TaskState.COMPLETED, self.verifier, manifest.reason, verifying["revision"], correlation_ref=binding.correlation_ref, completion=manifest.to_completion_evidence(), evidence_refs=manifest.evidence_refs, artifact_refs=manifest.artifact_refs, payload={"manifest_id": manifest.manifest_id})
        return manifest

    def resume(self, task_id: str) -> NextStep:
        task = self.store.fetch_task(task_id)
        state = TaskState(task["state"])
        if state in TERMINAL_STATES:
            return NextStep(state, NextAction.NONE, f"task is terminal in {state}")
        assignments = self.assignments.assignments_for_task(task_id)
        if not assignments:
            return NextStep(state, NextAction.CLAIM_ASSIGNMENT, "no specialist assignment exists for this task")
        assignment = assignments[-1]
        for request in self.actions.requests_for_task(task_id):
            effect = self._request_effect(request)
            if effect in {EffectState.UNKNOWN, EffectState.POSSIBLE}:
                return NextStep(state, NextAction.RECONCILE_EFFECT, f"action effect is {effect}; reconcile against reality before any retry", request["action_request_id"], assignment["assignment_id"])
        if assignment["state"] in {AssignmentState.READY, AssignmentState.RECOVERING}:
            return NextStep(state, NextAction.CLAIM_ASSIGNMENT, f"assignment is {assignment['state']} and needs a fresh fenced lease", None, assignment["assignment_id"])
        if assignment["state"] == AssignmentState.LEASED:
            executed = [r for r in self.actions.requests_for_task(task_id) if r["state"] in {ActionState.RESULT_RECEIVED, ActionState.EFFECT_RECONCILED, ActionState.VERIFIED}]
            action = NextAction.SETTLE_ASSIGNMENT if executed else NextAction.EXECUTE_ACTION
            reason = "execution truth exists; settle the assignment" if executed else "the lease is held and no action has produced a result"
            return NextStep(state, action, reason, None, assignment["assignment_id"])
        manifest = self.evidence.latest_manifest(task_id)
        if manifest is None:
            return NextStep(state, NextAction.EVALUATE_COMPLETION, "the assignment is settled and the completion gate has not run", None, assignment["assignment_id"])
        if manifest["verdict"] == "VERIFIED":
            return NextStep(state, NextAction.COMPLETE_TASK, "a verified completion manifest exists and the task is not yet COMPLETED", None, assignment["assignment_id"])
        return NextStep(state, NextAction.NONE, f"completion gate returned {manifest['verdict']}; a new authorized decision is required", None, assignment["assignment_id"])

    def _scope(self, binding: FlowBinding) -> str:
        return evidence_scope(binding.project_boundary, binding.task_id)

    def _require_bindable(self, task_id: str, assignment: SpecialistAssignment, envelope: AuthorityEnvelope) -> None:
        if assignment.task_ref != task_id:
            raise BoundaryViolation("the assignment names a different task")
        if envelope.task_ref != task_id:
            raise BoundaryViolation("the authority envelope is bound to a different task")
        if assignment.authority_envelope_ref != envelope.envelope_id:
            raise BoundaryViolation("the assignment references a different authority envelope")
        boundary = normalize_boundary_scope(assignment.project_boundary)
        if boundary not in set(envelope.allowed_scope):
            raise BoundaryViolation(f"the authority envelope does not grant the project boundary {boundary}")
        outside = set(assignment.allowed_tools) - set(envelope.tool_boundary)
        if outside:
            raise BoundaryViolation("delegated tools exceed the envelope tool boundary: " + ", ".join(sorted(outside)))

    def _require_current(self, binding: FlowBinding, now: str) -> None:
        task = self.store.fetch_task(binding.task_id)
        if task["revision"] != binding.task_revision:
            raise ConcurrencyConflict(f"expected revision {binding.task_revision}, found {task['revision']}")
        if TaskState(task["state"]) is not TaskState.EXECUTING:
            raise SupervisionRejected(f"the task is {task['state']}, not EXECUTING")
        if task["context_manifest_ref"] != binding.context_manifest_ref:
            raise BoundaryViolation("the task context manifest no longer matches the assignment")
        self.assignments.validate_lease(binding.lease, now)

    def _require_request_bound(self, binding: FlowBinding, request: ActionRequest) -> None:
        if request.task_ref != binding.task_id:
            raise BoundaryViolation("the action request names a different task")
        if request.assignment_ref != binding.assignment_id:
            raise BoundaryViolation("the action request is not bound to the leased assignment")
        if request.authority_envelope_ref != binding.authority_envelope_ref:
            raise BoundaryViolation("the action request cites a different authority envelope")
        if not request.project_boundary or normalize_boundary_scope(request.project_boundary) != normalize_boundary_scope(binding.project_boundary):
            raise BoundaryViolation("the action request crosses the assignment project boundary")
        if request.adapter_id not in binding.lease.allowed_tools:
            raise BoundaryViolation(f"adapter {request.adapter_id} is outside the assignment tool grant")

    def _require_existing_request_bound(self, binding: FlowBinding, request_id: str) -> None:
        request = self.actions.get_request(request_id)
        body = json.loads(request["body"])
        if request["task_ref"] != binding.task_id or body.get("task_ref") != binding.task_id:
            raise BoundaryViolation("the action request belongs to a different task")
        if body.get("assignment_ref") != binding.assignment_id:
            raise BoundaryViolation("the action request belongs to a different assignment")
        if body.get("authority_envelope_ref") != binding.authority_envelope_ref:
            raise BoundaryViolation("the action request belongs to a different authority envelope")
        project_boundary = body.get("project_boundary")
        if not project_boundary or normalize_boundary_scope(project_boundary) != normalize_boundary_scope(binding.project_boundary):
            raise BoundaryViolation("the action request belongs to a different project boundary")
        if body.get("adapter_id") not in binding.lease.allowed_tools:
            raise BoundaryViolation("the action request adapter is outside the current lease tool grant")

    def _require_evidence_scope(self, binding: FlowBinding, items: Iterable[Evidence]) -> None:
        scope = self._scope(binding)
        for item in items:
            if item.scope != scope:
                raise BoundaryViolation(f"evidence {item.evidence_id} is scoped to {item.scope}, not {scope}")

    def _request_effect(self, request: dict) -> EffectState:
        attempt = self.actions.latest_attempt(request["action_request_id"])
        if attempt is None:
            return EffectState.UNKNOWN if request["state"] == ActionState.DISPATCHED else EffectState.NONE
        return self.actions.effective_effect(attempt)

    def _effects(self, task_id: str) -> tuple[EffectRecord, ...]:
        return tuple(EffectRecord(request["action_request_id"], str(self._request_effect(request))) for request in self.actions.requests_for_task(task_id))
