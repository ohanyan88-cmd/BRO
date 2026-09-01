import unittest

from bro_runtime.kernel import BROKernel
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.multistep import StepRequest
from bro_runtime.multistep_runtime import prepare_multistep
from bro_runtime.provider_adapters import ProviderHealth
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.task_runtime import SQLiteTaskStore

T0 = "2026-09-01T00:00:00Z"


def capability(capability_id: str, operation: str, domain: str, provider_ref: str) -> Capability:
    return Capability(
        capability_id=capability_id,
        version=1,
        kind=CapabilityKind.TOOL_ADAPTER,
        name=capability_id,
        description="multistep routing test",
        operations=(operation,),
        domains=(domain,),
        input_contract_ref=None,
        output_contract_ref="artifact:test",
        dependency_refs=(),
        authority_requirements=(operation,),
        evidence_capabilities=("readback",),
        provider_ref=provider_ref,
        health_ref=None,
        status=CapabilityStatus.ACTIVE,
        recorded_at=T0,
    )


class MultiStepProviderRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)

    def test_each_step_uses_provider_health_aware_selection(self):
        health = {
            "adapter:crm-degraded": ProviderHealth.DEGRADED,
            "adapter:crm-healthy": ProviderHealth.HEALTHY,
            "adapter:billing": ProviderHealth.HEALTHY,
        }
        kernel = BROKernel(self.tasks, self.mind, provider_health_for=lambda ref: health[ref])
        kernel.skills.register(capability("cap:crm-a", "create", "crm", "adapter:crm-degraded"))
        kernel.skills.register(capability("cap:crm-z", "create", "crm", "adapter:crm-healthy"))
        kernel.skills.register(capability("cap:billing", "invoice", "billing", "adapter:billing"))

        prepared = prepare_multistep(
            kernel,
            request="create customer and invoice",
            source="user",
            project_boundary="BRO",
            desired_outcome="customer exists and invoice exists",
            interpreted_scope=("crm", "billing"),
            success_conditions=("customer exists", "invoice exists"),
            authority_basis="user request",
            materiality="MATERIAL",
            risk_class="R2",
            steps=(
                StepRequest("customer", "create customer", "create", "crm", "customer", "readback"),
                StepRequest("invoice", "create invoice", "invoice", "billing", "invoice", "readback", ("customer",)),
            ),
        )

        by_key = {step.key: step for step in prepared.steps}
        self.assertEqual(by_key["customer"].capability_ref, "cap:crm-z")
        self.assertEqual(by_key["customer"].assignment.allowed_tools, ("adapter:crm-healthy",))
        self.assertEqual(by_key["invoice"].capability_ref, "cap:billing")

    def test_unavailable_provider_fails_closed_for_a_step(self):
        kernel = BROKernel(
            self.tasks,
            self.mind,
            provider_health_for=lambda _: ProviderHealth.UNAVAILABLE,
        )
        kernel.skills.register(capability("cap:crm", "create", "crm", "adapter:crm"))

        with self.assertRaisesRegex(ValueError, "no routable provider"):
            prepare_multistep(
                kernel,
                request="create customer then invoice",
                source="user",
                project_boundary="BRO",
                desired_outcome="customer and invoice",
                interpreted_scope=("crm",),
                success_conditions=("done",),
                authority_basis="user request",
                materiality="MATERIAL",
                risk_class="R2",
                steps=(
                    StepRequest("one", "first", "create", "crm", "customer", "readback"),
                    StepRequest("two", "second", "create", "crm", "customer2", "readback", ("one",)),
                ),
            )


if __name__ == "__main__":
    unittest.main()
