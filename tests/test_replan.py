import unittest
from dataclasses import replace

from bro_runtime import (
    ActionRequest, AdapterResult, AssignmentState, AuthorityEnvelope, BROKernel,
    BoundaryViolation, Capability, CapabilityKind, CapabilityStatus, EffectState,
    EvidenceFreshness, EvidenceValidity, SQLiteMindStore, SQLiteTaskStore, StepRequest,
    StepState, complete_multistep, continue_multistep, evidence_scope, open_multistep,
    open_replanned_step, prepare_multistep, replan_from_observation, settle_multistep,
)
from bro_runtime.evidence_verification import EvidenceObservation, EvidenceVerifier, VerificationResult

T0="2026-09-01T00:00:00Z"; T1="2026-09-01T00:00:01Z"

class ObservationReplanTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        for cid,operation,domain,provider in (("cap:crm","write","crm","adapter:crm"),("cap:notify","send","notification","adapter:notify"),("cap:verify","inspect","crm","adapter:verify")):
            self.kernel.skills.register(Capability(cid,1,CapabilityKind.TOOL_ADAPTER,cid,cid,(operation,),(domain,),None,f"artifact:{cid}",(),(operation,),("inspect",),provider,None,CapabilityStatus.ACTIVE,T0))
        self.kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:replan-test",
            lambda _observation: VerificationResult(EvidenceValidity.VALID,EvidenceFreshness.CURRENT,{"verified":True}),
        ))
        self.kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:replan-stale",
            lambda _observation: VerificationResult(EvidenceValidity.VALID,EvidenceFreshness.STALE,{"verified":True}),
        ))
        self.kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:replan-invalid",
            lambda _observation: VerificationResult(EvidenceValidity.UNVERIFIED,EvidenceFreshness.CURRENT,{"verified":False}),
        ))
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
        return EvidenceObservation(criterion,"inspection",key,{"ok":True},"read-back",True,evidence_scope("BRO",prepared.task_ref))
    def reality(self, claim=None):
        return EvidenceObservation(
            "current routing reality",
            "provider-readback",
            "crm:read-back",
            {"query":"routing configuration","adapter":"adapter:crm"},
            "registered-provider-readback",
            claim or {"owner_channel":"ops-alerts","old_channel":"sales-owner"},
            evidence_scope("BRO",self.prepared.task_ref),
        )
    def execute_settle(self,prepared,binding,key,operation,target,adapter,criterion,output):
        self.kernel.supervisor._execute_registered_provider(binding,self.request(prepared,key,operation,target,adapter),executor=adapter,interface_version="1",adapter=lambda _:AdapterResult("ok",EffectState.CONFIRMED),now=T1)
        settle_multistep(self.kernel,prepared,binding,key,result_state=AssignmentState.SUCCEEDED,output_ref=output,observations=(("IMMUNE:replan-test",self.evidence(prepared,key,criterion)),),now=T1)
    def routed(self):
        binding=open_multistep(self.kernel,self.prepared,self.envelope(self.prepared,"route","write","crm:lead-routing","adapter:crm"),worker_id="worker:route",now=T1)
        self.execute_settle(self.prepared,binding,"route","write","crm:lead-routing","adapter:crm","lead routed","artifact:routing")
        return binding
    def replacements(self):
        return (
            StepRequest("notify-current","Notify current owner channel","send","notification","artifact:notification-current","inspect current notification"),
            StepRequest("verify-current","Verify changed workflow","inspect","crm","artifact:acceptance-current","acceptance check",("notify-current",)),
        )
    def replan(self):
        return replan_from_observation(
            self.kernel,self.prepared,verifier_id="IMMUNE:replan-test",observation=self.reality(),
            replacements=self.replacements(),now=T1,
        )

    def test_verified_current_observation_supersedes_unfinished_route_and_completes(self):
        self.routed()
        old_notify=self.prepared.step("notify").step_ref; old_verify=self.prepared.step("verify").step_ref
        result=self.replan()
        revised=result.prepared
        self.assertEqual(result.prior_plan_revision,1); self.assertEqual(result.plan_revision,2)
        observed=self.kernel.perception.observation(result.observation_ref)
        self.assertEqual(observed.trust_state,"CONFIRMED")
        self.assertEqual(observed.raw_result_ref,result.evidence_ref)
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
        self.assertEqual(self.kernel.mind_store.plan(revised.plan_ref).revision,2)

    def test_stale_or_unverified_evidence_cannot_auto_replan(self):
        self.routed()
        for verifier in ("IMMUNE:replan-stale","IMMUNE:replan-invalid"):
            with self.assertRaisesRegex(Exception,"VALID CURRENT"):
                replan_from_observation(
                    self.kernel,self.prepared,verifier_id=verifier,observation=self.reality({"maybe":"changed"}),
                    replacements=self.replacements(),now=T1,
                )
        self.assertEqual(self.kernel.mind_store.plan(self.prepared.plan_ref).revision,1)

    def test_unknown_verifier_cannot_assert_confirmed_replan_reality(self):
        self.routed()
        with self.assertRaisesRegex(Exception,"unknown evidence verifier"):
            replan_from_observation(
                self.kernel,self.prepared,verifier_id="caller:self-asserted",observation=self.reality(),
                replacements=self.replacements(),now=T1,
            )
        self.assertEqual(self.kernel.mind_store.plan(self.prepared.plan_ref).revision,1)

    def test_expired_authority_blocks_replanned_step_before_claim(self):
        self.routed()
        result=self.replan()
        expired=replace(
            self.envelope(result.prepared,"notify-current","send","notification:ops-alerts","adapter:notify"),
            expires_at=T1,
        )
        with self.assertRaisesRegex(BoundaryViolation,"expired"):
            open_replanned_step(self.kernel,result,expired,worker_id="worker:notify",step_key="notify-current",now=T1)
        assignment=self.kernel.supervisor.assignments.get_assignment(result.prepared.step("notify-current").assignment.assignment_id)
        self.assertEqual(assignment["state"],AssignmentState.READY)
        self.assertEqual(self.tasks.fetch_task(result.prepared.task_ref)["state"],"BLOCKED")

    def test_stale_prepared_plan_cannot_replan_current_revision(self):
        self.routed()
        result=self.replan()
        revised=result.prepared
        binding=open_replanned_step(
            self.kernel,result,self.envelope(revised,"notify-current","send","notification:ops-alerts","adapter:notify"),
            worker_id="worker:notify",step_key="notify-current",now=T1,
        )
        self.execute_settle(revised,binding,"notify-current","send","notification:ops-alerts","adapter:notify","owner notified","artifact:notification-current")
        with self.assertRaisesRegex(Exception,"stale Plan revision"):
            replan_from_observation(
                self.kernel,self.prepared,verifier_id="IMMUNE:replan-test",observation=self.reality({"owner_channel":"other"}),
                replacements=self.replacements(),now=T1,
            )
        self.assertEqual(self.kernel.mind_store.plan(revised.plan_ref).revision,2)

if __name__=="__main__": unittest.main()
