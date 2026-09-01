import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.immune import AuthorityEnvelope, Evidence, EvidenceFreshness, EvidenceValidity, evidence_scope
from bro_runtime.kernel import BROKernel, KernelRejected
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.task_runtime import SQLiteTaskStore

T0="2026-09-01T00:00:00Z"; T1="2026-09-01T00:00:01Z"

class KernelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        self.kernel.skills.register(Capability(capability_id="cap:crm-write",version=1,kind=CapabilityKind.TOOL_ADAPTER,name="CRM writer",description="Writes governed CRM automations",operations=("write",),domains=("crm",),input_contract_ref=None,output_contract_ref="artifact:automation",dependency_refs=(),authority_requirements=("write",),evidence_capabilities=("inspect",),provider_ref="adapter:crm",health_ref=None,status=CapabilityStatus.ACTIVE,recorded_at=T0))
    def prepare(self):
        return self.kernel.prepare(request="Automate lead routing",source="user:gev",project_boundary="BRO",desired_outcome="Working lead routing automation",interpreted_scope=("crm","lead-routing"),success_conditions=("automation works",),operation="write",domain="crm",authority_basis="user request",materiality="MATERIAL",risk_class="R2",expected_output="artifact:automation",verification_requirement="inspect deployed routing")
    def test_missing_capability_fails_before_task_execution(self):
        with self.assertRaises(KernelRejected): self.kernel.prepare(request="x",source="user",project_boundary="BRO",desired_outcome="x",interpreted_scope=("x",),success_conditions=("x",),operation="delete",domain="unknown",authority_basis="user",materiality="MATERIAL",risk_class="R2",expected_output="artifact:x",verification_requirement="inspect")
        self.assertEqual(self.tasks.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],0)
    def test_outcome_request_reaches_verified_terminal_state(self):
        prepared=self.prepare(); task_id=prepared.assignment.task_ref
        envelope=AuthorityEnvelope(envelope_id="auth:1",version=1,principal="BRO",proof_ref="proof:user",authority_source="user",operation="write",target="crm:lead-routing",allowed_scope=("operation:write","target:crm:lead-routing",task_id,"project:BRO"),prohibited_scope=(),task_ref=task_id,risk_class="R2",valid_from=T0,expires_at="2026-09-02T00:00:00Z",revocation_ref=None,environment="prod",tool_boundary=("adapter:crm",),decision="ALLOWED",reason="explicit bounded user request",audit_ref="audit:1")
        binding=self.kernel.open(prepared,envelope,worker_id="specialist:automation",now=T1)
        request=ActionRequest(action_request_id="action:1",task_ref=task_id,intended_effect="deploy lead routing",operation="write",target="crm:lead-routing",environment="prod",adapter_id="adapter:crm",input_parameters={"rule":"route"},authority_envelope_ref="auth:1",risk_class="R2",reversibility="REVERSIBLE",idempotency_key="lead-routing-v1",idempotency_guaranteed=True,expected_result="deployed",verification_requirements=("inspect",),assignment_ref=prepared.assignment.assignment_id,project_boundary="BRO")
        attempt=self.kernel.supervisor.execute(binding,request,executor="specialist:automation",interface_version="1",adapter=lambda _:AdapterResult("deployed",EffectState.CONFIRMED),now=T1)
        self.assertEqual(attempt["effect_state"],"CONFIRMED")
        scope=evidence_scope("BRO",task_id)
        self.kernel.supervisor.reconcile(binding,"action:1",EffectState.CONFIRMED,Evidence("evidence:effect","effect reconciled","inspection","crm",{"record":"routing"},"read-back",T1,True,scope,(),EvidenceValidity.VALID,EvidenceFreshness.CURRENT,"IMMUNE_SYSTEM"),now=T1)
        self.kernel.supervisor.settle_assignment(binding,result_state=AssignmentState.SUCCEEDED,output_ref="artifact:routing-v1",evidence=(Evidence("evidence:criterion","automation works","inspection","crm",{"record":"routing"},"functional-check",T1,True,scope,(),EvidenceValidity.VALID,EvidenceFreshness.CURRENT,"IMMUNE_SYSTEM"),),now=T1)
        manifest=self.kernel.supervisor.complete(binding,outcome_statement="Lead routing automation is deployed and verified",required_criteria=("automation works",),now=T1)
        self.assertTrue(manifest.is_verified()); task=self.kernel.supervisor.canonical_task(task_id)
        self.assertEqual(task["state"],"COMPLETED"); self.assertEqual(task["completion_manifest_ref"],manifest.manifest_id)
        self.assertEqual(self.kernel.perception.intent(prepared.intent_ref).content,"Automate lead routing")
        self.assertEqual(self.kernel.mind_store.goal(prepared.goal_ref).intent_ref,prepared.intent_ref)
        self.assertEqual(self.kernel.mind_store.plan(prepared.plan_ref).step_refs,(prepared.step_ref,))

if __name__=="__main__": unittest.main()
