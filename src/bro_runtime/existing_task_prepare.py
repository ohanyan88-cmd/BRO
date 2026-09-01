"""Prepare a canonical governed flow around a durable pre-existing Task.

This is the narrow ingress bridge for trusted runtimes such as Automation.  It
reuses BROKernel's organ owners and produces the same PreparedFlow contract as
BROKernel.prepare, but keeps a caller-supplied Task identity and Goal identity.
It never grants authority; kernel.open remains the governed authority boundary.
"""
from __future__ import annotations

import uuid

from .capability_selection import CapabilitySelectionRejected, select_capability
from .continuity import ContinuityEnvelope
from .kernel import BROKernel, KernelRejected, PreparedFlow
from .mind import KnowledgeState
from .nervous_records import ContextEntry, StepState
from .orchestration import SpecialistAssignment
from .task_runtime import TaskState


def prepare_existing_task(
    kernel: BROKernel,
    *,
    task_id: str,
    goal_id: str,
    request: object,
    source: str,
    project_boundary: str,
    desired_outcome: str,
    interpreted_scope: tuple[str, ...],
    success_conditions: tuple[str, ...],
    operation: str,
    domain: str,
    authority_basis: str,
    materiality: str,
    risk_class: str,
    expected_output: str,
    verification_requirement: str,
    retry_policy: str = "RECONCILE_BEFORE_RETRY",
    constraints: tuple[str, ...] = (),
    assumptions: tuple[str, ...] = (),
    relationship_scope: str | None = None,
) -> PreparedFlow:
    """Prepare an unbound RECEIVED Task without creating or authorizing it."""
    task = kernel.task_store.fetch_task(task_id)
    if TaskState(task["state"]) is not TaskState.RECEIVED:
        raise KernelRejected("existing Task preparation requires RECEIVED state")
    if task["goal_ref"] != goal_id:
        raise KernelRejected("existing Task goal_ref does not match requested Goal identity")
    if task["authority_state"] != "UNASSESSED":
        raise KernelRejected("existing Task already carries authority state")
    if any(task[field] for field in ("plan_ref", "context_manifest_ref", "active_step_ref", "completion_manifest_ref", "blocker_ref")):
        raise KernelRejected("existing Task is already bound to canonical execution state")

    matches = kernel.skills.discover(operations=(operation,), domains=(domain,))
    if not matches:
        raise KernelRejected(f"no active capability matches operation={operation!r}, domain={domain!r}")
    try:
        match = select_capability(matches, kernel._provider_health_for)
    except CapabilitySelectionRejected as exc:
        raise KernelRejected(str(exc)) from exc
    cap = match.capability
    if not cap.provider_ref:
        raise KernelRejected("selected executable capability has no provider/adapter binding")

    continuity: ContinuityEnvelope | None = kernel.continuity.activate(relationship_scope) if relationship_scope else None
    intent = kernel.perception.record_intent(content=request, source=source, scope=project_boundary)
    try:
        goal = kernel.mind.form_goal(
            goal_id=goal_id,
            intent_ref=intent.intent_id,
            desired_outcome=desired_outcome,
            interpreted_scope=interpreted_scope,
            success_conditions=success_conditions,
            authority_basis=authority_basis,
            materiality=materiality,
            risk_class=risk_class,
            constraints=constraints,
            assumptions=assumptions,
            uncertainty=KnowledgeState.UNVERIFIED,
        )
    except Exception as exc:
        raise KernelRejected(f"existing Task Goal could not be formed: {exc}") from exc
    decision = kernel.mind.decide(
        goal_ref=goal.goal_id,
        question="Which registered capability should execute this outcome?",
        conclusion={"capability_ref": cap.capability_id, "version": cap.version, "provider_ref": cap.provider_ref},
        rationale="Selected from the capability registry using provider-health-aware routing.",
        authority_basis=authority_basis,
        uncertainty=KnowledgeState.CONFIRMED,
        reversibility="REVERSIBLE",
    )

    plan_id = f"plan:{uuid.uuid4()}"
    step_id = f"step:{uuid.uuid4()}"
    context_id = f"context:{uuid.uuid4()}"
    assignment_id = f"assignment:{uuid.uuid4()}"
    route_id = f"route:{uuid.uuid4()}"

    step = kernel.nervous.create_step(
        step_id=step_id,
        task_ref=task_id,
        plan_ref=plan_id,
        plan_revision=1,
        purpose=desired_outcome,
        required_capabilities=(cap.capability_id,),
        expected_output=expected_output,
        authority_class=risk_class,
        verification_requirement=verification_requirement,
        retry_policy=retry_policy,
        state=StepState.READY,
    )
    plan = kernel.mind.plan(
        goal_ref=goal.goal_id,
        decision_ref=decision.decision_id,
        step_refs=(step.step_id,),
        checkpoints=("authority", "effect-reconciliation", "completion"),
        recovery_options=("reconcile", "replan", "block"),
        completion_path=success_conditions,
        reason="Execute the selected capability under canonical authority and evidence gates.",
        plan_id=plan_id,
    )

    entries = [ContextEntry(intent.intent_id, project_boundary, authority_basis, "CURRENT", "CONFIRMED", intent.sensitivity,
                            "The current request defines the outcome and scope.", project_boundary)]
    memory_refs: list[str] = []
    for retrieval in kernel.memory.retrieve(scope=project_boundary):
        memory = retrieval.record
        memory_refs.append(memory.memory_id)
        entries.append(ContextEntry(memory.memory_id, memory.scope, memory.authority_ref or "MEMORY_SUPPORT_ONLY",
                                    memory.freshness.value, "UNVERIFIED", memory.sensitivity, retrieval.reason,
                                    project_boundary))
    if continuity:
        entries.extend((
            ContextEntry(f"SELF:{continuity.self_ref}@{continuity.self_version}", project_boundary, "SELF_CONTINUITY",
                         "CURRENT", "CONFIRMED", "PRIVATE",
                         "Minimal SELF continuity envelope; private foundation is not exposed.", project_boundary),
            ContextEntry(f"HEART:{continuity.heart_ref}@{continuity.heart_version}", project_boundary, "HEART_CONTINUITY",
                         "CURRENT", "CONFIRMED", "RELATIONSHIP_PRIVATE",
                         "Minimal HEART relationship stance for this scope.", project_boundary),
        ))
    context = kernel.nervous.create_context_manifest(
        manifest_id=context_id,
        task_ref=task_id,
        isolation_boundary=project_boundary,
        entries=tuple(entries),
    )
    assignment = SpecialistAssignment(
        assignment_id, task_id, step.step_id, project_boundary, cap.capability_id, context.manifest_id,
        expected_output, "UNBOUND", (cap.provider_ref,), None, {}, success_conditions,
    )
    return PreparedFlow(intent.intent_id, goal.goal_id, decision.decision_id, plan.plan_id, step.step_id,
                        context.manifest_id, cap.capability_id, route_id, continuity, tuple(memory_refs), assignment)
