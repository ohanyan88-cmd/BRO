"""Verified-observation-driven re-entry and replanning for canonical multi-step work.

PERCEPTION owns Observation, IMMUNE owns verification truth, MIND owns
Decision/Plan revision, NERVOUS owns Step state, and this module only composes
transitions between those owners. Caller-supplied freshness/trust flags never
become authority to mutate an executable Plan.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from .action_runtime import ApprovalRequired
from .evidence_verification import EvidenceObservation
from .feet import RouteState
from .immune import (
    AUTHORITY_DECISION_TO_TASK_STATE,
    AuthorityDecision,
    AuthorityEnvelope,
    EvidenceFreshness,
    EvidenceValidity,
    evidence_scope,
)
from .mind import KnowledgeState
from .multistep import MultiStepRejected, PreparedPlan, PreparedStep, StepRequest, validate_graph
from .multistep_execution import _fresh_continuation_verdict
from .nervous_records import StepState
from .orchestration import SpecialistAssignment
from .perception import Freshness, TrustState
from .supervision import BoundaryViolation, FlowBinding
from .task_runtime import TaskState, utc_now


@dataclass(frozen=True)
class ReplanResult:
    observation_ref: str
    evidence_ref: str
    prior_plan_revision: int
    plan_revision: int
    prepared: PreparedPlan


def _require_current_plan_and_context(kernel, prepared: PreparedPlan, task: dict):
    if task["plan_ref"] != prepared.plan_ref:
        raise MultiStepRejected("Task is bound to a different Plan")
    current_plan = kernel.mind_store.plan(prepared.plan_ref)
    if task.get("plan_revision") != current_plan.revision:
        raise MultiStepRejected("Task is not bound to the latest canonical Plan revision")
    if task.get("context_manifest_ref") != prepared.context_manifest_ref:
        raise MultiStepRejected("Task context binding differs from the prepared Plan context")
    context = kernel.nervous.context_manifest(prepared.context_manifest_ref)
    if context.task_ref != prepared.task_ref:
        raise MultiStepRejected("Context Manifest belongs to a different Task")
    for item in prepared.steps:
        step = kernel.nervous.step(item.step_ref)
        if step.task_ref != prepared.task_ref or step.plan_ref != prepared.plan_ref:
            raise MultiStepRejected("prepared Step crosses the canonical Task/Plan boundary")
        if step.state is not StepState.SUCCEEDED and step.plan_revision != current_plan.revision:
            raise MultiStepRejected("unfinished prepared Step belongs to a stale Plan revision")
    return current_plan, context


def replan_from_observation(
    kernel,
    prepared: PreparedPlan,
    *,
    verifier_id: str,
    observation: EvidenceObservation,
    replacements: tuple[StepRequest, ...],
    actor: str = "BRO",
    now: str | None = None,
) -> ReplanResult:
    """Replace unfinished work only after IMMUNE verifies current external reality.

    The caller may submit an EvidenceObservation, but cannot set canonical
    validity/freshness/trust. A registered verifier must mint VALID + CURRENT
    Evidence inside the exact Task boundary before PERCEPTION records a
    CONFIRMED Observation and MIND is allowed to revise the executable Plan.
    """
    task = kernel.task_store.fetch_task(prepared.task_ref)
    if task["state"] != TaskState.EXECUTING:
        raise MultiStepRejected("observation replan requires an EXECUTING Task")
    old_plan, context = _require_current_plan_and_context(kernel, prepared, task)

    expected_scope = evidence_scope(context.isolation_boundary, prepared.task_ref)
    if observation.scope != expected_scope:
        raise MultiStepRejected("replan observation crosses the prepared Task boundary")
    verified = kernel.evidence_verifiers.verify(verifier_id, observation, collected_at=now)
    if verified.validity is not EvidenceValidity.VALID or verified.freshness is not EvidenceFreshness.CURRENT:
        raise MultiStepRejected("automatic replan requires verifier-minted VALID CURRENT evidence")

    order = validate_graph(replacements)
    by_key = {item.key: item for item in replacements}
    resolved = {}
    for key in order:
        req = by_key[key]
        matches = kernel.skills.discover(operations=(req.operation,), domains=(req.domain,))
        if not matches:
            raise MultiStepRejected(f"no active capability matches replanned step={key!r}")
        cap = matches[0].capability
        if not cap.provider_ref:
            raise MultiStepRejected(f"replanned step {key!r} capability has no provider/adapter binding")
        resolved[key] = cap

    perception_observation = kernel.perception.observe(
        claim=verified.result,
        source=verified.source,
        provenance={**verified.provenance, "evidence_ref": verified.evidence_id, "verifier": verified.verifier},
        freshness=Freshness.CURRENT,
        trust_state=TrustState.CONFIRMED,
        scope=context.isolation_boundary,
        limitations=verified.limitations,
        raw_result_ref=verified.evidence_id,
        integrity={"verified_evidence_ref": verified.evidence_id, "verifier": verified.verifier},
        observed_at=verified.collected_at,
    )

    succeeded = []
    for item in prepared.steps:
        step = kernel.nervous.step(item.step_ref)
        if step.state is StepState.SUCCEEDED:
            succeeded.append(item)
        elif step.state in {StepState.PLANNED, StepState.READY}:
            kernel.nervous.transition_step(item.step_ref, StepState.CANCELLED)
        elif step.state in {StepState.ACTIVE, StepState.BLOCKED, StepState.PARTIAL, StepState.FAILED}:
            raise MultiStepRejected(f"cannot supersede Step {item.key!r} while it is {step.state}")

    next_revision = old_plan.revision + 1
    step_ids = {key: f"step:{uuid.uuid4()}" for key in order}
    created = {}
    for key in order:
        req = by_key[key]
        cap = resolved[key]
        deps = tuple(step_ids[d] for d in req.dependencies)
        created[key] = kernel.nervous.create_step(
            step_id=step_ids[key],
            task_ref=prepared.task_ref,
            plan_ref=prepared.plan_ref,
            plan_revision=next_revision,
            purpose=req.purpose,
            dependencies=deps,
            required_capabilities=(cap.capability_id,),
            expected_output=req.expected_output,
            authority_class=req.risk_class,
            verification_requirement=req.verification_requirement,
            retry_policy=req.retry_policy,
            state=StepState.READY if not deps else StepState.PLANNED,
        )

    decision = kernel.mind.decide(
        goal_ref=prepared.goal_ref,
        question="How should the active Plan change after verified current reality?",
        conclusion={
            "observation_ref": perception_observation.observation_id,
            "evidence_ref": verified.evidence_id,
            "replacement_steps": list(order),
        },
        rationale="IMMUNE-verified current reality supersedes the prior executable route.",
        authority_basis=task.get("authority_state") or "UNASSESSED",
        uncertainty=KnowledgeState.CONFIRMED,
        reversibility="REVERSIBLE",
        evidence_refs=(verified.evidence_id,),
    )
    new_refs = tuple(item.step_ref for item in succeeded) + tuple(step_ids[key] for key in order)
    plan = kernel.mind.replan(
        prepared.plan_ref,
        step_refs=new_refs,
        decision_ref=decision.decision_id,
        reason="Re-entered planning after verifier-confirmed current reality changed the executable route.",
    )
    kernel.supervisor.tasks.transition(
        prepared.task_ref,
        TaskState.PLANNING,
        actor,
        "verified current reality requires replanning",
        task["revision"],
        correlation_ref=prepared.task_ref,
        plan_ref=prepared.plan_ref,
        plan_revision=plan.revision,
        payload={
            "observation_ref": perception_observation.observation_id,
            "evidence_ref": verified.evidence_id,
            "prior_plan_revision": old_plan.revision,
        },
    )
    route = kernel.feet.latest(prepared.route_id)
    if route.state is not RouteState.ACTIVE:
        raise MultiStepRejected("observation replan requires an ACTIVE FEET route")
    kernel.feet.move(
        prepared.route_id,
        current_step_ref=route.current_step_ref,
        current_location="REPLANNING",
        next_location="AUTHORIZING",
    )

    prepared_steps = list(succeeded)
    for key in order:
        req = by_key[key]
        cap = resolved[key]
        step = created[key]
        assignment = SpecialistAssignment(
            f"assignment:{uuid.uuid4()}",
            prepared.task_ref,
            step.step_id,
            context.isolation_boundary,
            cap.capability_id,
            prepared.context_manifest_ref,
            req.expected_output,
            "UNBOUND",
            (cap.provider_ref,),
            None,
            {},
            kernel.mind_store.goal(prepared.goal_ref).success_conditions,
        )
        prepared_steps.append(PreparedStep(key, step.step_id, cap.capability_id, assignment))
    revised = PreparedPlan(
        prepared.task_ref,
        prepared.intent_ref,
        prepared.goal_ref,
        decision.decision_id,
        prepared.plan_ref,
        prepared.context_manifest_ref,
        prepared.route_id,
        tuple(prepared_steps),
    )
    return ReplanResult(
        perception_observation.observation_id,
        verified.evidence_id,
        old_plan.revision,
        plan.revision,
        revised,
    )


def open_replanned_step(
    kernel,
    result: ReplanResult,
    envelope: AuthorityEnvelope,
    *,
    worker_id: str,
    step_key: str,
    now: str | None = None,
    actor: str = "BRO",
) -> FlowBinding:
    """Freshly authorize and start one dependency-ready Step after replan."""
    prepared = result.prepared
    target = prepared.step(step_key)
    step = kernel.nervous.step(target.step_ref)
    if step.state is not StepState.READY:
        raise MultiStepRejected("replanned Step is not READY")
    if step.plan_ref != prepared.plan_ref or step.plan_revision != result.plan_revision:
        raise MultiStepRejected("replanned Step is not bound to the current Plan revision")
    task = kernel.task_store.fetch_task(prepared.task_ref)
    if task["state"] != TaskState.PLANNING or task["plan_revision"] != result.plan_revision:
        raise MultiStepRejected("Task is not positioned on the replanned revision")
    _, context = _require_current_plan_and_context(kernel, prepared, task)
    if context.isolation_boundary != target.assignment.project_boundary:
        raise BoundaryViolation("replanned assignment crosses the Context Manifest isolation boundary")

    assignment = target.assignment
    if envelope.task_ref != prepared.task_ref:
        raise BoundaryViolation("authority envelope belongs to a different Task")
    if set(assignment.allowed_tools) - set(envelope.tool_boundary):
        raise BoundaryViolation("authority envelope does not grant the selected adapter")
    assignment = SpecialistAssignment(**{**assignment.__dict__, "authority_envelope_ref": envelope.envelope_id})
    moment = now or utc_now()

    kernel.supervisor.actions.register_authority(envelope)
    verdict = _fresh_continuation_verdict(kernel, assignment, envelope, moment)
    authorizing = kernel.supervisor.tasks.transition(
        prepared.task_ref,
        TaskState.AUTHORIZING,
        actor,
        "fresh authority evaluated for replanned Step",
        task["revision"],
        correlation_ref=prepared.task_ref,
        context_manifest_ref=prepared.context_manifest_ref,
        authority_state=AUTHORITY_DECISION_TO_TASK_STATE[verdict.decision],
    )
    kernel.supervisor.assignments.create_assignment(assignment, actor, moment)
    if verdict.decision is not AuthorityDecision.ALLOW:
        reason = "; ".join(verdict.reasons) or envelope.reason
        kernel.supervisor.tasks.transition(
            prepared.task_ref,
            TaskState.BLOCKED,
            kernel.supervisor.verifier,
            f"authority state {AUTHORITY_DECISION_TO_TASK_STATE[verdict.decision]}: {reason}",
            authorizing["revision"],
            correlation_ref=prepared.task_ref,
            blocker_ref=envelope.envelope_id,
        )
        kernel.nervous.transition_step(target.step_ref, StepState.BLOCKED)
        kernel.feet.block(prepared.route_id, authority_ref=envelope.envelope_id)
        if verdict.decision is AuthorityDecision.APPROVAL_REQUIRED:
            raise ApprovalRequired(f"task {prepared.task_ref} is waiting for Approval")
        raise BoundaryViolation(f"fresh replanned-step authority denied: {reason}")

    lease = kernel.supervisor.assignments.claim(assignment.assignment_id, worker_id, moment)
    executing = kernel.supervisor.tasks.transition(
        prepared.task_ref,
        TaskState.EXECUTING,
        actor,
        "replanned dependency-ready Step is progressing",
        authorizing["revision"],
        correlation_ref=prepared.task_ref,
        active_step_ref=target.step_ref,
        blocker_ref=None,
    )
    kernel.nervous.transition_step(target.step_ref, StepState.ACTIVE)
    kernel.feet.move(
        prepared.route_id,
        current_step_ref=target.step_ref,
        current_location="EXECUTING",
        next_location="NEXT_STEP",
    )
    return FlowBinding(
        prepared.task_ref,
        executing["revision"],
        assignment.assignment_id,
        lease,
        assignment.project_boundary,
        assignment.context_manifest_ref,
        envelope.envelope_id,
        prepared.task_ref,
    )
