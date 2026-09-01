"""Observation-driven re-entry and replanning for canonical multi-step work.

PERCEPTION owns Observation, MIND owns Decision/Plan revision, NERVOUS owns Step
state, and this module only composes the transition between those owners.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from .action_runtime import ApprovalRequired
from .feet import RouteState
from .immune import AUTHORITY_DECISION_TO_TASK_STATE, ENVELOPE_DECISION_TO_AUTHORITY, AuthorityDecision, AuthorityEnvelope
from .mind import KnowledgeState
from .multistep import MultiStepRejected, PreparedPlan, PreparedStep, StepRequest, validate_graph
from .nervous_records import StepState
from .orchestration import SpecialistAssignment
from .perception import Freshness, TrustState
from .supervision import BoundaryViolation, FlowBinding
from .task_runtime import TaskState, utc_now

@dataclass(frozen=True)
class ReplanResult:
    observation_ref: str
    prior_plan_revision: int
    plan_revision: int
    prepared: PreparedPlan


def replan_from_observation(kernel, prepared: PreparedPlan, *, claim: object, source: str,
                            provenance: dict, freshness: Freshness, trust_state: TrustState,
                            replacements: tuple[StepRequest, ...], limitations: tuple[str, ...] = (),
                            raw_result_ref: str | None = None, integrity: dict | None = None,
                            actor: str = "BRO") -> ReplanResult:
    """Replace unfinished work after inspecting reality.

    Only CURRENT, CONFIRMED observations may automatically change an executing
    plan. We preserve succeeded historical Steps, cancel not-started superseded
    Steps, create a new MIND Plan revision, and move the Task into PLANNING.
    """
    task = kernel.task_store.fetch_task(prepared.task_ref)
    if task["state"] != TaskState.EXECUTING:
        raise MultiStepRejected("observation replan requires an EXECUTING Task")
    if task["plan_ref"] != prepared.plan_ref:
        raise MultiStepRejected("Task is bound to a different Plan")
    if Freshness(freshness) is not Freshness.CURRENT or TrustState(trust_state) is not TrustState.CONFIRMED:
        raise MultiStepRejected("automatic replan requires CURRENT CONFIRMED observation")
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

    observation = kernel.perception.observe(claim=claim, source=source, provenance=provenance,
        freshness=freshness, trust_state=trust_state, scope=kernel.nervous.context_manifest(prepared.context_manifest_ref).isolation_boundary,
        limitations=limitations, raw_result_ref=raw_result_ref, integrity=integrity)
    old_plan = kernel.mind_store.plan(prepared.plan_ref)
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
        req = by_key[key]; cap = resolved[key]
        deps = tuple(step_ids[d] for d in req.dependencies)
        created[key] = kernel.nervous.create_step(step_id=step_ids[key], task_ref=prepared.task_ref,
            plan_ref=prepared.plan_ref, plan_revision=next_revision, purpose=req.purpose, dependencies=deps,
            required_capabilities=(cap.capability_id,), expected_output=req.expected_output,
            authority_class=req.risk_class, verification_requirement=req.verification_requirement,
            retry_policy=req.retry_policy, state=StepState.READY if not deps else StepState.PLANNED)

    decision = kernel.mind.decide(goal_ref=prepared.goal_ref,
        question="How should the active Plan change after the new Observation?",
        conclusion={"observation_ref": observation.observation_id, "replacement_steps": list(order)},
        rationale="Current confirmed reality supersedes the prior executable route.",
        authority_basis=task.get("authority_state") or "UNASSESSED", uncertainty=KnowledgeState.CONFIRMED,
        reversibility="REVERSIBLE", evidence_refs=(observation.observation_id,))
    new_refs = tuple(item.step_ref for item in succeeded) + tuple(step_ids[key] for key in order)
    plan = kernel.mind.replan(prepared.plan_ref, step_refs=new_refs,
        decision_ref=decision.decision_id, reason="Re-entered planning after a current confirmed Observation changed reality.")
    kernel.supervisor.tasks.transition(prepared.task_ref, TaskState.PLANNING, actor,
        "current confirmed Observation requires replanning", task["revision"], correlation_ref=prepared.task_ref,
        plan_ref=prepared.plan_ref, plan_revision=plan.revision,
        payload={"observation_ref": observation.observation_id, "prior_plan_revision": old_plan.revision})
    route = kernel.feet.latest(prepared.route_id)
    if route.state is not RouteState.ACTIVE:
        raise MultiStepRejected("observation replan requires an ACTIVE FEET route")
    kernel.feet.move(prepared.route_id, current_step_ref=route.current_step_ref,
        current_location="REPLANNING", next_location="AUTHORIZING")

    prepared_steps = list(succeeded)
    context = kernel.nervous.context_manifest(prepared.context_manifest_ref)
    for key in order:
        req = by_key[key]; cap = resolved[key]; step = created[key]
        assignment = SpecialistAssignment(f"assignment:{uuid.uuid4()}", prepared.task_ref, step.step_id,
            context.isolation_boundary, cap.capability_id, prepared.context_manifest_ref, req.expected_output,
            "UNBOUND", (cap.provider_ref,), None, {}, kernel.mind_store.goal(prepared.goal_ref).success_conditions)
        prepared_steps.append(PreparedStep(key, step.step_id, cap.capability_id, assignment))
    revised = PreparedPlan(prepared.task_ref, prepared.intent_ref, prepared.goal_ref, decision.decision_id,
        prepared.plan_ref, prepared.context_manifest_ref, prepared.route_id, tuple(prepared_steps))
    return ReplanResult(observation.observation_id, old_plan.revision, plan.revision, revised)


def open_replanned_step(kernel, result: ReplanResult, envelope: AuthorityEnvelope, *,
                        worker_id: str, step_key: str, now: str | None = None,
                        actor: str = "BRO") -> FlowBinding:
    """Authorize and start one dependency-ready Step after replan."""
    prepared = result.prepared; target = prepared.step(step_key); step = kernel.nervous.step(target.step_ref)
    if step.state is not StepState.READY:
        raise MultiStepRejected("replanned Step is not READY")
    task = kernel.task_store.fetch_task(prepared.task_ref)
    if task["state"] != TaskState.PLANNING or task["plan_revision"] != result.plan_revision:
        raise MultiStepRejected("Task is not positioned on the replanned revision")
    assignment = target.assignment
    if envelope.task_ref != prepared.task_ref:
        raise BoundaryViolation("authority envelope belongs to a different Task")
    if set(assignment.allowed_tools) - set(envelope.tool_boundary):
        raise BoundaryViolation("authority envelope does not grant the selected adapter")
    assignment = SpecialistAssignment(**{**assignment.__dict__, "authority_envelope_ref": envelope.envelope_id})
    moment = now or utc_now()
    decision = ENVELOPE_DECISION_TO_AUTHORITY.get(envelope.decision, AuthorityDecision.DENY)
    authorizing = kernel.supervisor.tasks.transition(prepared.task_ref, TaskState.AUTHORIZING, actor,
        "resolving authority for replanned Step", task["revision"], correlation_ref=prepared.task_ref,
        context_manifest_ref=prepared.context_manifest_ref,
        authority_state=AUTHORITY_DECISION_TO_TASK_STATE[decision])
    kernel.supervisor.actions.register_authority(envelope)
    kernel.supervisor.assignments.create_assignment(assignment, actor, moment)
    if decision is not AuthorityDecision.ALLOW:
        kernel.supervisor.tasks.transition(prepared.task_ref, TaskState.BLOCKED, kernel.supervisor.verifier,
            f"authority state {AUTHORITY_DECISION_TO_TASK_STATE[decision]}: {envelope.reason}",
            authorizing["revision"], correlation_ref=prepared.task_ref, blocker_ref=envelope.envelope_id)
        kernel.nervous.transition_step(target.step_ref, StepState.BLOCKED)
        kernel.feet.block(prepared.route_id, authority_ref=envelope.envelope_id)
        if envelope.decision == "APPROVAL_REQUIRED":
            raise ApprovalRequired(f"task {prepared.task_ref} is waiting for Approval")
        raise BoundaryViolation(f"authority envelope is not ALLOWED: {envelope.decision}")
    lease = kernel.supervisor.assignments.claim(assignment.assignment_id, worker_id, moment)
    executing = kernel.supervisor.tasks.transition(prepared.task_ref, TaskState.EXECUTING, actor,
        "replanned dependency-ready Step is progressing", authorizing["revision"],
        correlation_ref=prepared.task_ref, active_step_ref=target.step_ref, blocker_ref=None)
    kernel.nervous.transition_step(target.step_ref, StepState.ACTIVE)
    kernel.feet.move(prepared.route_id, current_step_ref=target.step_ref,
        current_location="EXECUTING", next_location="NEXT_STEP")
    return FlowBinding(prepared.task_ref, executing["revision"], assignment.assignment_id, lease,
        assignment.project_boundary, assignment.context_manifest_ref, envelope.envelope_id, prepared.task_ref)
