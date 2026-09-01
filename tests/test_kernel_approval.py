import unittest

from bro_runtime import (
    Approval, ApprovalDecision, ApprovalRequired, AuthorityEnvelope, BROKernel,
    Capability, CapabilityKind, CapabilityStatus, RevocationState, RouteState,
    SQLiteMindStore, SQLiteTaskStore, StepState,
)

T0="2026-09-01T00:00:00Z"; T1="2026-09-01T00:00:01Z"

class KernelApprovalResumeTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        self.kernel.skills.register(Capability("cap:crm-write",1,CapabilityKind.TOOL_ADAPTER,"CRM writer","CRM writes",("write",),("crm",),None,"artifact:crm",(),("write",),("inspect",),"adapter:crm",None,CapabilityStatus.ACTIVE,T0))
    def prepared(self):
        return self.kernel.prepare(request="deploy rule",source="user",project_boundary="BRO",desired_outcome="rule deployed",interpreted_scope=("crm",),success_conditions=("works",),operation="write",domain="crm",authority_basis="user",materiality="MATERIAL",risk_class="R3",expected_output="artifact:crm",verification_requirement="inspect")
    def envelope(self,task):
        return AuthorityEnvelope("auth:approval",1,"BRO","proof:user","user","write","crm:rule",("operation:write","target:crm:rule",task,"project:BRO"),(),task,"R3",T0,"2026-09-02T00:00:00Z",None,"prod",("adapter:crm",),"APPROVAL_REQUIRED","approval needed","audit:1")
    def approval(self,task,step):
        return Approval("approval:1","user","proof:approval","write","crm:rule",("operation:write","target:crm:rule",task,"project:BRO"),"R3",("writes CRM",),(),T0,"2026-09-02T00:00:00Z",ApprovalDecision.APPROVED,RevocationState.ACTIVE,task,None,"audit:approval",step)
    def test_kernel_resume_preserves_same_task_step_route_and_cannot_replay_consumed_approval(self):
        prepared=self.prepared(); task=prepared.assignment.task_ref
        with self.assertRaises(ApprovalRequired): self.kernel.open(prepared,self.envelope(task),worker_id="worker",now=T0)
        self.assertEqual(self.tasks.fetch_task(task)["state"],"BLOCKED")
        self.assertEqual(self.kernel.nervous.step(prepared.step_ref).state,StepState.BLOCKED)
        self.assertEqual(self.kernel.feet.latest(prepared.route_id).state,RouteState.BLOCKED)
        self.kernel.supervisor.approvals.record(self.approval(task,prepared.step_ref))
        binding=self.kernel.resume_with_approval(prepared,"approval:1","worker",now=T1)
        self.assertEqual(binding.task_id,task); self.assertEqual(prepared.assignment.task_ref,task)
        self.assertEqual(self.tasks.fetch_task(task)["state"],"EXECUTING")
        self.assertEqual(self.kernel.nervous.step(prepared.step_ref).state,StepState.ACTIVE)
        self.assertEqual(self.kernel.feet.latest(prepared.route_id).state,RouteState.ACTIVE)
        with self.assertRaises(Exception): self.kernel.resume_with_approval(prepared,"approval:1","worker",now=T1)

if __name__=="__main__": unittest.main()
