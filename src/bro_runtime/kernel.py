"""Canonical BRO runtime composition without stealing organ ownership."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable

from .action_runtime import ActionRequest, ApprovalRequired, EffectState
from .capability_selection import CapabilitySelectionRejected, select_capability
from .continuity import ContinuityEnvelope, ContinuityStore
from .evidence_verification import (
    EvidenceObservation,
    EvidenceVerificationRegistry,
    EvidenceVerifier,
)
from .feet import FeetStore, RouteCheckpoint, RouteState
from .governed_supervision import GovernedTaskSupervisor
from .immune import AuthorityEnvelope, CompletionManifest, Evidence, evidence_scope
from .memory import MemoryStore
from .mind import KnowledgeState, MindRuntime, SQLiteMindStore
from .nervous_records import ContextEntry, NervousRecordStore, StepState
from .orchestration import AssignmentState, SpecialistAssignment
from .perception import PerceptionStore
from .provider_adapters import ProviderAdapter, ProviderAdapterRegistry, ProviderHealth
from .provider_execution import ProviderExecutionGateway, ProviderRoute
from .restart_recovery import RestartReconciliation, RestartRecoveryRuntime
from .secret_runtime import SecretMediator
from .readiness import ReadinessReport, RuntimeReadiness
from .skills import CapabilityRegistry
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
    """The canonical composition root for planning, governed execution and truth."""

    def __init__(
        self,
        task_store: SQLiteTaskStore,
        mind_store: SQLiteMindStore,
        *,
        provider_health_for: Callable[[str], ProviderHealth] | None = None,
    ) -> None:
        self.task_store = task_store
        self.mind_store = mind_store
        c = task_store.connection
        self.perception = PerceptionStore(c)
        self.mind = MindRuntime(mind_store)
        self.nervous = NervousRecordStore(c)
        self.skills = CapabilityRegistry(c)
        self.memory = MemoryStore(c)
        self.continuity = ContinuityStore(c)
        self.feet = FeetStore(c)
        self.voice = VoiceRuntime()
        self.readiness = RuntimeReadiness()
        self.evidence_verifiers = EvidenceVerificationRegistry()
        self.supervisor = GovernedTaskSupervisor(
            task_store,
            mind_store=mind_store,
            evidence_verifiers=self.evidence_verifiers,
        )

        # Canonical production boundaries. Provider routing, evidence verification,
        # and restart reconciliation are composed here so callers do not stitch
        # privileged helper paths together themselves.
        self.providers = ProviderAdapterRegistry()
        self.secrets = SecretMediator()
        self.provider_gateway = ProviderExecutionGateway(self.supervisor, self.providers, self.secrets)
        self.restart_recovery = RestartRecoveryRuntime(self.supervisor)
        self._provider_health_for = provider_health_for or (lambda _provider_ref: ProviderHealth.HEALTHY)

    def register_provider(self, adapter: ProviderAdapter) -> ProviderAdapter:
        return self.providers.register(adapter)

    def register_evidence_verifier(self, verifier: EvidenceVerifier) -> EvidenceVerifier:
        return self.evidence_verifiers.register(verifier)

    def prepare(
        self,
        *,
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
        matches = self.skills.discover(operations=(operation,), domains=(domain,))
        if not matches:
            raise KernelRejected(f"no active capability matches operation={operation!r}, domain={domain!r}")
        try:
            match = select_capability(matches, self._provider_health_for)
        except CapabilitySelectionRejected as exc:
            raise KernelRejected(str(exc)) from exc
        cap = match.capability
        if not cap.provider_ref:
            raise KernelRejected("selected executable capability has no provider/adapter binding")

        continuity = self.continuity.activate(relationship_scope) if relationship_scope else None
        intent = self.perception.record_intent(content=request, source=source, scope=project_boundary)
        goal = self.mind.form_goal(
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
        decision = self.mind.decide(
            goal_ref=goal.goal_id,
            question="Which registered capability should execute this outcome?",
            conclusion={
                "capability_ref": cap.capability_id,
                "version": cap.version,
                "provider_ref": cap.provider_ref,
            },
            rationale="Selected from the capability registry using provider-health-aware routing.",
            authority_basis=authority_basis,
            uncertainty=KnowledgeState.CONFIRMED,
            reversibility="REVERSIBLE",
        )

        task_id = f"task:{uuid.uuid4()}"
        plan_id = f"plan:{uuid.uuid4()}"
        step_id = f"step:{uuid.uuid4()}"
        context_id = f"context:{uuid.uuid4()}"
        assignment_id = f"assignment:{uuid.uuid4()}"
        route_id = f"route:{uuid.uuid4()}"

        step = self.nervous.create_step(
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
        plan = self.mind.plan(
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
            ContextEntry(
                intent.intent_id,
                project_boundary,
                authority_basis,
                "CURRENT",
                "CONFIRMED",
                intent.sensitivity,
                "The current request defines the outcome and scope.",
                project_boundary,
            )
        ]
        memory_refs: list[str] = []
        for retrieval in self.memory.retrieve(scope=project_boundary):
            memory = retrieval.record
            memory_refs.append(memory.memory_id)
            entries.append(
                ContextEntry(
                    memory.memory_id,
                    memory.scope,
                    memory.authority_ref or "MEMORY_SUPPORT_ONLY",
                    memory.freshness.value,
                    "UNVERIFIED",
                    memory.sensitivity,
                    retrieval.reason,
                    project_boundary,
                )
            )
        if continuity:
            entries.extend(
                (
                    ContextEntry(
                        f"SELF:{continuity.self_ref}@{continuity.self_version}",
                        project_boundary,
                        "SELF_CONTINUITY",
                        "CURRENT",
                        "CONFIRMED",
                        "PRIVATE",
                        "Minimal SELF continuity envelope; private foundation is not exposed.",
                        project_boundary,
                    ),
                    ContextEntry(
                        f"HEART:{continuity.heart_ref}@{continuity.heart_version}",
                        project_boundary,
                        "HEART_CONTINUITY",
                        "CURRENT",
                        "CONFIRMED",
                        "RELATIONSHIP_PRIVATE",
                        "Minimal HEART relationship stance for this scope.",
                        project_boundary,
                    ),
                )
            )
        context = self.nervous.create_context_manifest(
            manifest_id=context_id,
            task_ref=task_id,
            isolation_boundary=project_boundary,
            entries=tuple(entries),
        )
        assignment = SpecialistAssignment(
            assignment_id,
            task_id,
            step.step_id,
            project_boundary,
            cap.capability_id,
            context.manifest_id,
            expected_output,
            "UNBOUND",
            (cap.provider_ref,),
            None,
            {},
            success_conditions,
        )
        return PreparedFlow(
            intent.intent_id,
            goal.goal_id,
            decision.decision_id,
            plan.plan_id,
            step.step_id,
            context.manifest_id,
            cap.capability_id,
            route_id,
            continuity,
            tuple(memory_refs),
            assignment,
        )

    def open(self, prepared: PreparedFlow, envelope: AuthorityEnvelope, *, worker_id: str, now: str | None = None):
        if envelope.task_ref != prepared.assignment.task_ref:
            raise KernelRejected("authority envelope belongs to a different Task")
        if set(prepared.assignment.allowed_tools) - set(envelope.tool_boundary):
            raise KernelRejected("authority envelope does not grant the selected capability adapter")
        assignment = SpecialistAssignment(
            **{**prepared.assignment.__dict__, "authority_envelope_ref": envelope.envelope_id}
        )
        try:
            binding = self.supervisor.open_flow(
                task_id=assignment.task_ref,
                goal_ref=prepared.goal_ref,
                plan_ref=prepared.plan_ref,
                assignment=assignment,
                envelope=envelope,
                worker_id=worker_id,
                now=now,
            )
        except (ApprovalRequired, BoundaryViolation):
            task = self.task_store.fetch_task(assignment.task_ref)
            blocker = task.get("blocker_ref") or envelope.envelope_id
            self.nervous.transition_step(prepared.step_ref, StepState.BLOCKED)
            self.feet.append(
                RouteCheckpoint(
                    prepared.route_id,
                    1,
                    assignment.task_ref,
                    prepared.plan_ref,
                    prepared.step_ref,
                    task["state"],
                    None,
                    (blocker,),
                    blocker,
                    None,
                    None,
                    RouteState.BLOCKED,
                    utc_now(),
                )
            )
            raise
        self.nervous.transition_step(prepared.step_ref, StepState.ACTIVE)
        self.feet.append(
            RouteCheckpoint(
                prepared.route_id,
                1,
                assignment.task_ref,
                prepared.plan_ref,
                prepared.step_ref,
                "EXECUTING",
                "VERIFYING",
                (),
                None,
                None,
                None,
                RouteState.ACTIVE,
                utc_now(),
            )
        )
        return binding

    def execute_provider(
        self,
        binding,
        request: ActionRequest,
        *,
        route: ProviderRoute,
        executor: str,
        now: str | None = None,
    ) -> dict:
        """Canonical external-action path: registered provider -> IMMUNE -> HANDS."""
        return self.provider_gateway.execute(
            binding,
            request,
            route=route,
            executor=executor,
            now=now,
        )

    def verify_evidence(
        self,
        prepared: PreparedFlow,
        observation: EvidenceObservation,
        *,
        verifier_id: str,
        evidence_id: str | None = None,
        collected_at: str | None = None,
    ) -> Evidence:
        expected_scope = evidence_scope(prepared.assignment.project_boundary, prepared.assignment.task_ref)
        if observation.scope != expected_scope:
            raise KernelRejected("evidence observation crosses the prepared task boundary")
        return self.evidence_verifiers.verify(
            verifier_id,
            observation,
            evidence_id=evidence_id,
            collected_at=collected_at,
        )

    def reconcile_verified(
        self,
        prepared: PreparedFlow,
        binding,
        request_id: str,
        effect_state: EffectState,
        observation: EvidenceObservation,
        *,
        verifier_id: str,
        now: str | None = None,
    ) -> dict:
        evidence = self.verify_evidence(prepared, observation, verifier_id=verifier_id, collected_at=now)
        return self.supervisor.reconcile(binding, request_id, effect_state, evidence, now=now)

    def reconcile_after_restart(
        self,
        task_id: str,
        request_id: str,
        effect_state: EffectState,
        observation: EvidenceObservation,
        *,
        verifier_id: str,
        worker_id: str,
        now: str,
        lease_seconds: int = 30,
    ) -> RestartReconciliation:
        """Canonical restart path: trusted Evidence first, then fenced reconciliation; never replay."""
        assignments = self.supervisor.assignments.assignments_for_task(task_id)
        if not assignments:
            raise KernelRejected("persisted Task has no specialist assignment for restart reconciliation")
        body = json.loads(assignments[-1]["body"])
        expected_scope = evidence_scope(body["project_boundary"], task_id)
        if observation.scope != expected_scope:
            raise KernelRejected("restart observation crosses the persisted Task boundary")
        evidence = self.evidence_verifiers.verify(
            verifier_id,
            observation,
            collected_at=now,
        )
        return self.restart_recovery.reconcile_observed_effect(
            task_id,
            request_id,
            effect_state=effect_state,
            evidence=evidence,
            worker_id=worker_id,
            now=now,
            lease_seconds=lease_seconds,
        )

    def settle_verified_assignment(
        self,
        prepared: PreparedFlow,
        binding,
        *,
        result_state: AssignmentState,
        output_ref: str | None,
        observations: Iterable[tuple[str, EvidenceObservation]],
        limitations: Iterable[str] = (),
        now: str | None = None,
    ) -> dict:
        evidence = tuple(
            self.verify_evidence(prepared, observation, verifier_id=verifier_id, collected_at=now)
            for verifier_id, observation in observations
        )
        return self.supervisor.settle_assignment(
            binding,
            result_state=result_state,
            output_ref=output_ref,
            evidence=evidence,
            limitations=limitations,
            now=now,
        )

    def resume_with_approval(
        self,
        prepared: PreparedFlow,
        approval_id: str,
        worker_id: str,
        *,
        now: str | None = None,
        actor: str = "BRO",
    ):
        binding = self.supervisor.resume_with_approval(
            prepared.assignment.task_ref,
            approval_id,
            worker_id,
            now=now,
            actor=actor,
        )
        task = self.task_store.fetch_task(prepared.assignment.task_ref)
        prior = self.feet.latest(prepared.route_id)
        if prior.state is not RouteState.BLOCKED:
            raise KernelRejected("approval resume expected a BLOCKED FEET route")
        self.feet.resume(
            prepared.route_id,
            blocker_resolved=lambda ref: ref == prior.authority_blocker_ref and task["authority_state"] == "ALLOWED",
        )
        self.feet.move(
            prepared.route_id,
            current_step_ref=prepared.step_ref,
            current_location="EXECUTING",
            next_location="VERIFYING",
        )
        self.nervous.transition_step(prepared.step_ref, StepState.ACTIVE)
        return binding

    def complete(
        self,
        prepared: PreparedFlow,
        binding,
        *,
        outcome_statement: str,
        required_criteria: tuple[str, ...],
        artifact_refs: tuple[str, ...] = (),
        actor: str = "BRO",
        now: str | None = None,
    ) -> CompletionManifest:
        manifest = self.supervisor.complete(
            binding,
            outcome_statement=outcome_statement,
            required_criteria=required_criteria,
            artifact_refs=artifact_refs,
            actor=actor,
            now=now,
        )
        route = self.feet.latest(prepared.route_id)
        if manifest.is_verified():
            if route.state is RouteState.BLOCKED:
                raise KernelRejected("verified completion cannot close a route with unresolved blockers")
            self.nervous.transition_step(prepared.step_ref, StepState.SUCCEEDED)
            self.feet.complete(prepared.route_id)
        elif route.state is not RouteState.BLOCKED:
            self.nervous.transition_step(prepared.step_ref, StepState.BLOCKED)
            self.feet.block(prepared.route_id, integrity_ref=manifest.manifest_id)
        return manifest

    def recover(self, task_id: str, route_id: str) -> RecoveryView:
        next_step = self.supervisor.resume(task_id)
        task = self.task_store.fetch_task(task_id)
        route = self.feet.latest(route_id)
        if task["state"] == TaskState.COMPLETED and route.state is not RouteState.COMPLETED:
            route = self.feet.complete(route_id)
        elif task["state"] == TaskState.BLOCKED and route.state is not RouteState.BLOCKED:
            blocker = task.get("blocker_ref")
            if not blocker:
                raise KernelRejected("BLOCKED Task has no canonical blocker_ref for FEET")
            auth = task.get("authority_state") in {"DENIED", "APPROVAL_REQUIRED"}
            route = self.feet.block(
                route_id,
                authority_ref=blocker if auth else None,
                integrity_ref=None if auth else blocker,
            )
        return RecoveryView(next_step, route)

    def project_voice(self, task_id: str, *, uncertainty: tuple[str, ...] = ()) -> VoiceProjection:
        task = self.task_store.fetch_task(task_id)
        manifest = self.supervisor.evidence.latest_manifest(task_id)
        completion = manifest["verdict"] if manifest else "UNVERIFIED"
        evidence = "VERIFIED" if manifest and manifest["verdict"] == "VERIFIED" else "UNVERIFIED"
        effect = "NONE"
        requests = self.supervisor.actions.requests_for_task(task_id)
        if requests:
            attempt = self.supervisor.actions.latest_attempt(requests[-1]["action_request_id"])
            if attempt:
                effect = self.supervisor.actions.effective_effect(attempt).value
        return self.voice.project(
            VoiceInput(
                task_id,
                task["state"],
                task["authority_state"],
                evidence,
                effect,
                completion,
                uncertainty,
                task.get("blocker_ref"),
            )
        )

    def project_readiness(self, prepared: PreparedFlow) -> ReadinessReport:
        task = self.task_store.fetch_task(prepared.assignment.task_ref)
        step = self.nervous.step(prepared.step_ref)
        route = self.feet.latest(prepared.route_id)
        manifest = self.supervisor.evidence.latest_manifest(prepared.assignment.task_ref)
        return self.readiness.measure_task(
            task=task,
            step=step,
            route=route,
            completion_manifest=manifest,
        )