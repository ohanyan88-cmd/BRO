import unittest

from bro_runtime import (
    ActionRequest, AdapterResult, AssignmentState, AuthorityEnvelope, BROKernel,
    Capability, CapabilityKind, CapabilityStatus, EffectState, EvidenceFreshness,
    EvidenceValidity, RouteState, SQLiteMindStore, SQLiteTaskStore, StepRequest,
    StepState, complete_multistep, continue_multistep, evidence_scope, open_multistep,
    prepare_multistep, settle_multistep,
)
from bro_runtime.evidence_verification import EvidenceObservation, EvidenceVerifier, VerificationResult

T0="2026-09-01T00:00:00Z"; T1="2026-09-01T00:00:01Z"

class MultiStepExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        for cid,operation,domain,provider in (("cap:crm","write","crm","adapter:crm"),("cap:notify","send","notification","adapter:notify"),("cap:verify","inspect","crm","adapter:verify")):
            self.kernel.skills.register(Capability(cid,1,CapabilityKind.TOOL_ADAPTER,cid,cid,(operation,),(domain,),None,f"artifact:{cid}",(),(operation,),("inspect",),provider,None,CapabilityStatus.ACTIVE,T0))
        self.kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:multistep-test",
            lambda _observation: VerificationResult(EvidenceValidity.VALID,EvidenceFreshness.CURRENT,{"verified":True}),
        ))
        self.prepared=prepare_multistep(self.kernel,request="Automate lead handling",source="user",project_boundary="BRO",desired_outcome="Lead handling automation works end-to-end",interpreted_scope=("crm","notification"),success_conditions=("lead routed","owner notified","acceptance verified"),authority_basis="user request",materiality="MATERIAL",risk_class="R2",steps=(
            StepRequest("route","Route lead","write","crm","artifact:routing","inspect routing"),
            StepRequest("notify","Notify owner","send","notification","artifact:notification","inspect notification",("route",)),
            StepRequest("verify","Verify workflow","inspect","crm","artifact:acceptance","acceptance check",("route","notify")),))
    def envelope(self,key,operation,target,adapter):
        return AuthorityEnvelope(f"auth:{key}",1,"BRO","proof:user","user",operation,target,(f"operation:{operation}",f"target:{target}",self.prepared.task_ref,"project:BRO"),(),self.prepared.task_ref,"R2",T0,"2026-09-02T00:00:00Z",None,"prod",(adapter,),"ALLOWED","bounded user request",f"audit:{key}")
    def request(self,key,operation,target,adapter):
        step=self.prepared.step(key)
        return ActionRequest(f"action:{key}",self.prepared.task_ref,f"perform {key}",operation,target,"prod",adapter,{"key":key},f"auth:{key}","R2","REVERSIBLE",f"idem:{key}",True,"ok",("inspect",),step.assignment.assignment_id,"BRO")
    def evidence(self,key,criterion):
        return EvidenceObservation(criterion,"inspection",key,{"ok":True},"read-back",True,evidence_scope("BRO",self.prepared.task_ref))
    def execute_and_settle(self,binding,key,operation,target,adapter,criterion,output):
        attempt=self.kernel.supervisor._execute_registered_provider(binding,self.request(key,operation,target,adapter),executor=adapter,interface_version="1",adapter=lambda _:AdapterResult("ok",EffectState.CONFIRMED),now=T1)
        self.assertEqual(attempt["effect_state"],"CONFIRMED")
        settle_multistep(self.kernel,self.prepared,binding,key,result_state=AssignmentState.SUCCEEDED,output_ref=output,observations=(("IMMUNE:multistep-test",self.evidence(key,criterion)),),now=T1)
    def test_three_step_outcome_executes_on_one_task_and_completes_verified(self):
        route_auth=self.envelope("route","write","crm:lead-routing","adapter:crm")
        binding=open_multistep(self.kernel,self.prepared,route_auth,worker_id="worker:route",now=T1)
        self.execute_and_settle(binding,"route","write","crm:lead-routing","adapter:crm","lead routed","artifact:routing")
        self.assertEqual(self.kernel.nervous.step(self.prepared.step("route").step_ref).state,StepState.SUCCEEDED)
        notify_auth=self.envelope("notify","send","notification:sales-owner","adapter:notify")
        binding=continue_multistep(self.kernel,self.prepared,binding,"notify",notify_auth,worker_id="worker:notify",now=T1)
        self.execute_and_settle(binding,"notify","send","notification:sales-owner","adapter:notify","owner notified","artifact:notification")
        verify_auth=self.envelope("verify","inspect","crm:lead-routing","adapter:verify")
        binding=continue_multistep(self.kernel,self.prepared,binding,"verify",verify_auth,worker_id="worker:verify",now=T1)
        self.execute_and_settle(binding,"verify","inspect","crm:lead-routing","adapter:verify","acceptance verified","artifact:acceptance")
        manifest=complete_multistep(self.kernel,self.prepared,binding,outcome_statement="Lead routing, notification, and acceptance verification completed",required_criteria=("lead routed","owner notified","acceptance verified"),now=T1)
        self.assertTrue(manifest.is_verified())
        self.assertEqual(self.tasks.fetch_task(self.prepared.task_ref)["state"],"COMPLETED")
        self.assertEqual(self.kernel.feet.latest(self.prepared.route_id).state,RouteState.COMPLETED)
        self.assertTrue(all(self.kernel.nervous.step(item.step_ref).state is StepState.SUCCEEDED for item in self.prepared.steps))
        assignments=self.kernel.supervisor.assignments.assignments_for_task(self.prepared.task_ref)
        self.assertEqual(len(assignments),3)
        self.assertEqual([row["state"] for row in assignments],["SUCCEEDED","SUCCEEDED","SUCCEEDED"])

if __name__=="__main__": unittest.main()
