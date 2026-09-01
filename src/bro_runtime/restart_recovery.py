"""Durable restart recovery for unresolved external effects.

NERVOUS SYSTEM owns the recovery sequence but creates no new canonical record.
It reuses persisted Task, Assignment, lease, Action and Evidence state and only
reclaims a fresh fenced lease when external reality has already been observed.
The external command is never replayed by this runtime.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .action_runtime import EffectState
from .immune import Evidence
from .orchestration import AssignmentState
from .supervision import FlowBinding, NextAction, TaskSupervisor
from .task_runtime import TERMINAL_STATES, TaskState


class RestartRecoveryRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class RestartReconciliation:
    binding: FlowBinding
    request_id: str
    effect_state: EffectState
    attempt: dict


class RestartRecoveryRuntime:
    """Reconcile one persisted POSSIBLE/UNKNOWN effect after process restart."""

    def __init__(self, supervisor: TaskSupervisor) -> None:
        self.supervisor = supervisor

    def reconcile_observed_effect(
        self,
        task_id: str,
        request_id: str,
        *,
        effect_state: EffectState,
        evidence: Evidence,
        worker_id: str,
        now: str,
        lease_seconds: int = 30,
    ) -> RestartReconciliation:
        if effect_state not in {EffectState.CONFIRMED, EffectState.NONE, EffectState.REVERSED}:
            raise RestartRecoveryRejected("restart reconciliation requires a resolved observed effect")

        task = self.supervisor.store.fetch_task(task_id)
        state = TaskState(task["state"])
        if state in TERMINAL_STATES:
            raise RestartRecoveryRejected(f"terminal Task {state} cannot recover in place")

        # A crashed worker may leave a durable ACTIVE lease. Only canonical lease
        # expiry may release it; we never steal a still-live fencing token.
        self.supervisor.assignments.expire_leases(now, actor="restart-recovery")

        next_step = self.supervisor.resume(task_id)
        if next_step.action is not NextAction.RECONCILE_EFFECT:
            raise RestartRecoveryRejected(
                f"durable Task does not require effect reconciliation: {next_step.action}"
            )
        if next_step.action_request_id != request_id:
            raise RestartRecoveryRejected("requested reconciliation is not the canonical next unresolved action")

        assignments = self.supervisor.assignments.assignments_for_task(task_id)
        if not assignments:
            raise RestartRecoveryRejected("persisted Task has no specialist assignment")
        assignment = assignments[-1]
        if assignment["assignment_id"] != next_step.assignment_id:
            raise RestartRecoveryRejected("canonical recovery assignment changed during inspection")

        assignment = self.supervisor.assignments.get_assignment(assignment["assignment_id"])
        assignment_state = AssignmentState(assignment["state"])
        if assignment_state is AssignmentState.LEASED:
            raise RestartRecoveryRejected(
                "prior worker lease is still active; fail closed until canonical lease expiry"
            )
        if assignment_state not in {AssignmentState.READY, AssignmentState.RECOVERING}:
            raise RestartRecoveryRejected(
                f"assignment {assignment_state} cannot be reclaimed for restart reconciliation"
            )

        body = json.loads(assignment["body"])
        lease = self.supervisor.assignments.claim(
            assignment["assignment_id"], worker_id, now, lease_seconds
        )
        binding = FlowBinding(
            task_id=task_id,
            task_revision=task["revision"],
            assignment_id=assignment["assignment_id"],
            lease=lease,
            project_boundary=body["project_boundary"],
            context_manifest_ref=body["context_manifest_ref"],
            authority_envelope_ref=body["authority_envelope_ref"],
            correlation_ref=task_id,
        )
        self.supervisor.tasks.record_event(
            task_id,
            "recovery.lease_reclaimed",
            worker_id,
            "fresh fenced lease reclaimed only for observed-effect reconciliation",
            correlation_ref=task_id,
            payload={
                "assignment_id": assignment["assignment_id"],
                "fencing_token": lease.fencing_token,
                "action_request_id": request_id,
                "command_replayed": False,
            },
        )
        attempt = self.supervisor.reconcile(
            binding,
            request_id,
            effect_state,
            evidence,
            now=now,
        )
        return RestartReconciliation(binding, request_id, effect_state, attempt)
