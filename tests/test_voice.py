import unittest

from bro_runtime.voice import VoiceInput, VoiceRuntime, VoiceState


class VoiceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.voice = VoiceRuntime()

    def project(self, **changes):
        base = dict(
            task_ref="task:1", task_state="EXECUTING", authority_state="ALLOW",
            evidence_state="PENDING", effect_state="NONE", completion_state="PENDING",
            uncertainty=(), blocker_ref=None,
        )
        base.update(changes)
        return self.voice.project(VoiceInput(**base))

    def test_tool_or_effect_success_never_becomes_completion_without_verified_gate(self):
        projection = self.project(effect_state="CONFIRMED")
        self.assertEqual(projection.state, VoiceState.ATTEMPTED)
        self.assertNotEqual(projection.state, VoiceState.COMPLETED)

    def test_unknown_effect_is_attempted_and_explicit(self):
        projection = self.project(effect_state="UNKNOWN", uncertainty=("external state not reconciled",))
        self.assertEqual(projection.state, VoiceState.ATTEMPTED)
        self.assertIn("unknown effect", projection.detail)
        self.assertEqual(projection.uncertainty, ("external state not reconciled",))

    def test_authority_blocker_wins_over_other_progress(self):
        projection = self.project(
            task_state="EXECUTING", authority_state="APPROVAL_REQUIRED",
            evidence_state="VERIFIED", effect_state="CONFIRMED", completion_state="VERIFIED",
            blocker_ref="approval:1",
        )
        self.assertEqual(projection.state, VoiceState.BLOCKED)
        self.assertEqual(projection.blocker_ref, "approval:1")

    def test_completed_requires_verified_completion_and_evidence(self):
        not_done = self.project(task_state="VERIFYING", evidence_state="PENDING", completion_state="VERIFIED")
        self.assertNotEqual(not_done.state, VoiceState.COMPLETED)
        done = self.project(task_state="COMPLETED", evidence_state="VERIFIED", completion_state="VERIFIED")
        self.assertEqual(done.state, VoiceState.COMPLETED)

    def test_verified_evidence_without_completion_stays_verified(self):
        projection = self.project(task_state="VERIFYING", evidence_state="VERIFIED", completion_state="PENDING")
        self.assertEqual(projection.state, VoiceState.VERIFIED)


if __name__ == "__main__":
    unittest.main()
