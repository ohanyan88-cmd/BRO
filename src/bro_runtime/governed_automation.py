"""Governed execution bridge for durable Automation occurrences.

Automation owns *when* work becomes due. This module only converts a durable
occurrence into a prepared canonical flow, obtains an external authority
decision, and enters BROKernel.open. Schedules never embed or mint authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .action_runtime import ApprovalRequired
from .automation import AutomationDefinition, AutomationDispatcher, AutomationOccurrence, AutomationRuntime, OccurrenceState
from .existing_task_prepare import prepare_existing_task
from .immune import AuthorityEnvelope
from .kernel import BROKernel, PreparedFlow
from .supervision import BoundaryViolation
from .task_runtime import TaskRuntime, TaskState


@dataclass(frozen=True)
class AutomationExecutionSpec:
    interpreted_scope: tuple[str, ...]
    success_conditions: tuple[str, ...]
    operation: str
    domain: str
    authority_basis: str
    materiality: str
    risk_class: str
    expected_output: str
    verification_requirement: str
    retry_policy: str = "RECONCILE_BEFORE_RETRY"
    constraints: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    relationship_scope: str | None = None


@dataclass(frozen=True)
class AutomationOpenResult:
    occurrence_id: str
    task_ref: str
    state: str
    prepared: PreparedFlow
    binding: object | None
    blocker_ref: str | None


class GovernedAutomationExecutor:
    """Restart-safe Automation -> existing Task -> governed kernel bridge."""

    def __init__(
        self,
        automation: AutomationRuntime,
        kernel: BROKernel,
        *,
        spec_for: Callable[[AutomationDefinition, AutomationOccurrence], AutomationExecutionSpec],
        authority_for: Callable[[AutomationDefinition, AutomationOccurrence, PreparedFlow], AuthorityEnvelope],
    ) -> None:
        self.automation = automation
        self.kernel = kernel
        self.dispatcher = AutomationDispatcher(automation, TaskRuntime(kernel.task_store))
        self.spec_for = spec_for
        self.authority_for = authority_for

    def _created_occurrences(self) -> tuple[AutomationOccurrence, ...]:
        rows = self.automation.connection.execute(
            "SELECT occurrence_id FROM automation_occurrences WHERE state='TASK_CREATED' ORDER BY due_at,occurrence_id"
        ).fetchall()
        return tuple(self.automation.fetch_occurrence(row["occurrence_id"]) for row in rows)

    def _open_if_received(self, occurrence: AutomationOccurrence, *, worker_id: str, now: str | None) -> AutomationOpenResult | None:
        if occurrence.state is not OccurrenceState.TASK_CREATED or not occurrence.task_ref:
            return None
        task = self.kernel.task_store.fetch_task(occurrence.task_ref)
        if TaskState(task["state"]) is not TaskState.RECEIVED:
            return None
        definition = self.automation.fetch(occurrence.automation_ref)
        spec = self.spec_for(definition, occurrence)
        prepared = prepare_existing_task(
            self.kernel,
            task_id=occurrence.task_ref,
            goal_id=f"automation-goal:{definition.automation_id}",
            request={"automation_ref": definition.automation_id, "occurrence_ref": occurrence.occurrence_id, "due_at": occurrence.due_at},
            source=f"automation:{definition.automation_id}",
            project_boundary=definition.project_boundary,
            desired_outcome=definition.desired_outcome,
            interpreted_scope=spec.interpreted_scope,
            success_conditions=spec.success_conditions,
            operation=spec.operation,
            domain=spec.domain,
            authority_basis=spec.authority_basis,
            materiality=spec.materiality,
            risk_class=spec.risk_class,
            expected_output=spec.expected_output,
            verification_requirement=spec.verification_requirement,
            retry_policy=spec.retry_policy,
            constraints=spec.constraints,
            assumptions=spec.assumptions,
            relationship_scope=spec.relationship_scope,
        )
        envelope = self.authority_for(definition, occurrence, prepared)
        try:
            binding = self.kernel.open(prepared, envelope, worker_id=worker_id, now=now)
        except (ApprovalRequired, BoundaryViolation):
            blocked = self.kernel.task_store.fetch_task(occurrence.task_ref)
            return AutomationOpenResult(
                occurrence.occurrence_id, occurrence.task_ref, blocked["state"], prepared, None, blocked.get("blocker_ref")
            )
        opened = self.kernel.task_store.fetch_task(occurrence.task_ref)
        return AutomationOpenResult(occurrence.occurrence_id, occurrence.task_ref, opened["state"], prepared, binding, None)

    def reconcile_created(self, *, worker_id: str, now: str | None = None) -> tuple[AutomationOpenResult, ...]:
        """Adopt TASK_CREATED/RECEIVED work after a process restart; never replay advanced Tasks."""
        self.dispatcher.reconcile_pending()
        results = []
        for occurrence in self._created_occurrences():
            opened = self._open_if_received(occurrence, worker_id=worker_id, now=now)
            if opened is not None:
                results.append(opened)
        return tuple(results)

    def tick(self, *, now: str, worker_id: str) -> tuple[AutomationOpenResult, ...]:
        """Claim due occurrences, materialize canonical Tasks, then enter governed execution."""
        self.dispatcher.tick(now=now)
        results = []
        for occurrence in self._created_occurrences():
            opened = self._open_if_received(occurrence, worker_id=worker_id, now=now)
            if opened is not None:
                results.append(opened)
        return tuple(results)
