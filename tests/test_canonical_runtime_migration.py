import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.evidence_verification import (
    EvidenceObservation,
    EvidenceVerificationRegistry,
    EvidenceVerifier,
    VerificationResult,
)
from bro_runtime.immune import (
    AuthorityEnvelope,
    EvidenceFreshness,
    EvidenceValidity,
    evidence_scope,
)
from bro_runtime.kernel import BROKernel
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
from bro_runtime.provider_adapters import ProviderAdapter, ProviderHealth
from bro_runtime.provider_execution import ProviderRoute
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.supervision import BoundaryViolation
from bro_runtime.task_runtime import SQLiteTaskStore

T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:00:01Z"


def capability(capability_id, provider_ref):
    return Capability(
        capability_id=capability_id,
        version=1,
        kind=CapabilityKind.TOOL_ADAPTER,
        name=capability_id,
        description="canonical runtime test capability",
        operations=("write",),
        domains=("crm",),
        input_contract_ref=None,
        output_contract_ref="artifact:crm",
        dependency_refs=(),
        authority_requirements=("write",),
        evidence_capabilities=("readback",),
        provider_ref=provider_ref,
        health_ref=None,
        status=CapabilityStatus.ACTIVE,
        recorded_at=T0,
    )


def prepare(kernel):
    return kernel.prepare(
        request="Create CRM customer",
        source="user",
        project_boundary="BRO",
        desired_outcome="CRM customer exists",
        interpreted_scope=("crm",),
        success_conditions=("customer exists",),
        operation="write",
        domain="crm",
        authority_basis="user request",
        materiality="MATERIAL",
        risk_class="R2",
        expected_output="artifact:customer",
        verification_requirement="provider readback",
    )


def envelope(prepared, adapter_id):
    task_id = prepared.assignment.task_ref
    return AuthorityEnvelope(
        envelope_id="auth:1",
        version=1,
        principal="BRO",
        proof_ref="proof:user",
        authority_source="user",
        operation="write",
        target="crm:customers",
        allowed_scope=("operation:write", "target:crm:customers", task_id, "project:BRO"),
        prohibited_scope=(),
        task_ref=task_id,
        risk_class="R2",
        valid_from=T0,
        expires_at="2026-09-02T00:00:00Z",
        revocation_ref=None,
        environment="prod",
        tool_boundary=(adapter_id,),
        decision="ALLOWED",
        reason="bounded test authority",
        audit_ref="audit:1",
    )


def action(prepared, adapter_id):
    return ActionRequest(
        action_request_id="action:1",
        task_ref=prepared.assignment.task_ref,
        intended_effect="create customer",
        operation="write",
        target="crm:customers",
        environment="prod",
        adapter_id=adapter_id,
        input_parameters={"name": "Gev"},
        authority_envelope_ref="auth:1",
        risk_class="R2",
        reversibility="REVERSIBLE",
        idempotency_key="customer:gev",
        idempotency_guaranteed=True,
        expected_result={"id": "C-1"},
        verification_requirements=("provider readback",),
        assignment_ref=prepared.assignment.assignment_id,
        project_boundary="BRO",
    )


class CanonicalRuntimeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)

    def test_prepare_uses_provider_health_in_canonical_kernel_path(self):
        health = {
            "adapter:degraded": ProviderHealth.DEGRADED,
            "adapter:healthy": ProviderHealth.HEALTHY,
        }
        kernel = BROKernel(self.tasks, self.mind, provider_health_for=lambda ref: health[ref])
        kernel.skills.register(capability("cap:a-degraded", "adapter:degraded"))
        kernel.skills.register(capability("cap:z-healthy", "adapter:healthy"))

        prepared = prepare(kernel)

        self.assertEqual(prepared.capability_ref, "cap:z-healthy")
        self.assertEqual(prepared.assignment.allowed_tools, ("adapter:healthy",))

    def test_kernel_supervisor_is_bound_to_the_exact_kernel_evidence_registry(self):
        kernel = BROKernel(self.tasks, self.mind)
        self.assertIs(kernel.supervisor.evidence_verifiers, kernel.evidence_verifiers)

        observation = EvidenceObservation(
            criterion="customer exists",
            evidence_type="external-readback",
            source="crm",
            provenance={},
            collection_method="readback",
            result={"exists": True},
            scope="project:BRO::task:foreign",
        )
        foreign = EvidenceVerificationRegistry()
        foreign.register(
            EvidenceVerifier(
                "IMMUNE:foreign",
                lambda _: VerificationResult(EvidenceValidity.VALID, EvidenceFreshness.CURRENT, {}),
            )
        )
        foreign_evidence = foreign.verify("IMMUNE:foreign", observation)
        self.assertFalse(kernel.evidence_verifiers.is_trusted(foreign_evidence))
        with self.assertRaisesRegex(BoundaryViolation, "this kernel's registered evidence verifier"):
            kernel.supervisor.evidence.record(foreign_evidence)

    def test_registered_provider_and_trusted_evidence_complete_canonical_flow(self):
        kernel = BROKernel(self.tasks, self.mind)
        kernel.skills.register(capability("cap:crm", "crm"))
        provider_calls = []
        kernel.register_provider(
            ProviderAdapter(
                adapter_id="crm",
                provider="acme",
                version="v1",
                operations=("write",),
                invoke=lambda inputs: provider_calls.append(inputs)
                or AdapterResult({"id": "C-1"}, EffectState.CONFIRMED, ("artifact:C-1",), ("observation:C-1",)),
                health=ProviderHealth.HEALTHY,
            )
        )
        kernel.register_evidence_verifier(
            EvidenceVerifier(
                "IMMUNE:crm-readback",
                lambda observation: VerificationResult(
                    EvidenceValidity.VALID,
                    EvidenceFreshness.CURRENT,
                    {"verified_by": "provider-readback", "resource": observation.result["id"]},
                ),
            )
        )

        prepared = prepare(kernel)
        binding = kernel.open(prepared, envelope(prepared, "crm"), worker_id="worker:crm", now=T1)
        attempt = kernel.execute_provider(
            binding,
            action(prepared, "crm"),
            route=ProviderRoute("acme", "crm", "v1"),
            executor="worker:crm",
            now=T1,
        )
        self.assertEqual(attempt["effect_state"], EffectState.CONFIRMED)
        self.assertEqual(provider_calls, [{"name": "Gev"}])

        scope = evidence_scope("BRO", prepared.assignment.task_ref)
        observation = EvidenceObservation(
            criterion="customer exists",
            evidence_type="external-readback",
            source="acme-crm",
            provenance={"provider":"acme", "adapter":"crm", "version":"v1"},
            collection_method="provider-readback",
            result={"id":"C-1", "exists":True},
            scope=scope,
        )
        kernel.settle_verified_assignment(
            prepared,
            binding,
            result_state=AssignmentState.SUCCEEDED,
            output_ref="artifact:C-1",
            observations=(("IMMUNE:crm-readback", observation),),
            now=T1,
        )
        manifest = kernel.complete(
            prepared,
            binding,
            outcome_statement="CRM customer exists and was independently read back",
            required_criteria=("customer exists",),
            now=T1,
        )
        self.assertTrue(manifest.is_verified())
        self.assertEqual(kernel.supervisor.canonical_task(prepared.assignment.task_ref)["state"], "COMPLETED")

    def test_canonical_evidence_path_rejects_foreign_scope_before_minting(self):
        kernel = BROKernel(self.tasks, self.mind)
        kernel.skills.register(capability("cap:crm", "crm"))
        kernel.register_evidence_verifier(
            EvidenceVerifier(
                "IMMUNE:crm-readback",
                lambda _: VerificationResult(EvidenceValidity.VALID, EvidenceFreshness.CURRENT, {}),
            )
        )
        prepared = prepare(kernel)
        foreign = EvidenceObservation(
            criterion="customer exists",
            evidence_type="external-readback",
            source="crm",
            provenance={},
            collection_method="readback",
            result={"exists": True},
            scope=evidence_scope("OTHER", prepared.assignment.task_ref),
        )
        with self.assertRaisesRegex(ValueError, "crosses the prepared task boundary"):
            kernel.verify_evidence(prepared, foreign, verifier_id="IMMUNE:crm-readback")


if __name__ == "__main__":
    unittest.main()
