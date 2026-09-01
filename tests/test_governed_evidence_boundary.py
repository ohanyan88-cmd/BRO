import unittest

from bro_runtime.action_runtime import EffectState
from bro_runtime.evidence_verification import (
    EvidenceObservation,
    EvidenceVerificationRegistry,
    EvidenceVerifier,
    VerificationResult,
    is_trusted_evidence,
)
from bro_runtime.governed_supervision import GovernedTaskSupervisor
from bro_runtime.immune import Evidence, EvidenceFreshness, EvidenceValidity
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.orchestration import AssignmentState
from bro_runtime.supervision import BoundaryViolation
from bro_runtime.task_runtime import SQLiteTaskStore


class GovernedEvidenceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)
        self.supervisor = GovernedTaskSupervisor(self.tasks, mind_store=self.mind)
        self.registry = EvidenceVerificationRegistry()
        self.registry.register(
            EvidenceVerifier(
                "IMMUNE:test-readback",
                lambda _observation: VerificationResult(
                    EvidenceValidity.VALID,
                    EvidenceFreshness.CURRENT,
                    {"verified_by": "test-readback"},
                ),
            )
        )

    def verified(self):
        return self.registry.verify(
            "IMMUNE:test-readback",
            EvidenceObservation(
                criterion="criterion",
                evidence_type="readback",
                source="provider",
                provenance={"resource": "crm:1"},
                collection_method="registered-provider-readback",
                result={"ok": True},
                scope="project:BRO::task:1",
            ),
            evidence_id="evidence:verified",
            collected_at="2026-09-01T00:00:00Z",
        )

    def test_registered_verifier_attests_exact_evidence_object(self):
        evidence = self.verified()
        self.assertTrue(is_trusted_evidence(evidence))
        clone = Evidence(**evidence.__dict__)
        self.assertFalse(is_trusted_evidence(clone))

    def test_canonical_ledger_rejects_direct_self_minted_evidence(self):
        forged = Evidence(**self.verified().__dict__)
        with self.assertRaisesRegex(BoundaryViolation, "cannot enter the canonical ledger"):
            self.supervisor.evidence.record(forged)

    def test_canonical_ledger_accepts_registered_verifier_evidence(self):
        evidence = self.verified()
        recorded = self.supervisor.evidence.record(evidence)
        self.assertEqual(recorded["evidence_id"], evidence.evidence_id)

    def test_canonical_ledger_rejects_direct_completion_manifest_minting(self):
        with self.assertRaisesRegex(BoundaryViolation, "direct completion evaluation is disabled"):
            self.supervisor.evidence.evaluate_completion()

    def test_canonical_supervisor_rejects_self_minted_reconciliation_evidence(self):
        forged = Evidence(**self.verified().__dict__)
        with self.assertRaisesRegex(BoundaryViolation, "untrusted evidence is disabled"):
            self.supervisor.reconcile(object(), "action:1", EffectState.CONFIRMED, forged)

    def test_canonical_supervisor_rejects_self_minted_settlement_evidence(self):
        forged = Evidence(**self.verified().__dict__)
        with self.assertRaisesRegex(BoundaryViolation, "untrusted evidence is disabled"):
            self.supervisor.settle_assignment(
                object(),
                result_state=AssignmentState.SUCCEEDED,
                output_ref="artifact:1",
                evidence=(forged,),
            )


if __name__ == "__main__":
    unittest.main()
