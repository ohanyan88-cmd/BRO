import json
import unittest
from urllib.request import Request, urlopen

from bro_runtime.action_runtime import AdapterResult, EffectState
from bro_runtime.evidence_verification import EvidenceObservation, EvidenceVerifier, VerificationResult
from bro_runtime.immune import AuthorityEnvelope, EvidenceFreshness, EvidenceValidity, evidence_scope
from bro_runtime.kernel import BROKernel
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
from bro_runtime.provider_adapters import ProviderAdapter, ProviderHealth
from bro_runtime.skills import Capability, CapabilityKind, CapabilityStatus
from bro_runtime.task_runtime import SQLiteTaskStore


T0 = "2026-09-01T00:00:00Z"
T1 = "2026-09-01T00:01:00Z"
REPO_API = "https://api.github.com/repos/ohanyan88-cmd/BRO"


class RealSystemAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.kernel = BROKernel(self.tasks, self.mind)
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)
        self.kernel.skills.register(Capability(
            capability_id="cap:github-inspect", version=1, kind=CapabilityKind.TOOL_ADAPTER,
            name="GitHub repository inspector", description="Reads a real external GitHub repository",
            operations=("inspect",), domains=("github",), input_contract_ref=None,
            output_contract_ref="evidence:github-repository", dependency_refs=(),
            authority_requirements=("inspect",), evidence_capabilities=("inspect",),
            provider_ref="adapter:github-rest", health_ref="health:github-rest",
            status=CapabilityStatus.ACTIVE, recorded_at=T0,
        ))
        self.kernel.providers.register(ProviderAdapter(
            adapter_id="adapter:github-rest", provider="github", version="v1",
            operations=("repository.read",), invoke=self.read_real_repository,
            health=ProviderHealth.HEALTHY,
        ))
        self.kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:github-acceptance",
            lambda _observation: VerificationResult(
                EvidenceValidity.VALID,
                EvidenceFreshness.CURRENT,
                {"verification_source": "registered-live-github-rest"},
            ),
        ))

    @staticmethod
    def read_real_repository(_inputs):
        request = Request(REPO_API, headers={"User-Agent": "BRO-real-system-acceptance"})
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise AssertionError(f"GitHub returned HTTP {response.status}")
            external = json.loads(response.read().decode("utf-8"))
        return AdapterResult(
            external,
            EffectState.NONE,
            observation_refs=(f"github:repository-readback:{external['id']}",),
        )

    def test_real_business_outcome_reaches_verified_done_through_registered_provider_readback(self):
        live = self.kernel.live_readback.observe_from_provider(
            provider="github", adapter_id="adapter:github-rest", version="v1",
            operation="repository.read", resource_ref="github:repo:ohanyan88-cmd/BRO", inputs={},
        )
        external = live.observed_state
        self.assertEqual(external["full_name"], "ohanyan88-cmd/BRO")
        self.assertEqual(external["default_branch"], "main")
        self.assertEqual(live.provider_ref, "github:adapter:github-rest@v1")
        self.assertTrue(live.evidence_ref.startswith("github:repository-readback:"))

        prepared = self.kernel.prepare(
            request="Verify the live BRO repository is externally reachable",
            source="acceptance:github", project_boundary="BRO",
            desired_outcome="Live BRO repository is externally observable and verified",
            interpreted_scope=("github", "repository-readback"),
            success_conditions=("live repository is externally readable",),
            operation="inspect", domain="github", authority_basis="production acceptance",
            materiality="MATERIAL", risk_class="R1", expected_output="evidence:github-repository",
            verification_requirement="registered GitHub provider readback",
        )
        task_ref = prepared.assignment.task_ref
        envelope = AuthorityEnvelope(
            envelope_id="auth:real-system", version=1, principal="BRO", proof_ref="proof:acceptance",
            authority_source="system", operation="inspect", target="github:repo:ohanyan88-cmd/BRO",
            allowed_scope=("operation:inspect", "target:github:repo:ohanyan88-cmd/BRO", task_ref, "project:BRO"),
            prohibited_scope=(), task_ref=task_ref, risk_class="R1", valid_from=T0,
            expires_at="2026-09-02T00:00:00Z", revocation_ref=None, environment="production",
            tool_boundary=("adapter:github-rest",), decision="ALLOWED",
            reason="read-only production acceptance", audit_ref="audit:real-system",
        )
        binding = self.kernel.open(prepared, envelope, worker_id="specialist:real-system", now=T1)
        observation = EvidenceObservation(
            criterion="live repository is externally readable",
            evidence_type="external-readback",
            source="github",
            provenance={
                "provider_ref": live.provider_ref,
                "resource_ref": live.resource_ref,
                "provider_observation_ref": live.evidence_ref,
                "full_name": external["full_name"],
                "default_branch": external["default_branch"],
                "id": external["id"],
            },
            collection_method="registered-provider-readback",
            result=True,
            scope=evidence_scope("BRO", task_ref),
        )
        self.kernel.settle_verified_assignment(
            prepared, binding, result_state=AssignmentState.SUCCEEDED,
            output_ref=live.resource_ref,
            observations=(("IMMUNE:github-acceptance", observation),), now=T1,
        )
        manifest = self.kernel.complete(
            prepared, binding,
            outcome_statement="The live BRO GitHub repository was read through the registered provider boundary and verified",
            required_criteria=("live repository is externally readable",), now=T1,
        )
        self.assertTrue(manifest.is_verified())
        self.assertEqual(self.kernel.supervisor.canonical_task(task_ref)["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
