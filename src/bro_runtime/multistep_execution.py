"""Governed continuation across dependency-ready Steps in one canonical Task."""
from __future__ import annotations

import json

from .action_runtime import ApprovalRequired
from .approval import ApprovalDecision
from .evidence_verification import EvidenceObservation
from .feet import RouteCheckpoint, RouteState
from .immune import (
    AUTHORITY_DECISION_TO_TASK_STATE,
    AuthorityDecision,
    AuthorityEnvelope,
    CompletionManifest,
    evidence_scope,
)
from .multistep import MultiStepRejected, PreparedPlan
from .multistep_runtime import ready_multistep
from .nervous_records import StepState
from .orchestration import AssignmentState, SpecialistAssignment
from .supervision import BoundaryViolation, FlowBinding
from .task_runtime import TaskState, utc_now


def _bound_assignment(prepared_step, envelope: AuthorityEnvelope) -> SpecialistAssignment:
    assignment = prepared_step.assignment
    if envelope.task_ref != assignment.task_ref:
        raise BoundaryViolation("authority envelope belongs to a different Task")
    if set(assignment.allowed_tools) - set(envelope.tool_boundary):
        raise BoundaryViolation("authority envelope does not grant the selected adapter")
    return SpecialistAssignment(**{**assignment.__dict__, "authority_envelope_ref": envelope.envelope_id})


def _fresh_continuation_verdict(kernel, assignment: SpecialistAssignment, envelope: AuthorityEnvelope, moment: str):
    """Use IMMUNE's canonical evaluator before a continuation may claim work.

    This admission check intentionally happens before the assignment lease and
    Task EXECUTING transition. HANDS will still perform its JIT action-level
    authority evaluation immediately before any external effect.
    """
    if len(assignment.allowed_tools) != 1:
        raise BoundaryViolation("continuation requires exactly one selected adapter")
    request = {
        "operation": envelope.operation,
        "target": envelope.target,
        "task_ref": assignment.task_ref,
        "environment": envelope.environment,
        "adapter_id": assignment.allowed_tools[0],
        "project_boundary": assignment.project_boundary,
        "risk_class": envelope.risk_class,
    }
    return kernel.supervisor.actions.authority.evaluate(
        request,
        envelope,
        moment,
        subject_ref=assignment.assignment_id,
    )


def open_multistep(kernel, prepared: PreparedPlan, envelope: AuthorityEnvelope, *, worker_id: str, step_key: str | None = None, now: str | None = None):
    ready = ready_multistep(kernel, prepared)
    if not ready:
        raise MultiStepRejected("multi-step plan has no READY Step")
    target = prepared.step(step_key) if step_key else ready[0]
    if target not in ready:
        raise MultiStepRejected("requested first Step is not dependency-ready")
    assignment = _bound_assignment(target, envelope)
    try:
        binding = kernel.supervisor.open_flow(
            task_id=prepared.task_ref,
            goal_ref=prepared.goal_ref,
            plan_ref=prepared.plan_ref,
            assignment=assignment,
            envelope=envelope,
            worker_id=worker_id,
            now=now,
        )
    except (ApprovalRequired, BoundaryViolation):
        task = kernel.task_store.fetch_task(prepared.task_ref)
        blocker = task.get("blocker_ref") or envelope.envelope_id
        kernel.nervous.transition_step(target.step_ref, StepState.BLOCKED)
        kernel.feet.append(
            RouteCheckpoint(
                prepared.route_id, 1, prepared.task_ref, prepared.plan_ref, target.step_ref,
                task["state"], None, (blocker,), blocker, None, None, RouteState.BLOCKED, utc_now(),
            )
        )
        raise
    kernel.nervous.transition_step(target.step_ref, StepState.ACTIVE)
    kernel.feet.append(
        RouteCheckpoint(
            prepared.route_id, 1, prepared.task_ref, prepared.plan_ref, target.step_ref,
            "EXECUTING", "NEXT_STEP", (), None, None, None, RouteState.ACTIVE, utc_now(),
        )
    )
    return binding


def settle_multistep(kernel, prepared: PreparedPlan, binding: FlowBinding, step_key: str, *, result_state: AssignmentState, output_ref: str | None, observations=(), limitations=(), now: str | None = None):
    target = prepared.step(step_key)
    if target.assignment.assignment_id != binding.assignment_id:
        raise MultiStepRejected("binding does not belong to the named Step")
    expected_scope = evidence_scope(target.assignment.project_boundary, prepared.task_ref)
    evidence = []
    for verifier_id, observation in observations:
        if not isinstance(observation, EvidenceObservation):
            raise MultiStepRejected("multistep settlement requires EvidenceObservation values")
        if observation.scope != expected_scope:
            raise MultiStepRejected("evidence observation crosses the prepared task boundary")
        evidence.append(kernel.evidence_verifiers.verify(verifier_id, observation, collected_at=now))
    result = kernel.supervisor.settle_assignment(
        binding,
        result_state=result_state,
        output_ref=output_ref,
        evidence=tuple(evidence),
        limitations=limitations,
        now=now,
    )
    state = {
        AssignmentState.SUCCEEDED: StepState.SUCCEEDED,
        AssignmentState.PARTIAL: StepState.PARTIAL,
        AssignmentState.FAILED: StepState.FAILED,
    }[AssignmentState(result_state)]
    kernel.nervous.transition_step(target.step_ref, state)
    ready_multistep(kernel, prepared)
    return result


def continue_multistep(kernel, prepared: PreparedPlan, binding: FlowBinding, next_key: str, envelope: AuthorityEnvelope, *, worker_id: str, now: str | None = None, actor: str = "BRO"):
    moment = now or utc_now()
    task = kernel.task_store.fetch_task(prepared.task_ref)
    if task["revision"] != binding.task_revision or task["state"] != TaskState.EXECUTING:
        raise MultiStepRejected("Task binding is stale or not EXECUTING")
    prior = kernel.supervisor.assignments.get_assignment(binding.assignment_id)
    if prior["state"] != AssignmentState.SUCCEEDED:
        raise MultiStepRejected("current Step must succeed before dependent continuation")
    target = prepared.step(next_key)
    if target not in ready_multistep(kernel, prepared):
        raise MultiStepRejected("next Step dependencies are not satisfied")
    assignment = _bound_assignment(target, envelope)

    planning = kernel.supervisor.tasks.transition(
        prepared.task_ref, TaskState.PLANNING, actor, "advancing to dependency-ready Step",
        task["revision"], correlation_ref=prepared.task_ref,
    )
    kernel.supervisor.actions.register_authority(envelope)
    verdict = _fresh_continuation_verdict(kernel, assignment, envelope, moment)
    authorizing = kernel.supervisor.tasks.transition(
        prepared.task_ref, TaskState.AUTHORIZING, actor, "fresh authority evaluated for next Step",
        planning["revision"], correlation_ref=prepared.task_ref,
        context_manifest_ref=prepared.context_manifest_ref,
        authority_state=AUTHORITY_DECISION_TO_TASK_STATE[verdict.decision],
    )
    kernel.supervisor.assignments.create_assignment(assignment, actor, moment)

    if verdict.decision is not AuthorityDecision.ALLOW:
        reason = "; ".join(verdict.reasons) or envelope.reason
        kernel.supervisor.tasks.transition(
            prepared.task_ref, TaskState.BLOCKED, kernel.supervisor.verifier,
            f"authority state {AUTHORITY_DECISION_TO_TASK_STATE[verdict.decision]}: {reason}",
            authorizing["revision"], correlation_ref=prepared.task_ref, blocker_ref=envelope.envelope_id,
        )
        kernel.nervous.transition_step(target.step_ref, StepState.BLOCKED)
        kernel.feet.block(prepared.route_id, authority_ref=envelope.envelope_id)
        if verdict.decision is AuthorityDecision.APPROVAL_REQUIRED:
            raise ApprovalRequired(f"task {prepared.task_ref} is waiting for Approval")
        raise BoundaryViolation(f"fresh continuation authority denied: {reason}")

    lease = kernel.supervisor.assignments.claim(assignment.assignment_id, worker_id, moment)
    executing = kernel.supervisor.tasks.transition(
        prepared.task_ref, TaskState.EXECUTING, actor, "dependency-ready Step is progressing",
        authorizing["revision"], correlation_ref=prepared.task_ref,
        active_step_ref=target.step_ref, blocker_ref=None,
    )
    kernel.nervous.transition_step(target.step_ref, StepState.ACTIVE)
    kernel.feet.move(
        prepared.route_id,
        current_step_ref=target.step_ref,
        current_location="EXECUTING",
        next_location="NEXT_STEP",
    )
    return FlowBinding(
        prepared.task_ref, executing["revision"], assignment.assignment_id, lease,
        assignment.project_boundary, assignment.context_manifest_ref,
        envelope.envelope_id, prepared.task_ref,
    )


def resume_multistep_with_approval(kernel, prepared: PreparedPlan, step_key: str, approval_id: str, worker_id: str, *, now: str | None = None, actor: str = "BRO"):
    moment = now or utc_now()
    task = kernel.task_store.fetch_task(prepared.task_ref)
    target = prepared.step(step_key)
    if task["state"] != TaskState.BLOCKED or task["authority_state"] != "APPROVAL_REQUIRED":
        raise BoundaryViolation("Task is not blocked on APPROVAL_REQUIRED authority")
    row = kernel.supervisor.assignments.get_assignment(target.assignment.assignment_id)
    if row["state"] != AssignmentState.READY:
        raise BoundaryViolation("approval resume requires the target assignment to remain READY")
    assignment = json.loads(row["body"])
    envelope = kernel.supervisor.actions.authority_envelope(assignment["authority_envelope_ref"])
    approval = kernel.supervisor.approvals.get(approval_id)
    body = json.loads(approval["body"])
    if approval["decision"] != ApprovalDecision.APPROVED or body["task_ref"] != prepared.task_ref:
        raise BoundaryViolation("Approval is not APPROVED for this Task")
    matched = kernel.supervisor.approvals.approved_for(
        task_ref=prepared.task_ref,
        action_request_ref=None,
        step_ref=target.step_ref,
        operation=envelope.operation,
        target=envelope.target,
        required_scope=envelope.allowed_scope,
        risk_class=envelope.risk_class,
        now=moment,
    )
    if matched is None or matched["approval_id"] != approval_id:
        raise BoundaryViolation("Approval does not satisfy this Task and Step")
    authorizing = kernel.supervisor.tasks.transition(
        prepared.task_ref, TaskState.AUTHORIZING, actor, "fresh Approval resolved next-Step authority",
        task["revision"], correlation_ref=prepared.task_ref, authority_state="ALLOWED",
        approval_refs=(approval_id,), blocker_ref=None,
    )
    lease = kernel.supervisor.assignments.claim(assignment["assignment_id"], worker_id, moment)
    executing = kernel.supervisor.tasks.transition(
        prepared.task_ref, TaskState.EXECUTING, actor, "approved dependency-ready Step is progressing",
        authorizing["revision"], correlation_ref=prepared.task_ref, active_step_ref=target.step_ref,
    )
    kernel.feet.resume(
        prepared.route_id,
        blocker_resolved=lambda ref: ref == envelope.envelope_id
        and kernel.task_store.fetch_task(prepared.task_ref)["authority_state"] == "ALLOWED",
    )
    kernel.feet.move(
        prepared.route_id,
        current_step_ref=target.step_ref,
        current_location="EXECUTING",
        next_location="NEXT_STEP",
    )
    kernel.nervous.transition_step(target.step_ref, StepState.ACTIVE)
    return FlowBinding(
        prepared.task_ref, executing["revision"], assignment["assignment_id"], lease,
        assignment["project_boundary"], assignment["context_manifest_ref"],
        envelope.envelope_id, prepared.task_ref,
    )


def complete_multistep(kernel, prepared: PreparedPlan, binding: FlowBinding, *, outcome_statement: str, required_criteria: tuple[str, ...], actor: str = "BRO", now: str | None = None) -> CompletionManifest:
    outputs = []
    for item in prepared.steps:
        try:
            row = kernel.supervisor.assignments.get_assignment(item.assignment.assignment_id)
        except Exception:
            continue
        if row.get("result_ref"):
            result = kernel.supervisor.assignments.result(row["result_ref"])
            if result and result.get("output_ref"):
                outputs.append(result["output_ref"])
    manifest = kernel.supervisor.complete(
        binding,
        outcome_statement=outcome_statement,
        required_criteria=required_criteria,
        artifact_refs=tuple(outputs),
        actor=actor,
        now=now,
    )
    if manifest.is_verified():
        kernel.feet.complete(prepared.route_id)
    elif kernel.feet.latest(prepared.route_id).state is not RouteState.BLOCKED:
        kernel.feet.block(prepared.route_id, integrity_ref=manifest.manifest_id)
    return manifest
