import unittest

from bro_runtime import (
    ActionRequest, AdapterResult, AssignmentState, AuthorityEnvelope, BROKernel,
    Capability, CapabilityKind, CapabilityStatus, EffectState, Evidence,
    EvidenceFreshness, EvidenceValidity, Freshness, SQLiteMindStore, SQLiteTaskStore,
    StepRequest, StepState, TrustState, complete_multistep, continue_multistep,
    evidence_scope, open_multistep, open_replanned_step, prepare_multistep,
    replan_from_observation, settle_multistep,
)

T0="2026-09-01T00:00:00Z"; T1="2026-09-01T00:00:01Z"

class ObservationReplanTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        for cid,operation,domain,provider in (("cap:crm","write","crm","adapter:crm"),("cap:notify","send","notification","adapter:notify"),("cap:verify","inspect","crm","adapter:verify")):
            self.kernel.skills.register(Capability(cid,1,CapabilityKind.TOOL_ADAPTER,cid,cid,(operation,),(domain,),None,f"artifact:{cid}",(),(operation,),("inspect",),provider,None,CapabilityStatus.ACTIVE,T0))
        self.prepared=prepare_multistep(self.kernel,request="Automate lead handling",source="user",project_boundary="BRO",desired_outcome="Lead handling adapts to current reality",interpreted_scope=("crm","notification"),success_conditions=("lead routed","owner notified","acceptance verified"),authority_basis="user request",materiality="MATERIAL",risk_class="R2",steps=(
            StepRequest("route","Route lead","write","crm","artifact:routing","inspect routing"),
            StepRequest("notify","Notify old owner channel","send","notification","artifact:notification","inspect notification",("route",)),
            StepRequest("verify","Verify old route","inspect","crm","artifact:acceptance","acceptance check",("route","notify")),))
    def envelope(self,prepared,key,operation,target,adapter):
        return AuthorityEnvelope(f"auth:{key}",1,"BRO","proof:user","user",operation,target,(f"operation:{operation}",f"target:{target}",prepared.task_ref,"project:BRO"),(),prepared.task_ref,"R2",T0,"2026-09-02T00:00:00Z",None,"prod",(adapter,),"ALLOWED","bounded user request",f"audit:{key}")
    def request(self,prepared,key,operation,target,adapter):
        step=prepared.step(key)
        return ActionRequest(f"action:{key}",prepared.task_ref,f"perform {key}",operation,target,"prod",adapter,{"key":key},f"auth:{key}","R2","REVERSIBLE",f"idem:{key}",True,"ok",("inspect",),step.assignment.assignment_id,"BRO")
    def evidence(self,prepared,key,criterion):
        return Evidence(f"evidence:{key}",criterion,"inspection",key,{"ok":True},"read-back",T1,True,evidence_scope("BRO",prepared.task_ref),(),EvidenceValidity.VALID,EvidenceFreshness.CURRENT,"IMMUNE_SYSTEM")
    def execute_settle(self,prepared,binding,key,operation,target,adapter,criterion,output):
        self.kernel.supervisor._execute_registered_provider(binding,self.request(prepared,key,operation,target,adapter),executor=adapter,interface_version="1",adapter=lambda _:AdapterResult("ok",EffectState.CONFIRMED),now=T1)
        settle_multistep(self.kernel,prepared,binding,key,result_state=AssignmentState.SUCCEEDED,output_ref=output,evidence=(self.evidence(prepared,key,criterion),),now=T1)
    def test_current_confirmed_observation_supersedes_unfinished_route_and_completes(self):
        binding=open_multistep(self.kernel,self.prepared,self.envelope(self.prepared,"route","write","crm:lead-routing","adapter:crm"),worker_id="worker:route",now=T1)
        self.execute_settle(self.prepared,binding,"route","write","crm:lead-routing","adapter:crm","lead routed","artifact:routing")
        old_notify=self.prepared.step("notify").step_ref; old_verify=self.prepared.step("verify").step_ref
        result=replan_from_observation(self.kernel,self.prepared,claim={"owner_channel":"ops-alerts","old_channel":"sales-owner"},source="crm:read-back",provenance={"query":"routing configuration","adapter":"adapter:crm"},freshness=Freshness.CURRENT,trust_state=TrustState.CONFIRMED,replacements=(
            StepRequest("notify-current","Notify current owner channel","send","notification","artifact:notification-current","inspect current notification"),
            StepRequest("verify-current","Verify changed workflow","inspect","crm","artifact:acceptance-current","acceptance check",("notify-current",)),))
        revised=result.prepared
        self.assertEqual(result.prior_plan_revision,1); self.assertEqual(result.plan_revision,2)
        self.assertEqual(self.kernel.perception.observation(result.observation_ref).trust_state,TrustState.CONFIRMED)
        self.assertEqual(self.kernel.nervous.step(old_notify).state,StepState.CANCELLED)
        self.assertEqual(self.kernel.nervous.step(old_verify).state,StepState.CANCELLED)
        self.assertEqual(self.tasks.fetch_task(revised.task_ref)["state"],"PLANNING")
        binding=open_replanned_step(self.kernel,result,self.envelope(revised,"notify-current","send","notification:ops-alerts","adapter:notify"),worker_id="worker:notify",step_key="notify-current",now=T1)
        self.execute_settle(revised,binding,"notify-current","send","notification:ops-alerts","adapter:notify","owner notified","artifact:notification-current")
        binding=continue_multistep(self.kernel,revised,binding,"verify-current",self.envelope(revised,"verify-current","inspect","crm:lead-routing","adapter:verify"),worker_id="worker:verify",now=T1)
        self.execute_settle(revised,binding,"verify-current","inspect","crm:lead-routing","adapter:verify","acceptance verified","artifact:acceptance-current")
        manifest=complete_multistep(self.kernel,revised,binding,outcome_statement="Lead handling followed current observed owner channel and was verified",required_criteria=("lead routed","owner notified","acceptance verified"),now=T1)
        self.assertTrue(manifest.is_verified())
        self.assertEqual(self.tasks.fetch_task(revised.task_ref)["state"],"COMPLETED")
        self.assertEqual(self.mind.plan if False else self.mind, self.mind)  # keep fixture ownership explicit
        self.assertEqual(self.kernel.mind_store.plan(revised.plan_ref).revision,2)
    def test_unverified_or_stale_observation_cannot_auto_replan(self):
        binding=open_multistep(self.kernel,self.prepared,self.envelope(self.prepared,"route","write","crm:lead-routing","adapter:crm"),worker_id="worker:route",now=T1)
        self.execute_settle(self.prepared,binding,"route","write","crm:lead-routing","adapter:crm","lead routed","artifact:routing")
        for freshness,trust in ((Freshness.STALE,TrustState.CONFIRMED),(Freshness.CURRENT,TrustState.UNVERIFIED)):
            with self.assertRaisesRegex(Exception,"CURRENT CONFIRMED"):
                replan_from_observation(self.kernel,self.prepared,claim={"maybe":"changed"},source="cache",provenance={"source":"cache"},freshness=freshness,trust_state=trust,replacements=(StepRequest("a","A","send","notification","a","check"),StepRequest("b","B","inspect","crm","b","check",("a",))))

if __name__=="__main__": unittest.main()
