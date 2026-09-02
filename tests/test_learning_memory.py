import sqlite3
import unittest

from bro_runtime.learning_memory import DurableLearningMemory, LearningMemoryRejected


class DurableLearningMemoryTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.memory = DurableLearningMemory(self.connection, candidate_threshold=2)

    def tearDown(self):
        self.connection.close()

    def learning(self):
        return {
            "pattern_key": "github:issue-comment",
            "lesson": "Use the governed GitHub issue-comment provider and verify by independent readback.",
            "skill_name": "github-issue-comment",
            "trigger": "When a request needs a governed GitHub issue comment",
            "procedure": ["interpret scope", "confirm material scope", "execute provider", "read back externally"],
        }

    def test_conversation_history_is_durable(self):
        self.memory.append_message("user", "remember this", mode="TALK")
        self.memory.append_message("assistant", "remembered", mode="TALK")
        reopened = DurableLearningMemory(self.connection)
        self.assertEqual(
            reopened.recent_messages(),
            ({"role": "user", "content": "remember this"}, {"role": "assistant", "content": "remembered"}),
        )

    def test_repeated_evidenced_success_creates_candidate_but_not_active_skill(self):
        first = self.memory.record_outcome(
            request="comment on github issue",
            success=True,
            specialist_ref="specialist:github",
            evidence_ref="github-readback:1",
            learning=self.learning(),
        )
        self.assertIsNone(first)
        second = self.memory.record_outcome(
            request="comment on github issue again",
            success=True,
            specialist_ref="specialist:github",
            evidence_ref="github-readback:2",
            learning=self.learning(),
        )
        self.assertEqual(second.status, "CANDIDATE")
        with self.assertRaises(LearningMemoryRejected):
            self.memory.promote_candidate(second.candidate_id, promoted_by="bro")

    def test_candidate_requires_explicit_approval_before_promotion(self):
        for suffix in ("one", "two"):
            candidate = self.memory.record_outcome(
                request=f"github comment {suffix}",
                success=True,
                specialist_ref="specialist:github",
                evidence_ref=f"github-readback:{suffix}",
                learning=self.learning(),
            )
        approved = self.memory.approve_candidate(candidate.candidate_id, approved_by="gev")
        self.assertEqual(approved.status, "APPROVED")
        promoted = self.memory.promote_candidate(candidate.candidate_id, promoted_by="gev")
        self.assertEqual(promoted.status, "PROMOTED")

    def test_success_without_external_evidence_cannot_be_learned(self):
        with self.assertRaises(LearningMemoryRejected):
            self.memory.record_outcome(
                request="pretend success",
                success=True,
                specialist_ref="specialist:github",
                evidence_ref="",
                learning=self.learning(),
            )

    def test_failed_outcome_does_not_create_lesson(self):
        self.memory.record_outcome(request="broken action", success=False, error_ref="RuntimeError:boom")
        rows = self.connection.execute("SELECT COUNT(*) FROM bro_learned_lessons").fetchone()[0]
        self.assertEqual(rows, 0)

    def test_relevant_lessons_are_retrievable_for_reuse(self):
        for suffix in ("one", "two"):
            self.memory.record_outcome(
                request=f"github issue comment {suffix}",
                success=True,
                specialist_ref="specialist:github",
                evidence_ref=f"github-readback:{suffix}",
                learning=self.learning(),
            )
        lessons = self.memory.relevant_lessons("Please add a github issue comment")
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0].skill_name, "github-issue-comment")
        self.assertEqual(lessons[0].successes, 2)


if __name__ == "__main__":
    unittest.main()
