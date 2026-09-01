"""Crash-safe recovery for dependency-ordered multi-step plans.

Recovery derives the next runnable Step exclusively from durable MIND Plan and
NERVOUS Step state. Already-succeeded Steps are never returned for replay, and
an ACTIVE Step is treated as uncertain rather than silently re-executed.
"""
from __future__ import annotations

from dataclasses import dataclass

from .multistep import MultiStepRejected
from .nervous_records import StepState


@dataclass(frozen=True)
class MultiStepRecovery:
    task_ref: str
    plan_ref: str
    next_step_ref: str | None
    blocked_step_refs: tuple[str, ...]
    completed_step_refs: tuple[str, ...]


def recover_multistep(kernel, *, task_ref: str, plan_ref: str) -> MultiStepRecovery:
    plan = kernel.mind.plan(plan_ref)
    steps = [kernel.nervous.step(ref) for ref in plan.step_refs]
    if any(step.task_ref != task_ref for step in steps):
        raise MultiStepRejected("plan contains a Step from another Task")

    completed = tuple(step.step_id for step in steps if step.state is StepState.SUCCEEDED)
    uncertain = tuple(step.step_id for step in steps if step.state is StepState.ACTIVE)
    blocked = tuple(
        step.step_id for step in steps
        if step.state in {StepState.BLOCKED, StepState.FAILED, StepState.PARTIAL}
    )
    if uncertain:
        raise MultiStepRejected(
            "ACTIVE Step requires effect/assignment reconciliation before recovery; replay is forbidden"
        )
    if blocked:
        return MultiStepRecovery(task_ref, plan_ref, None, blocked, completed)

    ready: list[str] = []
    for step in steps:
        if step.state is StepState.PLANNED:
            dependencies = [kernel.nervous.step(ref) for ref in step.dependencies]
            if dependencies and all(dep.state is StepState.SUCCEEDED for dep in dependencies):
                step = kernel.nervous.transition_step(step.step_id, StepState.READY)
        if step.state is StepState.READY:
            ready.append(step.step_id)

    if len(ready) > 1:
        raise MultiStepRejected("recovery found multiple READY Steps; deterministic continuation is ambiguous")
    return MultiStepRecovery(task_ref, plan_ref, ready[0] if ready else None, (), completed)
