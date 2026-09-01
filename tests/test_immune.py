from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from bro_runtime.immune import (
    AuthorityDecision,
    AuthorityEnvelope,
    AuthorityEvaluator,
    AuthorityRejected,
    CompletionManifest,
    CompletionNotVerified,
    CompletionVerdict,
    EffectRecord,
    Evidence,
    EvidenceFreshness,
    EvidenceLedger,
    EvidenceRejected,
    EvidenceValidity,
    evidence_scope,
    normalize_boundary_scope,
)

SCOPE = evidence_scope("project:BRO", "task:1")


def evidence(evidence_id: str = "evidence:1", **changes) -> Evidence:
    values = dict(
        evidence_id=evidence_id, criterion="tests pass", evidence_type="test-run", source="pytest",
        provenance={"runner": "ci"}, collection_method="executed", collected_at="2026-09-01T00:00:00Z",
        result={"failed": 0}, scope=SCOPE, limitations=(), validity=EvidenceValidity.VALID,
        freshness=EvidenceFreshness.CURRENT, verifier="IMMUNE_SYSTEM",
    )
    values.update(changes)
    return Evidence(**values)


def envelope(**changes) -> AuthorityEnvelope:
    values = dict(
        envelope_id="auth:1", version=1, principal="user:1", proof_ref="proof:1", authority_source="user",
        operation="write", target="repo:BRO",
        allowed_scope=("operation:write", "target:repo:BRO", "task:1", "project:BRO"),
        prohibited_scope=(), task_ref="task:1", risk_class="R3", valid_from="2026-01-01T00:00:00Z",
        expires_at="2027-01-01T00:00:00Z", revocation_ref=None, environment="github",
        tool_boundary=("github",), decision="ALLOWED", reason="requested", audit_ref="audit:1",
    )
    values.update(changes)
    return AuthorityEnvelope(**values)


def request(**changes) -> dict:
    values = dict(
        action_request_id="action:1", task_ref="task:1", operation="write", target="repo:BRO",
        environment="github", adapter_id="github", risk_class="R3", project_boundary="project:BRO",
    )
    values.update(changes)
    return values


class BoundaryScopeTests(unittest.TestCase):
    def test_bare_boundary_gains_the_canonical_prefix(self) -> None:
        self.assertEqual(normalize_boundary_scope("BRO"), "project:BRO")

    def test_canonical_boundary_is_never_double_prefixed(self) -> None:
        self.assertEqual(normalize_boundary_scope("project:BRO"), "project:BRO")
        self.assertNotEqual(normalize_boundary_scope("project:BRO"), "project:project:BRO")

    def test_normalisation_is_idempotent(self) -> None:
        for boundary in ("BRO", "project:BRO", "  project:BRO  "):
            once = normalize_boundary_scope(boundary)
            self.assertEqual(normalize_boundary_scope(once), once)

    def test_empty_boundary_is_denied(self) -> None:
        for empty in ("", "   ", None):
            with self.assertRaises(AuthorityRejected):
                normalize_boundary_scope(empty)

    def test_evidence_scope_normalises_the_boundary_exactly_once(self) -> None:
        self.assertEqual(evidence_scope("BRO", "task:1"), "project:BRO::task:1")
        self.assertEqual(evidence_scope("project:BRO", "task:1"), "project:BRO::task:1")


class AuthorityEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.authority = AuthorityEvaluator(self.connection)
        self.authority.register(envelope())

    def test_envelope_is_immutable(self) -> None:
        with self.assertRaisesRegex(AuthorityRejected, "immutable"):
            self.authority.register(envelope())

    def test_round_trip_preserves_the_digest(self) -> None:
        self.assertEqual(self.authority.envelope("auth:1").digest, envelope().digest)

    def test_matching_request_is_allowed_and_recorded(self) -> None:
        verdict = self.authority.evaluate(request(), envelope(), "2026-09-01T00:00:00Z", subject_ref="action:1")
        self.assertIs(verdict.decision, AuthorityDecision.ALLOW)
        decisions = self.authority.decisions("action:1")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["decision"], "ALLOW")
        self.assertEqual(decisions[0]["envelope_digest"], envelope().digest)

    def test_boundary_token_is_required_and_never_doubled(self) -> None:
        without = envelope(allowed_scope=("operation:write", "target:repo:BRO", "task:1"))
        verdict = self.authority.evaluate(request(), without, "2026-09-01T00:00:00Z")
        self.assertIs(verdict.decision, AuthorityDecision.DENY)
        self.assertIn("allowed scope is insufficient", verdict.reasons)

        doubled = envelope(allowed_scope=("operation:write", "target:repo:BRO", "task:1", "project:project:BRO"))
        self.assertIs(
            self.authority.evaluate(request(), doubled, "2026-09-01T00:00:00Z").decision,
            AuthorityDecision.DENY,
        )

    def test_bare_boundary_on_the_request_normalises_to_the_canonical_token(self) -> None:
        verdict = self.authority.evaluate(request(project_boundary="BRO"), envelope(), "2026-09-01T00:00:00Z")
        self.assertIs(verdict.decision, AuthorityDecision.ALLOW)

    def test_expired_authority_is_denied(self) -> None:
        verdict = self.authority.evaluate(request(), envelope(), "2027-06-01T00:00:00Z")
        self.assertIn("authority is expired", verdict.reasons)
        self.assertIs(verdict.decision, AuthorityDecision.DENY)

    def test_revoked_authority_is_denied(self) -> None:
        verdict = self.authority.evaluate(request(), envelope(revocation_ref="revocation:1"), "2026-09-01T00:00:00Z")
        self.assertIn("authority is revoked", verdict.reasons)

    def test_adapter_outside_the_tool_boundary_is_denied(self) -> None:
        verdict = self.authority.evaluate(request(), envelope(tool_boundary=("shell",)), "2026-09-01T00:00:00Z")
        self.assertIn("adapter outside tool boundary", verdict.reasons)

    def test_risk_ceiling_is_enforced(self) -> None:
        verdict = self.authority.evaluate(request(risk_class="R4"), envelope(), "2026-09-01T00:00:00Z")
        self.assertIn("authority risk ceiling is insufficient", verdict.reasons)

    def test_approval_required_is_not_an_allow(self) -> None:
        verdict = self.authority.evaluate(request(), envelope(decision="APPROVAL_REQUIRED"), "2026-09-01T00:00:00Z")
        self.assertIs(verdict.decision, AuthorityDecision.APPROVAL_REQUIRED)
        self.assertFalse(verdict.is_allowed())

    def test_unknown_envelope_decision_fails_closed(self) -> None:
        verdict = self.authority.evaluate(request(), envelope(decision="PROBABLY"), "2026-09-01T00:00:00Z")
        self.assertIs(verdict.decision, AuthorityDecision.DENY)


class EvidenceLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.ledger = EvidenceLedger(self.connection)

    def test_evidence_is_append_only(self) -> None:
        self.ledger.record(evidence())
        with self.assertRaisesRegex(EvidenceRejected, "append-only"):
            self.ledger.record(evidence())

    def test_valid_current_evidence_satisfies_its_criterion(self) -> None:
        self.ledger.record(evidence())
        satisfied, unsatisfied, refs = self.ledger.sufficiency(("tests pass",), SCOPE)
        self.assertEqual(satisfied, ("tests pass",))
        self.assertEqual(unsatisfied, ())
        self.assertEqual(refs, ("evidence:1",))

    def test_aging_evidence_still_counts_but_stale_does_not(self) -> None:
        self.ledger.record(evidence("evidence:aging", criterion="a", freshness=EvidenceFreshness.AGING))
        self.ledger.record(evidence("evidence:stale", criterion="b", freshness=EvidenceFreshness.STALE))
        self.ledger.record(evidence("evidence:unknown", criterion="c", freshness=EvidenceFreshness.UNKNOWN))
        satisfied, unsatisfied, _ = self.ledger.sufficiency(("a", "b", "c"), SCOPE)
        self.assertEqual(satisfied, ("a",))
        self.assertEqual(unsatisfied, ("b", "c"))

    def test_only_valid_evidence_counts(self) -> None:
        for index, validity in enumerate((EvidenceValidity.INVALID, EvidenceValidity.UNVERIFIED, EvidenceValidity.EXPIRED)):
            self.ledger.record(evidence(f"evidence:{index}", criterion=f"criterion:{index}", validity=validity))
        _, unsatisfied, refs = self.ledger.sufficiency(("criterion:0", "criterion:1", "criterion:2"), SCOPE)
        self.assertEqual(len(unsatisfied), 3)
        self.assertEqual(refs, ())

    def test_evidence_cannot_satisfy_a_criterion_in_another_scope(self) -> None:
        self.ledger.record(evidence(scope=evidence_scope("project:OTHER", "task:1")))
        _, unsatisfied, _ = self.ledger.sufficiency(("tests pass",), SCOPE)
        self.assertEqual(unsatisfied, ("tests pass",))


class CompletionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.ledger = EvidenceLedger(self.connection)

    def evaluate(self, **changes) -> CompletionManifest:
        values = dict(
            task_ref="task:1", task_revision=7, assignment_ref="assignment:1", scope=SCOPE,
            required_criteria=("tests pass",), assignment_result_state="SUCCEEDED",
            effects=(EffectRecord("action:1", "CONFIRMED"),), artifact_refs=("artifact:1",),
            outcome_exists=True, outcome_statement="the change is merged", exclusions=(),
            now="2026-09-01T01:00:00Z",
        )
        values.update(changes)
        return self.ledger.evaluate_completion(**values)

    def test_verified_when_every_criterion_has_current_evidence(self) -> None:
        self.ledger.record(evidence())
        manifest = self.evaluate()
        self.assertIs(manifest.verdict, CompletionVerdict.VERIFIED)
        self.assertEqual(manifest.evidence_refs, ("evidence:1",))
        self.assertEqual(manifest.to_completion_evidence().failures(), [])

    def test_missing_evidence_blocks_completion(self) -> None:
        manifest = self.evaluate()
        self.assertIs(manifest.verdict, CompletionVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(manifest.criteria_unsatisfied, ("tests pass",))
        with self.assertRaises(CompletionNotVerified):
            manifest.to_completion_evidence()

    def test_zero_declared_criteria_is_not_completion(self) -> None:
        manifest = self.evaluate(required_criteria=())
        self.assertIs(manifest.verdict, CompletionVerdict.INSUFFICIENT_EVIDENCE)
        self.assertIn("no completion criteria", manifest.reason)

    def test_unknown_effect_blocks_completion(self) -> None:
        self.ledger.record(evidence())
        manifest = self.evaluate(effects=(EffectRecord("action:1", "UNKNOWN"),))
        self.assertIs(manifest.verdict, CompletionVerdict.EFFECT_UNRECONCILED)

    def test_possible_effect_blocks_completion(self) -> None:
        self.ledger.record(evidence())
        manifest = self.evaluate(effects=(EffectRecord("action:1", "POSSIBLE"),))
        self.assertIs(manifest.verdict, CompletionVerdict.EFFECT_UNRECONCILED)

    def test_partial_result_stays_partial(self) -> None:
        self.ledger.record(evidence())
        manifest = self.evaluate(assignment_result_state="PARTIAL", exclusions=("integration untested",))
        self.assertIs(manifest.verdict, CompletionVerdict.PARTIAL)
        self.assertEqual(manifest.exclusions, ("integration untested",))
        with self.assertRaises(CompletionNotVerified):
            manifest.to_completion_evidence()

    def test_partial_without_exclusions_names_the_omission(self) -> None:
        self.ledger.record(evidence())
        manifest = self.evaluate(assignment_result_state="PARTIAL")
        self.assertIs(manifest.verdict, CompletionVerdict.PARTIAL)
        self.assertIn("did not declare its excluded scope", manifest.reason)

    def test_failed_work_is_not_completion(self) -> None:
        self.ledger.record(evidence())
        self.assertIs(self.evaluate(assignment_result_state="FAILED").verdict, CompletionVerdict.WORK_FAILED)

    def test_unsettled_assignment_is_not_completion(self) -> None:
        self.ledger.record(evidence())
        self.assertIs(self.evaluate(assignment_result_state="LEASED").verdict, CompletionVerdict.WORK_FAILED)

    def test_missing_outcome_is_not_completion(self) -> None:
        self.ledger.record(evidence())
        manifest = self.evaluate(outcome_exists=False)
        self.assertIs(manifest.verdict, CompletionVerdict.INSUFFICIENT_EVIDENCE)
        self.assertIn("outcome does not exist", manifest.reason)

    def test_every_verdict_is_durably_recorded(self) -> None:
        first = self.evaluate()
        self.ledger.record(evidence())
        second = self.evaluate()
        self.assertEqual(self.ledger.manifest(first.manifest_id)["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(self.ledger.latest_manifest("task:1")["manifest_id"], second.manifest_id)


class ContractAlignmentTests(unittest.TestCase):
    @staticmethod
    def schema(name: str) -> dict:
        return json.loads(Path(f"contracts/v0.1/{name}").read_text(encoding="utf-8"))

    def test_evidence_record_matches_its_contract(self) -> None:
        schema = self.schema("evidence.schema.json")
        self.assertEqual(set(evidence().body()), set(schema["properties"]))
        self.assertEqual(set(schema["required"]) - set(evidence().body()), set())
        self.assertEqual(set(schema["properties"]["validity"]["enum"]), {v.value for v in EvidenceValidity})
        self.assertEqual(set(schema["properties"]["freshness"]["enum"]), {f.value for f in EvidenceFreshness})

    def test_completion_manifest_matches_its_contract(self) -> None:
        schema = self.schema("completion-manifest.schema.json")
        manifest = CompletionManifest(
            "manifest:1", "task:1", 1, "assignment:1", CompletionVerdict.VERIFIED, "done", True,
            ("artifact:1",), (EffectRecord("action:1", "CONFIRMED"),), (), ("c",), (), ("evidence:1",),
            "2026-09-01T00:00:00Z", "IMMUNE_SYSTEM", "verified",
        )
        body = manifest.body()
        self.assertEqual(set(body), set(schema["properties"]))
        self.assertEqual(set(schema["required"]), set(body))
        self.assertEqual(set(schema["properties"]["verdict"]["enum"]), {v.value for v in CompletionVerdict})
        effect_enum = schema["properties"]["effects"]["items"]["properties"]["effect_state"]["enum"]
        attempt_enum = self.schema("action-attempt.schema.json")["properties"]["side_effect_state"]["enum"]
        self.assertEqual(set(effect_enum), set(attempt_enum))

    def test_completion_manifest_is_registered_to_one_owner(self) -> None:
        registry = json.loads(Path("contracts/registry.json").read_text(encoding="utf-8"))
        owners = [entry["owner"] for entry in registry["contracts"] if entry["primitive"] == "CompletionManifest"]
        self.assertEqual(owners, ["IMMUNE_SYSTEM"])


if __name__ == "__main__":
    unittest.main()
