import json
import unittest
from urllib.request import Request, urlopen

from bro_runtime.evidence_verification import EvidenceObservation, EvidenceVerifier, VerificationResult
from bro_runtime.immune import AuthorityEnvelope, EvidenceFreshness, EvidenceValidity, evidence_scope
from bro_runtime.kernel import BROKernel
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
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
        self.kernel.register_evidence_verifier(EvidenceVerifier(
            "IMMUNE:github-acceptance",
            lambda _observation: VerificationResult(
                EvidenceValidity.VALID,
                EvidenceFreshness.CURRENT,
                {"verification_source": "live-github-rest"},
            ),
        ))

    @staticmethod
    def read_real_repository():
        request = Request(REPO_API, headers={"User-Agent": "BRO-real-system-acceptance"})
        with urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise AssertionError(f"GitHub returned HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))

    def test_real_business_outcome_reaches_verified_done(self):
        external = self.read_real_repository()
        self.assertEqual(external["full_name"], "ohanyan88-cmd/BRO")
        self.assertEqual(external["default_branch"], "main")

        prepared = self.kernel.prepare(
            request="Verify the live BRO repository is externally reachable",
            source="acceptance:github", project_boundary="BRO",
            desired_outcome="Live BRO repository is externally observable and verified",
            interpreted_scope=("github", "repository-readback"),
            success_conditions=("live repository is externally readable",),
            operation="inspect", domain="github", authority_basis="production acceptance",
            materiality="MATERIAL", risk_class="R1", expected_output="evidence:github-repository",
            verification_requirement="read GitHub REST API",
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
        scope = evidence_scope("BRO", task_ref)
        observation = EvidenceObservation(
            criterion="live repository is externally readable",
            evidence_type="external-readback",
            source="github",
            provenance={"full_name": external["full_name"], "default_branch": external["default_branch"], "id": external["id"]},
            collection_method=REPO_API,
            result=True,
            scope=scope,
        )
        self.kernel.settle_verified_assignment(
            prepared,
            binding,
            result_state=AssignmentState.SUCCEEDED,
            output_ref=f"github:repo:{external['full_name']}",
            observations=(("IMMUNE:github-acceptance", observation),),
            now=T1,
        )
        manifest = self.kernel.complete(
            prepared, binding,
            outcome_statement="The live BRO GitHub repository was read from the external system and verified",
            required_criteria=("live repository is externally readable",), now=T1,
        )
        self.assertTrue(manifest.is_verified())
        self.assertEqual(self.kernel.supervisor.canonical_task(task_ref)["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
