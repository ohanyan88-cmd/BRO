import unittest

from bro_runtime import (
    BROKernel, Capability, CapabilityKind, CapabilityStatus, MultiStepRejected,
    SQLiteMindStore, SQLiteTaskStore, StepRequest, StepState, prepare_multistep,
)
from bro_runtime.multistep_recovery import recover_multistep

T0 = "2026-09-01T00:00:00Z"


class MultiStepRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.kernel = BROKernel(self.tasks, self.mind)
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)
        for cid, operation, domain, provider in (
            ("cap:one", "write", "crm", "adapter:crm"),
            ("cap:two", "send", "notification", "adapter:notify"),
            ("cap:three", "inspect", "crm", "adapter:verify"),
        ):
            self.kernel.skills.register(Capability(
                cid, 1, CapabilityKind.TOOL_ADAPTER, cid, cid, (operation,), (domain,), None,
                f"artifact:{cid}", (), (operation,), ("inspect",), provider, None,
                CapabilityStatus.ACTIVE, T0,
            ))

    def prepared(self):
        return prepare_multistep(
            self.kernel, request="Run lead automation", source="user", project_boundary="BRO",
            desired_outcome="Route, notify, verify", interpreted_scope=("crm", "notification"),
            success_conditions=("route done", "notify done", "verify done"), authority_basis="user request",
            materiality="MATERIAL", risk_class="R2", steps=(
                StepRequest("route", "route", "write", "crm", "artifact:route", "inspect route"),
                StepRequest("notify", "notify", "send", "notification", "artifact:notify", "inspect notify", ("route",)),
                StepRequest("verify", "verify", "inspect", "crm", "evidence:verify", "inspect verify", ("route", "notify")),
            ),
        )

    def test_restart_resumes_dependency_ready_step_without_replay(self):
        prepared = self.prepared()
        route = prepared.step("route")
        notify = prepared.step("notify")
        self.kernel.nervous.transition_step(route.step_ref, StepState.ACTIVE)
        self.kernel.nervous.transition_step(route.step_ref, StepState.SUCCEEDED)

        recovered = recover_multistep(self.kernel, task_ref=prepared.task_ref, plan_ref=prepared.plan_ref)

        self.assertEqual(recovered.next_step_ref, notify.step_ref)
        self.assertEqual(recovered.completed_step_refs, (route.step_ref,))
        self.assertNotEqual(recovered.next_step_ref, route.step_ref)
        self.assertEqual(self.kernel.nervous.step(route.step_ref).state, StepState.SUCCEEDED)
        self.assertEqual(self.kernel.nervous.step(notify.step_ref).state, StepState.READY)

    def test_active_step_is_never_blindly_replayed_after_restart(self):
        prepared = self.prepared()
        route = prepared.step("route")
        self.kernel.nervous.transition_step(route.step_ref, StepState.ACTIVE)
        with self.assertRaisesRegex(MultiStepRejected, "reconciliation"):
            recover_multistep(self.kernel, task_ref=prepared.task_ref, plan_ref=prepared.plan_ref)
        self.assertEqual(self.kernel.nervous.step(route.step_ref).state, StepState.ACTIVE)


if __name__ == "__main__":
    unittest.main()
