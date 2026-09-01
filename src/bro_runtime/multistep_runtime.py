"""Canonical multi-step plan composition for BROKernel."""
from __future__ import annotations
import uuid
from .mind import KnowledgeState
from .multistep import MultiStepRejected, PreparedPlan, PreparedStep, StepRequest, ready_step_refs, validate_graph
from .nervous_records import ContextEntry, StepState
from .orchestration import SpecialistAssignment


def prepare_multistep(kernel, *, request:object, source:str, project_boundary:str, desired_outcome:str,
                      interpreted_scope:tuple[str,...], success_conditions:tuple[str,...], authority_basis:str,
                      materiality:str, risk_class:str, steps:tuple[StepRequest,...], constraints:tuple[str,...]=(),
                      assumptions:tuple[str,...]=())->PreparedPlan:
    order=validate_graph(steps); by_key={s.key:s for s in steps}
    resolved={}
    for key in order:
        req=by_key[key]
        matches=kernel.skills.discover(operations=(req.operation,),domains=(req.domain,))
        if not matches: raise MultiStepRejected(f"no active capability matches step={key!r}, operation={req.operation!r}, domain={req.domain!r}")
        cap=matches[0].capability
        if not cap.provider_ref: raise MultiStepRejected(f"step {key!r} capability has no provider/adapter binding")
        resolved[key]=cap
    intent=kernel.perception.record_intent(content=request,source=source,scope=project_boundary)
    goal=kernel.mind.form_goal(intent_ref=intent.intent_id,desired_outcome=desired_outcome,interpreted_scope=interpreted_scope,
        success_conditions=success_conditions,authority_basis=authority_basis,materiality=materiality,risk_class=risk_class,
        constraints=constraints,assumptions=assumptions,uncertainty=KnowledgeState.UNVERIFIED)
    conclusion={key:{"capability_ref":resolved[key].capability_id,"version":resolved[key].version,"provider_ref":resolved[key].provider_ref} for key in order}
    decision=kernel.mind.decide(goal_ref=goal.goal_id,question="Which registered capabilities should execute the ordered outcome steps?",
        conclusion=conclusion,rationale="Selected active capabilities for every dependency-ordered step without granting authority.",
        authority_basis=authority_basis,uncertainty=KnowledgeState.CONFIRMED,reversibility="REVERSIBLE")
    task_id=f"task:{uuid.uuid4()}"; plan_id=f"plan:{uuid.uuid4()}"; context_id=f"context:{uuid.uuid4()}"; route_id=f"route:{uuid.uuid4()}"
    step_ids={key:f"step:{uuid.uuid4()}" for key in order}
    created={}
    for key in order:
        req=by_key[key]; cap=resolved[key]; deps=tuple(step_ids[d] for d in req.dependencies)
        created[key]=kernel.nervous.create_step(step_id=step_ids[key],task_ref=task_id,plan_ref=plan_id,plan_revision=1,
            purpose=req.purpose,dependencies=deps,required_capabilities=(cap.capability_id,),expected_output=req.expected_output,
            authority_class=req.risk_class,verification_requirement=req.verification_requirement,retry_policy=req.retry_policy,
            state=StepState.READY if not deps else StepState.PLANNED)
    plan=kernel.mind.plan(goal_ref=goal.goal_id,decision_ref=decision.decision_id,step_refs=tuple(step_ids[key] for key in order),
        checkpoints=("authority-per-step","dependency-boundary","effect-reconciliation","completion"),
        recovery_options=("reconcile","replan","block"),completion_path=success_conditions,
        reason="Execute dependency-ordered canonical Steps with authority evaluated independently per effect.",plan_id=plan_id)
    entries=[ContextEntry(intent.intent_id,project_boundary,authority_basis,"CURRENT","CONFIRMED",intent.sensitivity,
        "The current request defines the multi-step outcome and scope.",project_boundary)]
    for retrieval in kernel.memory.retrieve(scope=project_boundary):
        m=retrieval.record; entries.append(ContextEntry(m.memory_id,m.scope,m.authority_ref or "MEMORY_SUPPORT_ONLY",m.freshness.value,
            "UNVERIFIED",m.sensitivity,retrieval.reason,project_boundary))
    context=kernel.nervous.create_context_manifest(manifest_id=context_id,task_ref=task_id,isolation_boundary=project_boundary,entries=tuple(entries))
    prepared=[]
    for key in order:
        req=by_key[key]; cap=resolved[key]; step=created[key]
        assignment=SpecialistAssignment(f"assignment:{uuid.uuid4()}",task_id,step.step_id,project_boundary,cap.capability_id,
            context.manifest_id,req.expected_output,"UNBOUND",(cap.provider_ref,),None,{},success_conditions)
        prepared.append(PreparedStep(key,step.step_id,cap.capability_id,assignment))
    return PreparedPlan(task_id,intent.intent_id,goal.goal_id,decision.decision_id,plan.plan_id,context.manifest_id,route_id,tuple(prepared))


def ready_multistep(kernel,prepared:PreparedPlan)->tuple[PreparedStep,...]:
    ready=set(ready_step_refs(prepared,kernel.nervous))
    return tuple(item for item in prepared.steps if item.step_ref in ready)
