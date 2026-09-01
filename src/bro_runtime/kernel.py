"""Canonical BRO runtime composition without stealing organ ownership.

The kernel is wiring, not a new system of record. It turns one outcome-level
request into owner-native records and hands execution to GovernedTaskSupervisor.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from .immune import AuthorityEnvelope
from .mind import KnowledgeState, MindRuntime, SQLiteMindStore
from .nervous_records import ContextEntry, NervousRecordStore, StepState
from .orchestration import SpecialistAssignment
from .perception import PerceptionStore
from .skills import CapabilityMatch, CapabilityRegistry
from .governed_supervision import GovernedTaskSupervisor
from .task_runtime import SQLiteTaskStore

class KernelRejected(ValueError): pass

@dataclass(frozen=True)
class PreparedFlow:
    intent_ref:str; goal_ref:str; decision_ref:str; plan_ref:str; step_ref:str
    context_manifest_ref:str; capability_ref:str; assignment:SpecialistAssignment

class BROKernel:
    """Composition root for the canonical request-to-execution path."""
    def __init__(self, task_store:SQLiteTaskStore, mind_store:SQLiteMindStore)->None:
        self.task_store=task_store; self.mind_store=mind_store
        self.perception=PerceptionStore(task_store.connection); self.mind=MindRuntime(mind_store)
        self.nervous=NervousRecordStore(task_store.connection); self.skills=CapabilityRegistry(task_store.connection)
        self.supervisor=GovernedTaskSupervisor(task_store,mind_store=mind_store)

    def prepare(self,*,request:object,source:str,project_boundary:str,desired_outcome:str,
                interpreted_scope:tuple[str,...],success_conditions:tuple[str,...],operation:str,domain:str,
                authority_basis:str,materiality:str,risk_class:str,expected_output:str,
                verification_requirement:str,retry_policy:str="RECONCILE_BEFORE_RETRY",
                constraints:tuple[str,...]=(),assumptions:tuple[str,...]=())->PreparedFlow:
        matches=self.skills.discover(operations=(operation,),domains=(domain,))
        if not matches: raise KernelRejected(f"no active capability matches operation={operation!r}, domain={domain!r}")
        match:CapabilityMatch=matches[0]; capability=match.capability
        if not capability.provider_ref: raise KernelRejected("selected executable capability has no provider/adapter binding")
        intent=self.perception.record_intent(content=request,source=source,scope=project_boundary)
        goal=self.mind.form_goal(intent_ref=intent.intent_id,desired_outcome=desired_outcome,interpreted_scope=interpreted_scope,
            success_conditions=success_conditions,authority_basis=authority_basis,materiality=materiality,risk_class=risk_class,
            constraints=constraints,assumptions=assumptions,uncertainty=KnowledgeState.UNVERIFIED)
        decision=self.mind.decide(goal_ref=goal.goal_id,question="Which registered capability should execute this outcome?",
            conclusion={"capability_ref":capability.capability_id,"version":capability.version,"provider_ref":capability.provider_ref},
            rationale="Selected from the active capability registry by required operation and domain.",authority_basis=authority_basis,
            uncertainty=KnowledgeState.CONFIRMED,reversibility="REVERSIBLE")
        task_id=f"task:{uuid.uuid4()}"; plan_id=f"plan:{uuid.uuid4()}"; step_id=f"step:{uuid.uuid4()}"; context_id=f"context:{uuid.uuid4()}"; assignment_id=f"assignment:{uuid.uuid4()}"
        step=self.nervous.create_step(step_id=step_id,task_ref=task_id,plan_ref=plan_id,plan_revision=1,purpose=desired_outcome,
            required_capabilities=(capability.capability_id,),expected_output=expected_output,authority_class=risk_class,
            verification_requirement=verification_requirement,retry_policy=retry_policy,state=StepState.READY)
        plan=self.mind.plan(goal_ref=goal.goal_id,decision_ref=decision.decision_id,step_refs=(step.step_id,),
            checkpoints=("authority","effect-reconciliation","completion"),recovery_options=("reconcile","replan","block"),
            completion_path=success_conditions,reason="Execute the selected capability under canonical authority and evidence gates.",plan_id=plan_id)
        context=self.nervous.create_context_manifest(manifest_id=context_id,task_ref=task_id,isolation_boundary=project_boundary,
            entries=(ContextEntry(source_ref=intent.intent_id,scope=project_boundary,authority=authority_basis,freshness="CURRENT",
                trust_state="CONFIRMED",sensitivity=intent.sensitivity,inclusion_reason="The current user request defines the outcome and scope.",
                isolation_boundary=project_boundary),))
        assignment=SpecialistAssignment(assignment_id=assignment_id,task_ref=task_id,step_ref=step.step_id,project_boundary=project_boundary,
            required_capability=capability.capability_id,context_manifest_ref=context.manifest_id,expected_output_contract=expected_output,
            authority_envelope_ref="UNBOUND",allowed_tools=(capability.provider_ref,),deadline=None,budget={},evidence_requirements=success_conditions)
        return PreparedFlow(intent.intent_id,goal.goal_id,decision.decision_id,plan.plan_id,step.step_id,context.manifest_id,capability.capability_id,assignment)

    def open(self,prepared:PreparedFlow,envelope:AuthorityEnvelope,*,worker_id:str,now:str|None=None):
        if envelope.task_ref!=prepared.assignment.task_ref: raise KernelRejected("authority envelope belongs to a different Task")
        if set(prepared.assignment.allowed_tools)-set(envelope.tool_boundary): raise KernelRejected("authority envelope does not grant the selected capability adapter")
        assignment=SpecialistAssignment(**{**prepared.assignment.__dict__,"authority_envelope_ref":envelope.envelope_id})
        return self.supervisor.open_flow(task_id=assignment.task_ref,goal_ref=prepared.goal_ref,plan_ref=prepared.plan_ref,
            assignment=assignment,envelope=envelope,worker_id=worker_id,now=now)
