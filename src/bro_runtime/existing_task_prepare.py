"""Prepare canonical governed work around a durable pre-existing Task.

Trusted ingress runtimes (for example Automation) may reserve a Task before the
normal planning path runs.  This bridge reuses BROKernel organ owners, preserves
that Task identity, and makes preparation deterministic/restart-safe.  It never
grants authority: ``kernel.open`` remains the canonical authority boundary.
"""
from __future__ import annotations

import uuid

from .capability_selection import CapabilitySelectionRejected, select_capability
from .kernel import BROKernel, KernelRejected, PreparedFlow
from .mind import KnowledgeState
from .nervous_records import ContextEntry, StepState
from .orchestration import SpecialistAssignment
from .task_runtime import TaskState


def _stable_ref(prefix: str, task_id: str) -> str:
    return f"{prefix}:{uuid.uuid5(uuid.NAMESPACE_URL, f'bro://existing-task/{task_id}/{prefix}')}"


def _require_same(label: str, actual, expected) -> None:
    if actual != expected:
        raise KernelRejected(f"restart-safe preparation found conflicting {label}")


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
    """Prepare one unbound RECEIVED Task; retries reuse the same canonical refs."""
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

    continuity = kernel.continuity.activate(relationship_scope) if relationship_scope else None
    intent_id = _stable_ref("intent", task_id)
    decision_id = _stable_ref("decision", task_id)
    plan_id = _stable_ref("plan", task_id)
    step_id = _stable_ref("step", task_id)
    context_id = _stable_ref("context", task_id)
    assignment_id = _stable_ref("assignment", task_id)
    route_id = _stable_ref("route", task_id)

    try:
        intent = kernel.perception.intent(intent_id)
        _require_same("Intent source", intent.source, source)
        _require_same("Intent scope", intent.scope, project_boundary)
        _require_same("Intent content", intent.content, request)
    except Exception as exc:
        if not exc.__class__.__name__ == "PerceptionRejected":
            raise
        intent = kernel.perception.record_intent(
            intent_id=intent_id, content=request, source=source, scope=project_boundary
        )

    try:
        goal = kernel.mind_store.goal(goal_id)
        _require_same("Goal intent", goal.intent_ref, intent.intent_id)
        _require_same("Goal outcome", goal.desired_outcome, desired_outcome)
        _require_same("Goal scope", goal.interpreted_scope, tuple(dict.fromkeys(interpreted_scope)))
        _require_same("Goal success conditions", goal.success_conditions, tuple(dict.fromkeys(x.strip() for x in success_conditions if x.strip())))
    except KeyError:
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

    conclusion = {"capability_ref": cap.capability_id, "version": cap.version, "provider_ref": cap.provider_ref}
    try:
        decision = kernel.mind_store.decision(decision_id)
        _require_same("Decision Goal", decision.goal_ref, goal.goal_id)
        _require_same("Decision capability", decision.conclusion, conclusion)
    except KeyError:
        decision = kernel.mind.decide(
            decision_id=decision_id,
            goal_ref=goal.goal_id,
            question="Which registered capability should execute this outcome?",
            conclusion=conclusion,
            rationale="Selected from the capability registry using provider-health-aware routing.",
            authority_basis=authority_basis,
            uncertainty=KnowledgeState.CONFIRMED,
            reversibility="REVERSIBLE",
        )

    try:
        step = kernel.nervous.step(step_id)
        _require_same("Step Task", step.task_ref, task_id)
        _require_same("Step Plan", (step.plan_ref, step.plan_revision), (plan_id, 1))
        _require_same("Step capability", step.required_capabilities, (cap.capability_id,))
    except KeyError:
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

    try:
        plan = kernel.mind_store.plan(plan_id, 1)
        _require_same("Plan Goal", plan.goal_ref, goal.goal_id)
        _require_same("Plan Decision", plan.decision_ref, decision.decision_id)
        _require_same("Plan Steps", plan.step_refs, (step.step_id,))
    except KeyError:
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

    entries = [
        ContextEntry(intent.intent_id, project_boundary, authority_basis, "CURRENT", "CONFIRMED", intent.sensitivity,
                     "The current request defines the outcome and scope.", project_boundary)
    ]
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
    try:
        context = kernel.nervous.context_manifest(context_id)
        _require_same("Context Task", context.task_ref, task_id)
        _require_same("Context boundary", context.isolation_boundary, project_boundary)
    except KeyError:
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
