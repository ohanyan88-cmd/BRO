"""Dependency-aware multi-step preparation without stealing canonical ownership.

MIND still owns Plan, NERVOUS still owns Step/Assignment scheduling records,
and SKILLS only supplies capability candidates. This module composes them.
"""
from __future__ import annotations
from dataclasses import dataclass
from .nervous_records import StepState

class MultiStepRejected(ValueError): pass

@dataclass(frozen=True)
class StepRequest:
    key: str
    purpose: str
    operation: str
    domain: str
    expected_output: str
    verification_requirement: str
    dependencies: tuple[str,...]=()
    risk_class: str="R2"
    retry_policy: str="RECONCILE_BEFORE_RETRY"

    def __post_init__(self):
        if not all((self.key.strip(),self.purpose.strip(),self.operation.strip(),self.domain.strip(),self.expected_output.strip(),self.verification_requirement.strip())):
            raise MultiStepRejected("multi-step request fields must not be empty")
        if self.key in self.dependencies: raise MultiStepRejected("step cannot depend on itself")

@dataclass(frozen=True)
class PreparedStep:
    key: str
    step_ref: str
    capability_ref: str
    assignment_ref: str

@dataclass(frozen=True)
class PreparedPlan:
    task_ref: str
    intent_ref: str
    goal_ref: str
    decision_ref: str
    plan_ref: str
    context_manifest_ref: str
    route_id: str
    steps: tuple[PreparedStep,...]

    def step(self,key:str)->PreparedStep:
        for item in self.steps:
            if item.key==key:return item
        raise KeyError(key)

def validate_graph(requests:tuple[StepRequest,...])->tuple[str,...]:
    if len(requests)<2: raise MultiStepRejected("multi-step plan requires at least two steps")
    keys=[r.key for r in requests]
    if len(keys)!=len(set(keys)): raise MultiStepRejected("multi-step keys must be unique")
    known=set(keys)
    for r in requests:
        missing=set(r.dependencies)-known
        if missing: raise MultiStepRejected(f"step {r.key} has unknown dependencies: {sorted(missing)}")
    visiting=set(); visited=set(); order=[]
    by_key={r.key:r for r in requests}
    def visit(key):
        if key in visiting: raise MultiStepRejected("multi-step dependency graph contains a cycle")
        if key in visited:return
        visiting.add(key)
        for dep in by_key[key].dependencies:visit(dep)
        visiting.remove(key); visited.add(key); order.append(key)
    for key in keys:visit(key)
    return tuple(order)

def ready_step_refs(prepared:PreparedPlan,nervous)->tuple[str,...]:
    """Promote dependency-satisfied PLANNED steps and return currently READY refs."""
    refs={s.key:s.step_ref for s in prepared.steps}
    ready=[]
    for item in prepared.steps:
        step=nervous.step(item.step_ref)
        if step.state is StepState.PLANNED:
            dependencies=[nervous.step(refs[key]) for key in step.dependencies]
            if dependencies and all(dep.state is StepState.SUCCEEDED for dep in dependencies):
                step=nervous.transition_step(step.step_id,StepState.READY)
        if step.state is StepState.READY: ready.append(step.step_id)
    return tuple(ready)
