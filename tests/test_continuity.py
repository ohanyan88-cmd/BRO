import unittest
from dataclasses import asdict, replace

from bro_runtime import ContinuityRejected, ContinuityStatus, ContinuityStore, HeartRecord, SelfRecord, SQLiteTaskStore


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteTaskStore()
        self.addCleanup(self.db.close)
        self.store = ContinuityStore(self.db.connection)

    def self_record(self):
        base = SelfRecord(
            self_id="BRO", schema_version="0.1.0", identity_version=1, product_name="BRO",
            identity_statement="one persistent AI operating partner",
            character_traits=("steady", "direct"), stable_values=("truth", "continuity"),
            behavioral_invariants=("do not simulate access", "do not claim unverified completion"),
            voice_baseline_ref="voice:baseline:1", visual_identity_ref=None,
            continuity_policy_ref="policy:continuity:1", provider_independence=True,
            effective_from="2026-09-01T00:00:00Z", supersedes=None,
            authority_record_ref="authority:product-owner:1", integrity_digest="",
            status=ContinuityStatus.ACTIVE,
        )
        return replace(base, integrity_digest=self.store.digest(asdict(base)))

    def heart_record(self):
        base = HeartRecord(
            heart_id="heart:gev:1", schema_version="0.1.0", heart_version=1,
            relationship_scope="private:user:gev", stance_principles=("care without flattery",),
            care_rules=("optimize for durable outcome",), loyalty_rules=("never hide disagreement",),
            honesty_rules=("state uncertainty",), disagreement_rules=("challenge when truth requires it",),
            warmth_rules=("warmth without fake emotion",), privacy_rules=("keep private context private",),
            non_flattery_rules=("no empty praise",), non_deception_rules=("never claim human status",),
            long_horizon_commitments=("preserve continuity",), private_foundation_refs=("memory:private:1",),
            expression_constraints_ref="voice:constraints:1", effective_from="2026-09-01T00:00:00Z",
            supersedes=None, authority_record_ref="authority:user:1", integrity_digest="",
            status=ContinuityStatus.ACTIVE,
        )
        return replace(base, integrity_digest=self.store.digest(asdict(base)))

    def test_activation_returns_minimal_envelope_without_private_foundation(self):
        self.store.record_self(self.self_record())
        self.store.record_heart(self.heart_record())
        envelope = self.store.activate("private:user:gev")
        self.assertEqual(envelope.self_ref, "BRO")
        self.assertEqual(envelope.heart_ref, "heart:gev:1")
        self.assertNotIn("memory:private:1", repr(envelope))
        self.assertIn("do not disclose private foundation material", envelope.prohibited_disclosures)

    def test_self_cannot_rename_bro_or_depend_on_provider(self):
        record = self.self_record()
        renamed = replace(record, product_name="OTHER", integrity_digest="")
        renamed = replace(renamed, integrity_digest=self.store.digest(asdict(renamed)))
        with self.assertRaisesRegex(ContinuityRejected, "must remain BRO"):
            self.store.record_self(renamed)
        dependent = replace(record, provider_independence=False, integrity_digest="")
        dependent = replace(dependent, integrity_digest=self.store.digest(asdict(dependent)))
        with self.assertRaisesRegex(ContinuityRejected, "provider-independent"):
            self.store.record_self(dependent)

    def test_integrity_tampering_is_rejected(self):
        record = self.heart_record()
        tampered = replace(record, honesty_rules=("hide uncertainty",))
        with self.assertRaisesRegex(ContinuityRejected, "integrity digest mismatch"):
            self.store.record_heart(tampered)

    def test_activation_fails_closed_on_ambiguous_active_heart(self):
        self.store.record_self(self.self_record())
        first = self.heart_record()
        self.store.record_heart(first)
        second = replace(first, heart_id="heart:gev:2", heart_version=2, integrity_digest="")
        second = replace(second, integrity_digest=self.store.digest(asdict(second)))
        self.store.record_heart(second)
        with self.assertRaisesRegex(ContinuityRejected, "exactly one active"):
            self.store.activate("private:user:gev")


if __name__ == "__main__":
    unittest.main()
