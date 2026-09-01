"""Canonical BRO runtime composition without stealing organ ownership.

The kernel is wiring, not a new system of record. It turns one outcome-level
request into owner-native records, connects continuity and governed context,
and hands execution to GovernedTaskSupervisor.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from .action_runtime import ApprovalRequired, EffectState
from .continuity import ContinuityEnvelope, ContinuityStore
from .feet import FeetStore, RouteCheckpoint, RouteState
from .governed_supervision import GovernedTaskSupervisor
from .immune import AuthorityEnvelope, CompletionManifest
from .memory import MemoryStore
from .mind import KnowledgeState, MindRuntime, SQLiteMindStore
from .nervous_records import ContextEntry, NervousRecordStore, StepState
from .orchestration import SpecialistAssignment
from .perception import PerceptionStore
from .skills import CapabilityMatch, CapabilityRegistry
from .supervision import BoundaryViolation, NextStep
from .task_runtime import SQLiteTaskStore, TaskState, utc_now
from .voice import VoiceInput, VoiceProjection, VoiceRuntime


class KernelRejected(ValueError):
    pass


@dataclass(frozen=True)
class PreparedFlow:
    intent_ref: str
    goal_ref: str
    decision_ref: str
    plan_ref: str
    step_ref: str
    context_manifest_ref: str
    capability_ref: str
    route_id: str
    continuity: ContinuityEnvelope | None
    memory_refs: tuple[str, ...]
    assignment: SpecialistAssignment


@dataclass(frozen=True)
class RecoveryView:
    next_step: NextStep
    route: RouteCheckpoint


class BROKernel:
    """Composition root for the canonical request-to-verified-outcome path."""

    def __init__(self, task_store: SQLiteTaskStore, mind_store: SQLiteMindStore) -> None:
        self.task_store = task_store
        self.mind_store = mind_store
        connection = task_store.connection
        self.perception = PerceptionStore(connection)
        self.mind = MindRuntime(mind_store)
        self.nervous = NervousRecordStore(connection)
        self.skills = CapabilityRegistry(connection)
        self.memory = MemoryStore(connection)
        self.continuity = ContinuityStore(connection)
        self.feet = FeetStore(connection)
        self.voice = VoiceRuntime()
        self.supervisor = GovernedTaskSupervisor(task_store, mind_store=mind_store)

    def prepare(
        self, *, request: object, source: str, project_boundary: str,
        desired_outcome: str, interpreted_scope: tuple[str, ...],
        success_conditions: tuple[str, ...], operation: str, domain: str,
        authority_basis: str, materiality: str, risk_class: str,
        expected_output: str, verification_requirement: str,
        retry_policy: str = "RECONCILE_BEFORE_RETRY",
        constraints: tuple[str, ...] = (), assumptions: tuple[str, ...] = (),
        relationship_scope: str | None = None,
    ) -> PreparedFlow:
        matches = self.skills.discover(operations=(operation,), domains=(domain,))
        if not matches:
            raise KernelRejected(f"no active capability matches operation={operation!r}, domain={domain!r}")
        match: CapabilityMatch = matches[0]
        capability = match.capability
        if not capability.provider_ref:
            raise KernelRejected("selected executable capability has no provider/adapter binding")

        continuity = self.continuity.activate(relationship_scope) if relationship_scope else None
        intent = self.perception.record_intent(content=request, source=source, scope=project_boundary)
        goal = self.mind.form_goal(
            intent_ref=intent.intent_id, desired_outcome=desired_outcome,
            interpreted_scope=interpreted_scope, success_conditions=success_conditions,
            authority_basis=authority_basis, materiality=materiality, risk_class=risk_class,
            constraints=constraints, assumptions=assumptions, uncertainty=KnowledgeState.UNVERIFIED,
        )
        decision = self.mind.decide(
            goal_ref=goal.goal_id, question="Which registered capability should execute this outcome?",
            conclusion={"capability_ref": capability.capability_id, "version": capability.version,
                        "provider_ref": capability.provider_ref},
            rationale="Selected from the active capability registry by required operation and domain.",
            authority_basis=authority_basis, uncertainty=KnowledgeState.CONFIRMED,
            reversibility="REVERSIBLE",
        )

        task_id = f"task:{uuid.uuid4()}"
        plan_id = f"plan:{uuid.uuid4()}"
        step_id = f"step:{uuid.uuid4()}"
        context_id = f"context:{uuid.uuid4()}"
        assignment_id = f"assignment:{uuid.uuid4()}"
        route_id = f"route:{uuid.uuid4()}"

        step = self.nervous.create_step(
            step_id=step_id, task_ref=task_id, plan_ref=plan_id, plan_revision=1,
            purpose=desired_outcome, required_capabilities=(capability.capability_id,),
            expected_output=expected_output, authority_class=risk_class,
            verification_requirement=verification_requirement, retry_policy=retry_policy,
            state=StepState.READY,
        )
        plan = self.mind.plan(
            goal_ref=goal.goal_id, decision_ref=decision.decision_id, step_refs=(step.step_id,),
            checkpoints=("authority", "effect-reconciliation", "completion"),
            recovery_options=("reconcile", "replan", "block"), completion_path=success_conditions,
            reason="Execute the selected capability under canonical authority and evidence gates.",
            plan_id=plan_id,
        )

        entries = [ContextEntry(
            source_ref=intent.intent_id, scope=project_boundary, authority=authority_basis,
            freshness="CURRENT", trust_state="CONFIRMED", sensitivity=intent.sensitivity,
            inclusion_reason="The current request defines the outcome and scope.",
            isolation_boundary=project_boundary,
        )]
        memory_refs: list[str] = []
        for retrieval in self.memory.retrieve(scope=project_boundary):
            record = retrieval.record
            memory_refs.append(record.memory_id)
            entries.append(ContextEntry(
                source_ref=record.memory_id, scope=record.scope,
                authority=record.authority_ref or "MEMORY_SUPPORT_ONLY",
                freshness=record.freshness.value, trust_state="UNVERIFIED",
                sensitivity=record.sensitivity, inclusion_reason=retrieval.reason,
                isolation_boundary=project_boundary,
            ))
        if continuity is not None:
            entries.extend((
                ContextEntry(
                    source_ref=f"SELF:{continuity.self_ref}@{continuity.self_version}",
                    scope=project_boundary, authority="SELF_CONTINUITY", freshness="CURRENT",
                    trust_state="CONFIRMED", sensitivity="PRIVATE",
                    inclusion_reason="Minimal SELF continuity envelope; private foundation is not exposed.",
                    isolation_boundary=project_boundary,
                ),
                ContextEntry(
                    source_ref=f"HEART:{continuity.heart_ref}@{continuity.heart_version}",
                    scope=project_boundary, authority="HEART_CONTINUITY", freshness="CURRENT",
                    trust_state="CONFIRMED", sensitivity="RELATIONSHIP_PRIVATE",
                    inclusion_reason="Minimal HEART relationship stance for this scope.",
                    isolation_boundary=project_boundary,
                ),
            ))
        context = self.nervous.create_context_manifest(
            manifest_id=context_id, task_ref=task_id, isolation_boundary=project_boundary,
            entries=tuple(entries),
        )
        assignment = SpecialistAssignment(
            assignment_id=assignment_id, task_ref=task_id, step_ref=step.step_id,
            project_boundary=project_boundary, required_capability=capability.capability_id,
            context_manifest_ref=context.manifest_id, expected_output_contract=expected_output,
            authority_envelope_ref="UNBOUND", allowed_tools=(capability.provider_ref,),
            deadline=None, budget={}, evidence_requirements=success_conditions,
        )
        return PreparedFlow(
            intent.intent_id, goal.goal_id, decision.decision_id, plan.plan_id, step.step_id,
            context.manifest_id, capability.capability_id, route_id, continuity,
            tuple(memory_refs), assignment,
        )

    def open(self, prepared: PreparedFlow, envelope: AuthorityEnvelope, *, worker_id: str,
             now: str | None = None):
        if envelope.task_ref != prepared.assignment.task_ref:
            raise KernelRejected("authority envelope belongs to a different Task")
        if set(prepared.assignment.allowed_tools) - set(envelope.tool_boundary):
            raise KernelRejected("authority envelope does not grant the selected capability adapter")
        assignment = SpecialistAssignment(**{
            **prepared.assignment.__dict__, "authority_envelope_ref": envelope.envelope_id,
        })
        try:
            binding = self.supervisor.open_flow(
                task_id=assignment.task_ref, goal_ref=prepared.goal_ref, plan_ref=prepared.plan_ref,
                assignment=assignment, envelope=envelope, worker_id=worker_id, now=now,
            )
        except (ApprovalRequired, BoundaryViolation):
            task = self.task_store.fetch_task(assignment.task_ref)
            blocker = task.get("blocker_ref") or envelope.envelope_id
            self.feet.append(RouteCheckpoint(
                route_id=prepared.route_id, version=1, task_ref=assignment.task_ref,
                plan_ref=prepared.plan_ref, current_step_ref=prepared.step_ref,
                current_location=task["state"], next_location=None, unresolved_refs=(blocker,),
                authority_blocker_ref=blocker, integrity_blocker_ref=None, risk_blocker_ref=None,
                state=RouteState.BLOCKED, recorded_at=utc_now(),
            ))
            raise
        self.feet.append(RouteCheckpoint(
            route_id=prepared.route_id, version=1, task_ref=assignment.task_ref,
            plan_ref=prepared.plan_ref, current_step_ref=prepared.step_ref,
            current_location="EXECUTING", next_location="VERIFYING", unresolved_refs=(),
            authority_blocker_ref=None, integrity_blocker_ref=None, risk_blocker_ref=None,
            state=RouteState.ACTIVE, recorded_at=utc_now(),
        ))
        return binding

    def complete(self, prepared: PreparedFlow, binding, *, outcome_statement: str,
                 required_criteria: tuple[str, ...], artifact_refs: tuple[str, ...] = (),
                 actor: str = "BRO", now: str | None = None) -> CompletionManifest:
        manifest = self.supervisor.complete(
            binding, outcome_statement=outcome_statement, required_criteria=required_criteria,
            artifact_refs=artifact_refs, actor=actor, now=now,
        )
        route = self.feet.latest(prepared.route_id)
        if manifest.is_verified():
            if route.state is RouteState.BLOCKED:
                raise KernelRejected("verified completion cannot close a route with unresolved blockers")
            self.feet.complete(prepared.route_id)
        elif route.state is not RouteState.BLOCKED:
            self.feet.block(prepared.route_id, integrity_ref=manifest.manifest_id)
        return manifest

    def recover(self, task_id: str, route_id: str) -> RecoveryView:
        """Reconstruct next work without replaying any external command."""
        next_step = self.supervisor.resume(task_id)
        task = self.task_store.fetch_task(task_id)
        route = self.feet.latest(route_id)
        if task["state"] == TaskState.COMPLETED and route.state is not RouteState.COMPLETED:
            route = self.feet.complete(route_id)
        elif task["state"] == TaskState.BLOCKED and route.state is not RouteState.BLOCKED:
            blocker = task.get("blocker_ref")
            if not blocker:
                raise KernelRejected("BLOCKED Task has no canonical blocker_ref for FEET")
            route = self.feet.block(
                route_id,
                authority_ref=blocker if task.get("authority_state") in {"DENIED", "APPROVAL_REQUIRED"} else None,
                integrity_ref=None if task.get("authority_state") in {"DENIED", "APPROVAL_REQUIRED"} else blocker,
            )
        return RecoveryView(next_step, route)

    def project_voice(self, task_id: str, *, uncertainty: tuple[str, ...] = ()) -> VoiceProjection:
        """Project canonical state through VOICE without upgrading any claim."""
        task = self.task_store.fetch_task(task_id)
        manifest = self.supervisor.evidence.latest_manifest(task_id)
        completion_state = manifest["verdict"] if manifest else "UNVERIFIED"
        evidence_state = "VERIFIED" if manifest and manifest["verdict"] == "VERIFIED" else "UNVERIFIED"
        effect_state = "NONE"
        requests = self.supervisor.actions.requests_for_task(task_id)
        if requests:
            attempt = self.supervisor.actions.latest_attempt(requests[-1]["action_request_id"])
            if attempt:
                effect_state = self.supervisor.actions.effective_effect(attempt).value
        return self.voice.project(VoiceInput(
            task_ref=task_id, task_state=task["state"], authority_state=task["authority_state"],
            evidence_state=evidence_state, effect_state=effect_state,
            completion_state=completion_state, uncertainty=uncertainty,
            blocker_ref=task.get("blocker_ref"),
        ))
