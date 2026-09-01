from __future__ import annotations

import sqlite3
import unittest

from bro_runtime import AssignmentRejected, AssignmentState, SpecialistAssignment, StaleWorkerResult, Supervisor


def assignment() -> SpecialistAssignment:
    return SpecialistAssignment("assignment:1", "task:1", "step:1", "project:BRO", "capability:code", "context:1", "contract:output", "auth:1", ("repo:BRO",), None, {"seconds": 60}, ("tests",))


class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supervisor = Supervisor(sqlite3.connect(":memory:"))
        self.supervisor.create_assignment(assignment(), "BRO", "2026-09-01T00:00:00Z")

    def test_claim_is_serialized_and_scoped(self) -> None:
        grant = self.supervisor.claim("assignment:1", "worker:1", "2026-09-01T00:00:01Z")
        self.assertEqual(grant.project_boundary, "project:BRO")
        self.assertEqual(grant.context_manifest_ref, "context:1")
        with self.assertRaisesRegex(AssignmentRejected, "not claimable|active lease"):
            self.supervisor.claim("assignment:1", "worker:2", "2026-09-01T00:00:02Z")

    def test_heartbeat_extends_only_current_lease(self) -> None:
        grant = self.supervisor.claim("assignment:1", "worker:1", "2026-09-01T00:00:01Z", 10)
        renewed = self.supervisor.heartbeat(grant, "2026-09-01T00:00:05Z", 20)
        self.assertEqual(renewed.expires_at, "2026-09-01T00:00:25Z")

    def test_expiry_enters_recovery_without_replay(self) -> None:
        self.supervisor.claim("assignment:1", "worker:1", "2026-09-01T00:00:01Z", 5)
        self.assertEqual(self.supervisor.expire_leases("2026-09-01T00:00:07Z"), ["assignment:1"])
        self.assertEqual(self.supervisor.get_assignment("assignment:1")["state"], AssignmentState.RECOVERING)
        self.assertIn('"command_replayed": false', self.supervisor.events("assignment:1")[-1]["payload"])

    def test_reclaim_increments_fencing_and_rejects_stale_result(self) -> None:
        old = self.supervisor.claim("assignment:1", "worker:old", "2026-09-01T00:00:01Z", 5)
        self.supervisor.expire_leases("2026-09-01T00:00:07Z")
        new = self.supervisor.claim("assignment:1", "worker:new", "2026-09-01T00:00:08Z")
        self.assertGreater(new.fencing_token, old.fencing_token)
        with self.assertRaises(StaleWorkerResult):
            self.supervisor.submit_result(old, AssignmentState.SUCCEEDED, "artifact:old", ("evidence:old",), (), "2026-09-01T00:00:09Z")

    def test_success_requires_evidence_and_settles_lease(self) -> None:
        grant = self.supervisor.claim("assignment:1", "worker:1", "2026-09-01T00:00:01Z")
        with self.assertRaisesRegex(AssignmentRejected, "evidence"):
            self.supervisor.submit_result(grant, AssignmentState.SUCCEEDED, "artifact:1", (), (), "2026-09-01T00:00:02Z")
        result = self.supervisor.submit_result(grant, AssignmentState.SUCCEEDED, "artifact:1", ("evidence:1",), (), "2026-09-01T00:00:03Z")
        self.assertEqual(result["result_state"], AssignmentState.SUCCEEDED)
        with self.assertRaises(StaleWorkerResult):
            self.supervisor.submit_result(grant, AssignmentState.SUCCEEDED, "artifact:2", ("evidence:2",), (), "2026-09-01T00:00:04Z")

    def test_partial_result_preserves_limitations(self) -> None:
        grant = self.supervisor.claim("assignment:1", "worker:1", "2026-09-01T00:00:01Z")
        with self.assertRaisesRegex(AssignmentRejected, "limitations"):
            self.supervisor.submit_result(grant, AssignmentState.PARTIAL, "artifact:1", ("evidence:1",), (), "2026-09-01T00:00:02Z")
        result = self.supervisor.submit_result(grant, AssignmentState.PARTIAL, "artifact:1", ("evidence:1",), ("missing integration",), "2026-09-01T00:00:03Z")
        self.assertIn("missing integration", result["limitations"])

    def test_missing_boundaries_fail_closed(self) -> None:
        other = Supervisor(sqlite3.connect(":memory:"))
        invalid = SpecialistAssignment("a", "t", "s", "", "c", "ctx", "out", "auth", (), None, {}, ())
        with self.assertRaisesRegex(AssignmentRejected, "boundaries"):
            other.create_assignment(invalid, "BRO", "2026-09-01T00:00:00Z")


if __name__ == "__main__": unittest.main()
