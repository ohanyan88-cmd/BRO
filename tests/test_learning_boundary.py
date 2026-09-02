import sqlite3
import unittest

from bro_runtime.learning_boundary import (
    EXTERNAL_ASSURANCE,
    ExperienceContext,
    GovernedLearningBoundary,
    LearningEligibility,
)
from bro_runtime.learning_memory import DurableLearningMemory, LearningMemoryRejected, LessonStatus

VERIFIED_RECEIPT = {
    "specialist_ref": "specialist:github-operations",
    "provider_ref": "github:github-issue-comment@v1:write",
    "effect_ref": "github-effect:issue-comment:1",
    "readback_ref": "github-readback:sha256:aaaa",
    "readback_provider_ref": "github:github-issue-comment@v1:readback",
    "evidence_ref": "github-external-readback:comment:1",
    "assurance": "external_system",
}

LESSON = {
    "lesson": "Confirm the interpreted scope, then verify the comment by independent readback.",
    "skill_name": "github-issue-comment",
    "trigger": "a governed GitHub issue comment is requested",
    "procedure": ["interpret scope", "confirm scope", "execute provider", "read back externally"],
    "intended_outcome": "one marker-bound comment exists on the configured issue",
    "preconditions": ["configured acceptance target", "mediated provider token"],
    "required_authority": "operator scope confirmation",
    "failure_modes": ["conflicting replay for the idempotency marker"],
}


def receipt(**overrides):
    payload = dict(VERIFIED_RECEIPT)
    payload.update(overrides)
    return payload


class LearningBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.memory = DurableLearningMemory(self.connection, candidate_threshold=2)
        self.extractor_calls = []
        self.boundary = GovernedLearningBoundary(self.memory, extractor=self.extractor)

    def tearDown(self):
        self.connection.close()

    def extractor(self, request, facts):
        self.extractor_calls.append((request, facts))
        return dict(LESSON)

    def context(self, request="post the governed acceptance comment", **overrides):
        payload = {
            "request": request, "mode": "ACT", "interpreted_scope": ("github", "production"),
            "source_revision": "a" * 40, "environment": "production", "instance_id": "dbsrv",
            "model_ref": "cloudflare:openai-compatible:model-a",
            "target_ref": "github:ohanyan88-cmd/BRO:issue:45",
        }
        payload.update(overrides)
        return ExperienceContext(**payload)

    # ---------------------------------------------------------- eligibility
    def test_verified_receipt_is_eligible(self):
        self.assertIs(self.boundary.eligibility(receipt()), LearningEligibility.ELIGIBLE)

    def test_missing_evidence_is_not_eligible(self):
        self.assertIs(self.boundary.eligibility(receipt(readback_ref="")), LearningEligibility.MISSING_EVIDENCE)

    def test_repository_assurance_is_not_eligible(self):
        self.assertIs(self.boundary.eligibility(receipt(assurance="repository")), LearningEligibility.INSUFFICIENT_ASSURANCE)
        self.assertNotIn("repository", EXTERNAL_ASSURANCE)

    def test_self_attested_receipt_is_not_eligible(self):
        same = receipt(readback_provider_ref="github:github-issue-comment@v1:write")
        self.assertIs(self.boundary.eligibility(same), LearningEligibility.SELF_ATTESTED)
        echoed = receipt(readback_ref=VERIFIED_RECEIPT["effect_ref"])
        self.assertIs(self.boundary.eligibility(echoed), LearningEligibility.SELF_ATTESTED)

    # ------------------------------------------------- experience vs lesson
    def test_unverified_success_is_experience_but_never_a_lesson(self):
        submission = self.boundary.submit_success(self.context(), receipt(assurance="repository"))
        self.assertIs(submission.eligibility, LearningEligibility.INSUFFICIENT_ASSURANCE)
        self.assertTrue(submission.recorded)
        self.assertFalse(submission.became_lesson)
        self.assertEqual(self.extractor_calls, [], "an ineligible outcome must not reach the model extractor")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bro_learned_lessons").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bro_learning_experience").fetchone()[0], 1)

    def test_failed_act_is_experience_and_cannot_count_as_success(self):
        self.boundary.submit_success(self.context(), receipt())
        before = self.memory.lesson(self.boundary.pattern_key(self.context(), receipt()))
        self.boundary.submit_failure(self.context(), error_ref="GitHubProviderRejected:status 403", receipt=receipt())
        after = self.memory.lesson(before.pattern_key)
        self.assertEqual(after.successes, before.successes)
        self.assertEqual(after.failures, 1)
        self.assertLess(after.confidence, before.confidence)
        self.assertIs(after.status, LessonStatus.DISPUTED)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bro_failure_observations").fetchone()[0], 1)

    def test_experience_record_captures_the_governed_facts(self):
        self.boundary.submit_success(self.context(), receipt())
        row = self.connection.execute("SELECT * FROM bro_learning_experience ORDER BY sequence DESC LIMIT 1").fetchone()
        self.assertEqual(row["assurance"], "external_system")
        self.assertEqual(row["effect_ref"], VERIFIED_RECEIPT["effect_ref"])
        self.assertEqual(row["readback_ref"], VERIFIED_RECEIPT["readback_ref"])
        self.assertEqual(row["readback_provider_ref"], VERIFIED_RECEIPT["readback_provider_ref"])
        self.assertEqual(row["source_revision"], "a" * 40)
        self.assertEqual(row["environment"], "production")
        self.assertEqual(row["instance_id"], "dbsrv")
        self.assertEqual(row["model_ref"], "cloudflare:openai-compatible:model-a")
        self.assertTrue(row["pattern_key"])
        self.assertEqual(row["mode"], "ACT")

    # ------------------------------------------------------ model boundary
    def test_model_cannot_choose_the_pattern_a_lesson_is_filed_under(self):
        self.boundary.extractor = lambda request, facts: {**LESSON, "pattern_key": "attacker-chosen"}
        submission = self.boundary.submit_success(self.context(), receipt())
        expected = self.boundary.pattern_key(self.context(), receipt())
        self.assertEqual(submission.pattern_key, expected)
        self.assertNotEqual(expected, "attacker-chosen")
        stored = [row[0] for row in self.connection.execute("SELECT pattern_key FROM bro_learned_lessons")]
        self.assertEqual(stored, [expected])

    def test_the_boundary_itself_overrides_the_model_supplied_pattern_key(self):
        # The store re-asserts the runtime key as well, so this pins the boundary's own
        # override: without it the marker LEARN-MODEL-001 guards would carry no weight.
        self.boundary.extractor = lambda request, facts: {**LESSON, "pattern_key": "attacker-chosen"}
        extracted = self.boundary._extract(self.context(), receipt())
        self.assertEqual(extracted["pattern_key"], self.boundary.pattern_key(self.context(), receipt()))

    def test_model_assertion_cannot_manufacture_evidence(self):
        self.boundary.extractor = lambda request, facts: {
            **LESSON, "evidence_ref": "invented", "assurance": "production", "successes": 99,
        }
        submission = self.boundary.submit_success(self.context(), receipt(evidence_ref="", readback_ref=""))
        self.assertIs(submission.eligibility, LearningEligibility.MISSING_EVIDENCE)
        self.assertFalse(submission.became_lesson)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bro_learned_lessons").fetchone()[0], 0)

    def test_only_whitelisted_receipt_fields_reach_the_model(self):
        self.boundary.submit_success(self.context(), receipt(token="super-secret", body="private payload"))
        _, facts = self.extractor_calls[0]
        self.assertNotIn("token", facts)
        self.assertNotIn("body", facts)
        self.assertEqual(set(facts), set(VERIFIED_RECEIPT))

    def test_observations_are_runtime_facts_not_model_prose(self):
        submission = self.boundary.submit_success(self.context(), receipt())
        lesson = self.memory.lesson(submission.pattern_key)
        self.assertIn("binding:target_ref=github:ohanyan88-cmd/BRO:issue:45", lesson.observations)
        self.assertIn("binding:capability=github:github-issue-comment@v1", lesson.observations)
        self.assertIn("observed:evidence_ref=github-external-readback:comment:1", lesson.observations)
        self.assertFalse(any(LESSON["lesson"] in item for item in lesson.observations))

    def test_pattern_survives_a_different_specialist_choice(self):
        first = self.boundary.submit_success(self.context(), receipt())
        second = self.boundary.submit_success(self.context(), receipt(
            specialist_ref="specialist:completely-different",
            effect_ref="github-effect:issue-comment:2",
            readback_ref="github-readback:sha256:bbbb",
            evidence_ref="github-external-readback:comment:2",
        ))
        self.assertEqual(first.pattern_key, second.pattern_key)
        self.assertIsNotNone(second.candidate)

    # ------------------------------------------------------------ confidence
    def test_repeated_independently_evidenced_success_raises_confidence(self):
        first = self.boundary.submit_success(self.context(), receipt())
        self.assertIsNone(first.candidate)
        self.assertEqual(self.memory.lesson(first.pattern_key).confidence, 1.0)
        second = self.boundary.submit_success(self.context(), receipt(
            effect_ref="github-effect:issue-comment:2",
            readback_ref="github-readback:sha256:bbbb",
            evidence_ref="github-external-readback:comment:2",
        ))
        lesson = self.memory.lesson(second.pattern_key)
        self.assertEqual(lesson.successes, 2)
        self.assertIs(lesson.status, LessonStatus.ACTIVE)

    def test_a_lesson_can_be_marked_stale_and_retired(self):
        submission = self.boundary.submit_success(self.context(), receipt())
        stale = self.memory.mark_stale(submission.pattern_key, reason="target retired", observed_by="gev")
        self.assertIs(stale.status, LessonStatus.STALE)
        retired = self.memory.retire(submission.pattern_key, reason="superseded", observed_by="gev")
        self.assertIs(retired.status, LessonStatus.RETIRED)
        self.assertEqual(self.memory.relevant_lessons("governed acceptance comment github"), ())

    # -------------------------------------------------------- contradiction
    def test_contradicting_current_truth_withholds_the_lesson(self):
        self.boundary.submit_success(self.context(), receipt())
        advisory = self.boundary.advisory_context(
            "post the governed acceptance comment",
            current_truth={"target_ref": "github:someone-else/OTHER:issue:9", "environment": "production"},
        )
        self.assertEqual(advisory["lessons"], [])
        self.assertTrue(advisory["withheld_for_contradiction"])
        recorded = self.memory.contradictions()
        self.assertTrue(any(item.field_name == "target_ref" for item in recorded))

    def test_matching_current_truth_offers_the_lesson_as_advisory_only(self):
        self.boundary.submit_success(self.context(), receipt())
        advisory = self.boundary.advisory_context(
            "post the governed acceptance comment",
            current_truth={"target_ref": "github:ohanyan88-cmd/BRO:issue:45", "environment": "production"},
        )
        self.assertEqual(len(advisory["lessons"]), 1)
        self.assertTrue(advisory["advisory"])
        self.assertFalse(advisory["grants_authority"])
        self.assertEqual(advisory["withheld_for_contradiction"], [])

    def test_a_later_revision_does_not_contradict_an_earlier_lesson(self):
        self.boundary.submit_success(self.context(), receipt())
        advisory = self.boundary.advisory_context(
            "post the governed acceptance comment",
            current_truth={"source_revision": "b" * 40, "environment": "production"},
        )
        self.assertEqual(len(advisory["lessons"]), 1)
        self.assertEqual(advisory["lessons"][0]["provenance"]["source_revision"], "a" * 40)

    # ------------------------------------------------------------ candidate
    def test_candidate_carries_structured_reusable_knowledge(self):
        self.boundary.submit_success(self.context(), receipt())
        submission = self.boundary.submit_success(self.context(), receipt(
            effect_ref="github-effect:issue-comment:2",
            readback_ref="github-readback:sha256:bbbb",
            evidence_ref="github-external-readback:comment:2",
        ))
        candidate = submission.candidate
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.status, "CANDIDATE")
        self.assertEqual(candidate.intended_outcome, LESSON["intended_outcome"])
        self.assertEqual(candidate.preconditions, tuple(LESSON["preconditions"]))
        self.assertEqual(candidate.required_authority, LESSON["required_authority"])
        self.assertEqual(candidate.failure_modes, tuple(LESSON["failure_modes"]))
        self.assertEqual(candidate.supporting_executions, 2)
        self.assertTrue(candidate.verification)
        self.assertEqual(candidate.provenance.model_ref, "cloudflare:openai-compatible:model-a")

    def test_candidate_cannot_self_approve_or_self_promote_and_transitions_are_audited(self):
        self.boundary.submit_success(self.context(), receipt())
        submission = self.boundary.submit_success(self.context(), receipt(
            effect_ref="github-effect:issue-comment:2",
            readback_ref="github-readback:sha256:bbbb",
            evidence_ref="github-external-readback:comment:2",
        ))
        candidate_id = submission.candidate.candidate_id
        with self.assertRaises(LearningMemoryRejected):
            self.memory.promote_candidate(candidate_id, promoted_by="bro")
        with self.assertRaises(LearningMemoryRejected):
            self.memory.approve_candidate(candidate_id, approved_by="   ")
        self.assertEqual(self.memory.candidate(candidate_id).status, "CANDIDATE")
        self.memory.approve_candidate(candidate_id, approved_by="gev")
        self.memory.promote_candidate(candidate_id, promoted_by="gev")
        trail = self.memory.candidate_transitions(candidate_id)
        self.assertEqual([item["to_status"] for item in trail], ["CANDIDATE", "APPROVED", "PROMOTED"])
        self.assertEqual([item["actor"] for item in trail], ["runtime", "gev", "gev"])

    # ------------------------------------------------------------ fail-safe
    def test_learning_failure_never_raises_into_the_executed_action(self):
        def exploding(request, facts):
            raise RuntimeError("extractor is down")

        self.boundary.extractor = exploding
        submission = self.boundary.submit_success(self.context(), receipt())
        self.assertFalse(submission.recorded)
        self.assertIn("extractor is down", submission.error)
        self.assertIs(submission.eligibility, LearningEligibility.ELIGIBLE)

    def test_capability_class_ignores_the_operation_half(self):
        self.assertEqual(
            self.boundary.capability_class("github:github-issue-comment@v1:write"),
            self.boundary.capability_class("github:github-issue-comment@v1:readback"),
        )


if __name__ == "__main__":
    unittest.main()
