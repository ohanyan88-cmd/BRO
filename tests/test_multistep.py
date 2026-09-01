import unittest

from bro_runtime import (
    BROKernel, Capability, CapabilityKind, CapabilityStatus, MultiStepRejected,
    SQLiteMindStore, SQLiteTaskStore, StepRequest, StepState,
    prepare_multistep, ready_multistep,
)

T0="2026-09-01T00:00:00Z"

class MultiStepPlanningTests(unittest.TestCase):
    def setUp(self):
        self.tasks=SQLiteTaskStore(); self.mind=SQLiteMindStore(); self.kernel=BROKernel(self.tasks,self.mind)
        self.addCleanup(self.tasks.close); self.addCleanup(self.mind.close)
        for cid,name,operation,domain,provider in (
            ("cap:crm","CRM writer","write","crm","adapter:crm"),
            ("cap:notify","Notifier","send","notification","adapter:notify"),
            ("cap:verify","Verifier","inspect","crm","adapter:verify"),
        ):
            self.kernel.skills.register(Capability(cid,1,CapabilityKind.TOOL_ADAPTER,name,name,(operation,),(domain,),None,f"artifact:{cid}",(),(operation,),("inspect",),provider,None,CapabilityStatus.ACTIVE,T0))
    def requests(self):
        return (
            StepRequest("route","Deploy lead routing","write","crm","artifact:routing","inspect routing"),
            StepRequest("notify","Notify sales owner","send","notification","artifact:notification","inspect notification",("route",)),
            StepRequest("verify","Verify routed lead and notification","inspect","crm","evidence:acceptance","acceptance check",("route","notify")),
        )
    def prepare(self,steps=None):
        return prepare_multistep(self.kernel,request="Automate lead handling",source="user",project_boundary="BRO",
            desired_outcome="Lead routing and notification work end-to-end",interpreted_scope=("crm","notification"),
            success_conditions=("lead routed","owner notified","acceptance verified"),authority_basis="user request",
            materiality="MATERIAL",risk_class="R2",steps=steps or self.requests())
    def test_three_step_business_plan_preserves_canonical_owners_and_dependencies(self):
        prepared=self.prepare(); plan=self.mind.plan(prepared.plan_ref)
        self.assertEqual(len(plan.step_refs),3)
        self.assertEqual(tuple(x.step_ref for x in prepared.steps),plan.step_refs)
        route,notify,verify=(prepared.step(k) for k in ("route","notify","verify"))
        self.assertEqual(self.kernel.nervous.step(route.step_ref).state,StepState.READY)
        self.assertEqual(self.kernel.nervous.step(notify.step_ref).state,StepState.PLANNED)
        self.assertEqual(self.kernel.nervous.step(verify.step_ref).state,StepState.PLANNED)
        self.assertEqual(self.kernel.nervous.step(notify.step_ref).dependencies,(route.step_ref,))
        self.assertEqual(self.kernel.nervous.step(verify.step_ref).dependencies,(route.step_ref,notify.step_ref))
        self.assertEqual({x.assignment.task_ref for x in prepared.steps},{prepared.task_ref})
        self.assertEqual({x.assignment.context_manifest_ref for x in prepared.steps},{prepared.context_manifest_ref})
        self.assertEqual(tuple(x.key for x in ready_multistep(self.kernel,prepared)),("route",))
    def test_dependency_scheduler_unlocks_only_when_all_predecessors_succeed(self):
        prepared=self.prepare(); route=prepared.step("route"); notify=prepared.step("notify")
        self.kernel.nervous.transition_step(route.step_ref,StepState.ACTIVE)
        self.kernel.nervous.transition_step(route.step_ref,StepState.SUCCEEDED)
        self.assertEqual(tuple(x.key for x in ready_multistep(self.kernel,prepared)),("notify",))
        self.kernel.nervous.transition_step(notify.step_ref,StepState.ACTIVE)
        self.kernel.nervous.transition_step(notify.step_ref,StepState.SUCCEEDED)
        self.assertEqual(tuple(x.key for x in ready_multistep(self.kernel,prepared)),("verify",))
    def test_cycle_and_missing_capability_fail_before_task_execution(self):
        cyclic=(StepRequest("a","a","write","crm","a","a",("b",)),StepRequest("b","b","send","notification","b","b",("a",)))
        with self.assertRaises(MultiStepRejected): self.prepare(cyclic)
        missing=(self.requests()[0],StepRequest("x","Unknown","delete","unknown","x","x",("route",)))
        with self.assertRaises(MultiStepRejected): self.prepare(missing)
        self.assertEqual(self.tasks.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],0)

if __name__=="__main__": unittest.main()
