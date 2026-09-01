import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.evidence_verification import (
    EvidenceObservation, EvidenceVerificationRegistry, EvidenceVerifier, VerificationResult,
)
from bro_runtime.immune import EvidenceFreshness, EvidenceRejected, EvidenceValidity, evidence_scope
from bro_runtime.provider_adapters import ProviderAdapter, ProviderAdapterRegistry, ProviderHealth
from bro_runtime.provider_execution import ProviderExecutionGateway, ProviderRoute


class EvidenceTrustBoundaryTests(unittest.TestCase):
    def test_caller_cannot_mint_evidence_through_unknown_verifier(self):
        registry = EvidenceVerificationRegistry()
        observation = EvidenceObservation(
            criterion="external outcome exists", evidence_type="readback", source="crm",
            provenance={"resource":"C-1"}, collection_method="provider-readback", result={"exists":True},
            scope=evidence_scope("BRO", "task:1"),
        )
        with self.assertRaisesRegex(EvidenceRejected, "unknown evidence verifier"):
            registry.verify("caller", observation)

    def test_trusted_verifier_owns_validity_freshness_and_identity(self):
        registry = EvidenceVerificationRegistry()
        registry.register(EvidenceVerifier(
            "IMMUNE:crm-readback",
            lambda observation: VerificationResult(
                EvidenceValidity.VALID, EvidenceFreshness.CURRENT,
                {"verified_resource": observation.provenance["resource"]},
            ),
        ))
        evidence = registry.verify(
            "IMMUNE:crm-readback",
            EvidenceObservation(
                criterion="external outcome exists", evidence_type="readback", source="crm",
                provenance={"resource":"C-1"}, collection_method="provider-readback",
                result={"exists":True}, scope=evidence_scope("BRO", "task:1"),
            ),
            evidence_id="evidence:trusted", collected_at="2026-09-01T00:00:00Z",
        )
        self.assertEqual(evidence.verifier, "IMMUNE:crm-readback")
        self.assertIs(evidence.validity, EvidenceValidity.VALID)
        self.assertIs(evidence.freshness, EvidenceFreshness.CURRENT)
        self.assertEqual(evidence.provenance["verified_resource"], "C-1")


class ProviderGatewayTests(unittest.TestCase):
    def test_gateway_resolves_registered_version_and_never_accepts_a_callable(self):
        calls=[]
        providers=ProviderAdapterRegistry()
        providers.register(ProviderAdapter(
            "crm", "acme", "v1", ("customer.create",),
            lambda inputs: calls.append(inputs) or AdapterResult({"id":"C-1"}, EffectState.CONFIRMED),
            ProviderHealth.HEALTHY,
        ))

        class Supervisor:
            def execute(self, binding, request, *, executor, interface_version, adapter, now=None):
                self.interface_version=interface_version
                return adapter(request.input_parameters)

        supervisor=Supervisor()
        gateway=ProviderExecutionGateway(supervisor, providers)
        request=ActionRequest(
            "action:1","task:1","create customer","customer.create","crm:customers","prod","crm",
            {"name":"Gev"},"auth:1","R2","REVERSIBLE","idem:1",True,{"id":"C-1"},("readback",),
            "assignment:1","BRO",
        )
        result=gateway.execute(object(), request, route=ProviderRoute("acme","crm","v1"), executor="worker")
        self.assertEqual(result.result,{"id":"C-1"})
        self.assertEqual(calls,[{"name":"Gev"}])
        self.assertEqual(supervisor.interface_version,"v1")

    def test_unavailable_provider_fails_before_supervisor_execution(self):
        providers=ProviderAdapterRegistry()
        providers.register(ProviderAdapter("crm","acme","v1",("read",),lambda _: AdapterResult({},EffectState.NONE),ProviderHealth.UNAVAILABLE))
        class Supervisor:
            def execute(self, *args, **kwargs):
                raise AssertionError("must not execute")
        gateway=ProviderExecutionGateway(Supervisor(),providers)
        request=ActionRequest("a","t","read","read","x","prod","crm",{},"auth","R1","REVERSIBLE","i",True,{},(),"as","BRO")
        with self.assertRaisesRegex(ValueError,"unavailable"):
            gateway.execute(object(),request,route=ProviderRoute("acme","crm","v1"),executor="worker")


if __name__ == "__main__":
    unittest.main()
