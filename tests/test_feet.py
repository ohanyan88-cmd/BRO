import unittest

from bro_runtime import SQLiteTaskStore
from bro_runtime.feet import FeetRejected, FeetStore, RouteCheckpoint, RouteState


class FeetRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteTaskStore()
        self.addCleanup(self.db.close)
        self.feet = FeetStore(self.db.connection)
        self.feet.append(RouteCheckpoint(
            route_id="route:1", version=1, task_ref="task:1", plan_ref="plan:1@1",
            current_step_ref="step:1", current_location="github:repo", next_location="github:ci",
            unresolved_refs=("step:2",), authority_blocker_ref=None, integrity_blocker_ref=None,
            risk_blocker_ref=None, state=RouteState.ACTIVE, recorded_at="2026-09-01T00:00:00Z"))

    def test_move_creates_immutable_checkpoint(self):
        moved = self.feet.move("route:1", current_step_ref="step:2", current_location="github:ci",
                               next_location="github:merge", unresolved_refs=())
        self.assertEqual(moved.version, 2)
        self.assertEqual(moved.current_location, "github:ci")
        self.assertEqual(self.feet.latest("route:1"), moved)

    def test_blocked_route_cannot_move(self):
        self.feet.block("route:1", authority_ref="approval:1")
        with self.assertRaisesRegex(FeetRejected, "blocker resolution"):
            self.feet.move("route:1", current_step_ref="step:2", current_location="github:ci", next_location=None)

    def test_resume_requires_external_canonical_resolution(self):
        self.feet.block("route:1", authority_ref="approval:1")
        with self.assertRaisesRegex(FeetRejected, "canonical blocker refs resolve"):
            self.feet.resume("route:1", blocker_resolved=lambda _: False)
        resumed = self.feet.resume("route:1", blocker_resolved=lambda ref: ref == "approval:1")
        self.assertEqual(resumed.state, RouteState.ACTIVE)
        self.assertIsNone(resumed.authority_blocker_ref)

    def test_checkpoint_versions_are_immutable(self):
        first = self.feet.latest("route:1")
        with self.assertRaisesRegex(FeetRejected, "immutable"):
            self.feet.append(first)


if __name__ == "__main__":
    unittest.main()
