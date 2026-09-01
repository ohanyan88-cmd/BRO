import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.continuity import ContinuityStatus, HeartRecord, SelfRecord
from bro_runtime.feet import RouteState
from bro_runtime.immune import AuthorityEnvelope, Evidence, EvidenceFreshness, EvidenceValidity, evidence_scope
from bro_runtime.kernel import BROKernel, KernelRejected
from bro_runtime.memory import MemoryClass, MemoryFreshness
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.supervision import NextAction
from bro_runtime.task_runtime import SQLiteTaskStore
from bro_runtime.voice import VoiceState

T0="2026-09-01T00:00:00Z"; T1="2026-09-01T00:00:01Z"; T2="2026-09-01T00:01:00Z"


class KernelIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        self.kernel.skills.register(Capability(
            capability_id="cap:crm-write",version=1,kind=CapabilityKind.TOOL_ADAPTER,name="CRM writer",
            description="Writes governed CRM automations",operations=("write",),domains=("crm",),
            input_contract_ref=None,output_contract_ref="artifact:automation",dependency_refs=(),
            authority_requirements=("write",),evidence_capabilities=("inspect",),provider_ref="adapter:crm",
            health_ref=None,status=CapabilityStatus.ACTIVE,recorded_at=T0))

    def prepare(self, **changes):
        values=dict(request="Automate lead routing",source="user:gev",project_boundary="BRO",
            desired_outcome="Working lead routing automation",interpreted_scope=("crm","lead-routing"),
            success_conditions=("automation works",),operation="write",domain="crm",authority_basis="user request",
            materiality="MATERIAL",risk_class="R2",expected_output="artifact:automation",
            verification_requirement="inspect deployed routing")
        values.update(changes)
        return self.kernel.prepare(**values)

    def envelope(self, task_id):
        return AuthorityEnvelope(envelope_id="auth:1",version=1,principal="BRO",proof_ref="proof:user",
            authority_source="user",operation="write",target="crm:lead-routing",
            allowed_scope=("operation:write","target:crm:lead-routing",task_id,"project:BRO"),prohibited_scope=(),
            task_ref=task_id,risk_class="R2",valid_from=T0,expires_at="2026-09-02T00:00:00Z",revocation_ref=None,
            environment="prod",tool_boundary=("adapter:crm",),decision="ALLOWED",
            reason="explicit bounded user request",audit_ref="audit:1")

    def request(self, prepared):
        return ActionRequest(action_request_id="action:1",task_ref=prepared.assignment.task_ref,
            intended_effect="deploy lead routing",operation="write",target="crm:lead-routing",environment="prod",
            adapter_id="adapter:crm",input_parameters={"rule":"route"},authority_envelope_ref="auth:1",risk_class="R2",
            reversibility="REVERSIBLE",idempotency_key="lead-routing-v1",idempotency_guaranteed=True,
            expected_result="deployed",verification_requirements=("inspect",),
            assignment_ref=prepared.assignment.assignment_id,project_boundary="BRO")

    def seed_continuity(self):
        self_body=dict(self_id="BRO",schema_version="0.1.0",identity_version=1,product_name="BRO",
            identity_statement="One persistent AI operating partner",character_traits=("direct",),
            stable_values=("truth",),behavioral_invariants=("verify before done",),voice_baseline_ref="voice:default",
            visual_identity_ref=None,continuity_policy_ref="policy:continuity",provider_independence=True,
            effective_from=T0,supersedes=None,authority_record_ref="authority:self",integrity_digest="",
            status=ContinuityStatus.ACTIVE)
        self_body["integrity_digest"]=self.kernel.continuity.digest(self_body)
        self.kernel.continuity.record_self(SelfRecord(**self_body))
        heart_body=dict(heart_id="heart:gev",schema_version="0.1.0",heart_version=1,relationship_scope="relationship:gev",
            stance_principles=("care without flattery",),care_rules=("be useful",),loyalty_rules=("do not blindly agree",),
            honesty_rules=("tell the truth",),disagreement_rules=("challenge material errors",),warmth_rules=("stay warm",),
            privacy_rules=("keep relationship-private context private",),non_flattery_rules=("no empty praise",),
            non_deception_rules=("never fake completion",),long_horizon_commitments=("preserve continuity",),
            private_foundation_refs=("private:foundation",),expression_constraints_ref="voice:default",effective_from=T0,
            supersedes=None,authority_record_ref="authority:heart",integrity_digest="",status=ContinuityStatus.ACTIVE)
        heart_body["integrity_digest"]=self.kernel.continuity.digest(heart_body)
        self.kernel.continuity.record_heart(HeartRecord(**heart_body))

    def test_missing_capability_fails_before_task_execution(self):
        with self.assertRaises(KernelRejected):
            self.kernel.prepare(request="x",source="user",project_boundary="BRO",desired_outcome="x",
                interpreted_scope=("x",),success_conditions=("x",),operation="delete",domain="unknown",
                authority_basis="user",materiality="MATERIAL",risk_class="R2",expected_output="artifact:x",
                verification_requirement="inspect")
        self.assertEqual(self.tasks.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],0)

    def test_prepare_uses_minimal_continuity_and_memory_as_supporting_context(self):
        self.seed_continuity()
        memory=self.kernel.memory.store(memory_class=MemoryClass.PROJECT,subject="crm-routing",scope="BRO",
            content={"prior_rule":"round-robin"},source_owner="MEMORY",source_ref="decision:old",authority_ref=None,
            sensitivity="NORMAL",confidence="HIGH",freshness=MemoryFreshness.CURRENT,retention="PROJECT",
            integrity={"digest":"memory-1"})
        prepared=self.prepare(relationship_scope="relationship:gev")
        self.assertEqual(prepared.continuity.self_ref,"BRO")
        self.assertEqual(prepared.memory_refs,(memory.memory_id,))
        context=self.kernel.nervous.context_manifest(prepared.context_manifest_ref)
        memory_entry=next(entry for entry in context.entries if entry.source_ref==memory.memory_id)
        self.assertEqual(memory_entry.trust_state,"UNVERIFIED")
        self.assertIn("requires source/reality verification",memory_entry.inclusion_reason)
        self.assertTrue(any(entry.source_ref.startswith("SELF:BRO@") for entry in context.entries))
        self.assertFalse(any("private:foundation" in entry.source_ref for entry in context.entries))

    def test_recovery_reconstructs_next_step_without_replaying_command(self):
        prepared=self.prepare(); task_id=prepared.assignment.task_ref
        self.kernel.open(prepared,self.envelope(task_id),worker_id="specialist:automation",now=T1)
        self.kernel.supervisor.assignments.expire_leases(T2)
        recovery=self.kernel.recover(task_id,prepared.route_id)
        self.assertEqual(recovery.next_step.action,NextAction.CLAIM_ASSIGNMENT)
        self.assertEqual(recovery.route.state,RouteState.ACTIVE)
        self.assertEqual(self.kernel.supervisor.actions.requests_for_task(task_id),[])

    def test_outcome_request_reaches_verified_terminal_state_and_truthful_voice(self):
        prepared=self.prepare(); task_id=prepared.assignment.task_ref
        binding=self.kernel.open(prepared,self.envelope(task_id),worker_id="specialist:automation",now=T1)
        self.assertEqual(self.kernel.feet.latest(prepared.route_id).state,RouteState.ACTIVE)
        attempt=self.kernel.supervisor._execute_registered_provider(binding,self.request(prepared),executor="specialist:automation",
            interface_version="1",adapter=lambda _:AdapterResult("deployed",EffectState.CONFIRMED),now=T1)
        self.assertEqual(attempt["effect_state"],"CONFIRMED")
        scope=evidence_scope("BRO",task_id)
        self.kernel.supervisor.reconcile(binding,"action:1",EffectState.CONFIRMED,
            Evidence("evidence:effect","effect reconciled","inspection","crm",{"record":"routing"},"read-back",T1,
                True,scope,(),EvidenceValidity.VALID,EvidenceFreshness.CURRENT,"IMMUNE_SYSTEM"),now=T1)
        self.kernel.supervisor.settle_assignment(binding,result_state=AssignmentState.SUCCEEDED,
            output_ref="artifact:routing-v1",evidence=(Evidence("evidence:criterion","automation works","inspection","crm",
                {"record":"routing"},"functional-check",T1,True,scope,(),EvidenceValidity.VALID,
                EvidenceFreshness.CURRENT,"IMMUNE_SYSTEM"),),now=T1)
        manifest=self.kernel.complete(prepared,binding,outcome_statement="Lead routing automation is deployed and verified",
            required_criteria=("automation works",),now=T1)
        self.assertTrue(manifest.is_verified())
        task=self.kernel.supervisor.canonical_task(task_id)
        self.assertEqual(task["state"],"COMPLETED")
        self.assertEqual(task["completion_manifest_ref"],manifest.manifest_id)
        self.assertEqual(self.kernel.feet.latest(prepared.route_id).state,RouteState.COMPLETED)
        voice=self.kernel.project_voice(task_id)
        self.assertEqual(voice.state,VoiceState.COMPLETED)
        self.assertEqual(self.kernel.perception.intent(prepared.intent_ref).content,"Automate lead routing")
        self.assertEqual(self.kernel.mind_store.goal(prepared.goal_ref).intent_ref,prepared.intent_ref)
        self.assertEqual(self.kernel.mind_store.plan(prepared.plan_ref).step_refs,(prepared.step_ref,))

if __name__=="__main__": unittest.main()
