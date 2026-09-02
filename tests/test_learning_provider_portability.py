import json
import os
import sqlite3
import tempfile
import unittest

from bro_runtime.learning_boundary import ExperienceContext, GovernedLearningBoundary
from bro_runtime.learning_memory import DurableLearningMemory, LessonStatus

MODEL_A = "cloudflare:openai-compatible:@cf/meta/llama-3.3-70b-instruct-fp8-fast"
MODEL_B = "some-other-vendor:openai-compatible:another-model-v2"

RECEIPT = {
    "specialist_ref": "specialist:github-operations",
    "provider_ref": "github:github-issue-comment@v1:write",
    "effect_ref": "github-effect:issue-comment:1",
    "readback_ref": "github-readback:sha256:aaaa",
    "readback_provider_ref": "github:github-issue-comment@v1:readback",
    "evidence_ref": "github-external-readback:comment:1",
    "assurance": "external_system",
}

LESSON = {
    "lesson": "Confirm scope, execute the governed provider, then verify by independent readback.",
    "skill_name": "github-issue-comment",
    "trigger": "a governed GitHub issue comment is requested",
    "procedure": ["confirm scope", "execute provider", "read back externally"],
}

REQUEST = "post the governed acceptance comment on the configured issue"


def receipt(n):
    return {
        **RECEIPT,
        "effect_ref": f"github-effect:issue-comment:{n}",
        "readback_ref": f"github-readback:sha256:{n:04d}",
        "evidence_ref": f"github-external-readback:comment:{n}",
    }


def context(model_ref):
    return ExperienceContext(
        request=REQUEST, mode="ACT", interpreted_scope=("github", "production"),
        source_revision="c" * 40, environment="production", instance_id="dbsrv",
        model_ref=model_ref, target_ref="github:ohanyan88-cmd/BRO:issue:45",
    )


class ProviderPortabilityTests(unittest.TestCase):
    """BRO owns what it learned. A model is provenance, never the owner."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, "runtime.sqlite3")

    def learn_with(self, model_ref, occurrences):
        connection = sqlite3.connect(self.path)
        try:
            boundary = GovernedLearningBoundary(
                DurableLearningMemory(connection, candidate_threshold=2),
                extractor=lambda request, facts: dict(LESSON),
            )
            submissions = [boundary.submit_success(context(model_ref), receipt(n)) for n in occurrences]
        finally:
            connection.close()
        return submissions

    def reopen(self):
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        return DurableLearningMemory(connection, candidate_threshold=2)

    def test_lesson_learned_under_one_model_is_reusable_under_another(self):
        created = self.learn_with(MODEL_A, [1, 2])
        pattern_key = created[0].pattern_key
        self.assertIsNotNone(created[1].candidate)

        # A completely separate process, a different configured model, same durable state.
        memory = self.reopen()
        boundary = GovernedLearningBoundary(memory, extractor=lambda request, facts: dict(LESSON))
        advisory = boundary.advisory_context(
            "please add the governed acceptance comment to the configured issue",
            current_truth={"environment": "production", "target_ref": "github:ohanyan88-cmd/BRO:issue:45"},
        )
        self.assertEqual([item["pattern_key"] for item in advisory["lessons"]], [pattern_key])
        self.assertEqual(advisory["lessons"][0]["guidance"], LESSON["lesson"])
        self.assertEqual(advisory["lessons"][0]["provenance"]["model_ref"], MODEL_A)

    def test_a_new_model_reinforces_the_same_bro_owned_pattern(self):
        first = self.learn_with(MODEL_A, [1, 2])
        second = self.learn_with(MODEL_B, [3])
        self.assertEqual(first[0].pattern_key, second[0].pattern_key)
        lesson = self.reopen().lesson(first[0].pattern_key)
        self.assertEqual(lesson.successes, 3)
        self.assertIs(lesson.status, LessonStatus.ACTIVE)
        self.assertEqual(lesson.provenance.model_ref, MODEL_B, "latest provenance follows the current model")
        self.assertTrue(lesson.provenance.first_seen_at, "the first sighting is preserved across the switch")

    def test_candidate_survives_the_provider_switch_and_stays_a_candidate(self):
        created = self.learn_with(MODEL_A, [1, 2])
        candidate_id = created[1].candidate.candidate_id
        self.learn_with(MODEL_B, [3])
        candidate = self.reopen().candidate(candidate_id)
        self.assertEqual(candidate.status, "CANDIDATE")
        self.assertEqual(candidate.supporting_executions, 3)

    def test_durable_schema_carries_no_provider_specific_semantics(self):
        self.learn_with(MODEL_A, [1, 2])
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        schema = "\n".join(
            str(row[0]) for row in connection.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        ).lower()
        for vendor in ("cloudflare", "openai", "anthropic", "llama", "gpt", "gemini", "workers-ai"):
            self.assertNotIn(vendor, schema, f"storage schema must not encode {vendor} semantics")

    def test_model_identity_is_stored_as_data_never_as_a_key(self):
        self.learn_with(MODEL_A, [1, 2])
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT pattern_key,provenance_json FROM bro_learned_lessons").fetchone()
        self.assertNotIn(MODEL_A, row["pattern_key"])
        self.assertEqual(json.loads(row["provenance_json"])["model_ref"], MODEL_A)


if __name__ == "__main__":
    unittest.main()
