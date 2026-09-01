from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bro_runtime import (
    CompletionEvidence,
    ConcurrencyConflict,
    InvalidTransition,
    RecoveryAssessment,
    SQLiteTaskStore,
    TaskContractViolation,
    TaskRuntime,
    TaskState,
)
from bro_runtime.task_runtime import AUTHORITY_STATES


def complete_evidence() -> CompletionEvidence:
    return CompletionEvidence(True, True, True, True, ("evidence:1",), True, True, True, True)


class TaskRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = SQLiteTaskStore()
        self.runtime = TaskRuntime(self.store)
        self.task = self.runtime.create_task("task:1", "goal:1", "BRO", "intent preserved")

    def advance_to(self, target: TaskState) -> dict:
        order = [TaskState.INTERPRETING, TaskState.READY, TaskState.PLANNING, TaskState.AUTHORIZING, TaskState.EXECUTING, TaskState.VERIFYING]
        task = self.store.fetch_task("task:1")
        for state in order:
            task = self.runtime.transition("task:1", state, "BRO", f"enter {state}", task["revision"])
            if state is target:
                break
        return task

    def test_primary_lifecycle_completes_only_with_evidence(self) -> None:
        task = self.advance_to(TaskState.VERIFYING)
        task = self.runtime.transition("task:1", TaskState.COMPLETED, "BRO", "verified outcome", task["revision"], completion=complete_evidence())
        self.assertEqual(task["state"], TaskState.COMPLETED)
        self.assertEqual(task["evidence_refs"], ["evidence:1"])
        self.assertEqual(len(self.store.events("task:1")), 8)

    def test_completion_without_evidence_fails_closed(self) -> None:
        task = self.advance_to(TaskState.VERIFYING)
        with self.assertRaisesRegex(InvalidTransition, "explicit evidence"):
            self.runtime.transition("task:1", TaskState.COMPLETED, "BRO", "claim", task["revision"])

    def test_terminal_state_is_immutable(self) -> None:
        task = self.advance_to(TaskState.VERIFYING)
        task = self.runtime.transition("task:1", TaskState.COMPLETED, "BRO", "verified", task["revision"], completion=complete_evidence())
        with self.assertRaisesRegex(InvalidTransition, "terminal"):
            self.runtime.transition("task:1", TaskState.EXECUTING, "BRO", "rewrite", task["revision"])

    def test_pause_requires_checkpoint_and_resumes_recorded_path(self) -> None:
        task = self.advance_to(TaskState.EXECUTING)
        with self.assertRaisesRegex(InvalidTransition, "checkpoint"):
            self.runtime.transition("task:1", TaskState.PAUSED, "user", "pause", task["revision"])
        task = self.runtime.transition("task:1", TaskState.PAUSED, "user", "pause", task["revision"], resume_checkpoint_ref="checkpoint:7")
        with self.assertRaisesRegex(InvalidTransition, "recorded active path"):
            self.runtime.transition("task:1", TaskState.VERIFYING, "BRO", "wrong resume", task["revision"])
        task = self.runtime.transition("task:1", TaskState.EXECUTING, "BRO", "resume", task["revision"])
        self.assertEqual(task["state"], TaskState.EXECUTING)

    def test_unknown_effect_recovery_blocks_and_never_replays(self) -> None:
        task = self.advance_to(TaskState.EXECUTING)
        assessment = RecoveryAssessment(True, True, True, "UNKNOWN", True, True, ("evidence:reality-check",), "decision:recover")
        task = self.runtime.recover("task:1", assessment, "BRO", "worker lease expired", task["revision"])
        self.assertEqual(task["state"], TaskState.BLOCKED)
        events = self.store.events("task:1")[-2:]
        self.assertTrue(all('"command_replayed": false' in event["payload"] for event in events))

    def test_confirmed_effect_recovery_routes_to_verification(self) -> None:
        task = self.advance_to(TaskState.EXECUTING)
        assessment = RecoveryAssessment(True, True, True, "CONFIRMED", True, True, ("evidence:external-state",), "decision:verify")
        task = self.runtime.recover("task:1", assessment, "BRO", "reconcile", task["revision"])
        self.assertEqual(task["state"], TaskState.VERIFYING)

    def test_stale_revision_cannot_overwrite_current_state(self) -> None:
        stale = self.task["revision"]
        self.runtime.transition("task:1", TaskState.INTERPRETING, "BRO", "frame", stale)
        with self.assertRaises(ConcurrencyConflict):
            self.runtime.transition("task:1", TaskState.INTERPRETING, "worker", "stale write", stale)

    def test_sqlite_persists_state_and_events_across_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.db"
            store = SQLiteTaskStore(path)
            first = TaskRuntime(store)
            task = first.create_task("task:persist", "goal:persist", "BRO", "received")
            first.transition("task:persist", TaskState.INTERPRETING, "BRO", "frame", task["revision"])
            store.close()
            reopened = SQLiteTaskStore(path)
            try:
                self.assertEqual(reopened.fetch_task("task:persist")["state"], TaskState.INTERPRETING)
                self.assertEqual(len(reopened.events("task:persist")), 2)
            finally:
                reopened.close()


class CanonicalTaskRecordTests(unittest.TestCase):
    """The stored Task must be projectable into contracts/v0.1/task.schema.json."""

    def setUp(self) -> None:
        self.store = SQLiteTaskStore()
        self.runtime = TaskRuntime(self.store)
        self.runtime.create_task("task:1", "goal:1", "BRO", "received")

    def tearDown(self) -> None:
        self.store.close()

    def advance(self) -> dict:
        task = self.store.fetch_task("task:1")
        task = self.runtime.transition("task:1", TaskState.INTERPRETING, "BRO", "frame", task["revision"])
        task = self.runtime.transition("task:1", TaskState.READY, "BRO", "ready", task["revision"])
        task = self.runtime.transition("task:1", TaskState.PLANNING, "BRO", "plan", task["revision"],
                                       plan_ref="plan:1", plan_revision=1)
        return self.runtime.transition("task:1", TaskState.AUTHORIZING, "BRO", "authorize", task["revision"],
                                       context_manifest_ref="context:1", authority_state="ALLOWED")

    def test_unbound_task_cannot_be_projected(self) -> None:
        with self.assertRaisesRegex(TaskContractViolation, "plan_ref"):
            self.store.canonical_task("task:1")

    def test_bound_task_matches_the_canonical_contract(self) -> None:
        self.advance()
        record = self.store.canonical_task("task:1")
        schema = json.loads(Path("contracts/v0.1/task.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(record), set(schema["properties"]))
        self.assertEqual(set(schema["required"]) - set(record), set())
        self.assertEqual(record["accountable_identity"], "BRO")
        self.assertEqual(record["authority_state"], "ALLOWED")
        self.assertEqual(record["plan_ref"], "plan:1")
        self.assertEqual(record["context_manifest_ref"], "context:1")

    def test_operational_columns_stay_out_of_the_canonical_record(self) -> None:
        self.advance()
        record = self.store.canonical_task("task:1")
        for operational in ("prior_active_state", "resume_checkpoint_ref"):
            self.assertIn(operational, self.store.fetch_task("task:1"))
            self.assertNotIn(operational, record)

    def test_unknown_authority_state_fails_closed(self) -> None:
        task = self.store.fetch_task("task:1")
        with self.assertRaisesRegex(InvalidTransition, "authority state"):
            self.runtime.transition("task:1", TaskState.INTERPRETING, "BRO", "frame", task["revision"],
                                    authority_state="PROBABLY_FINE")

    def test_legacy_database_migrates_and_keeps_its_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.db"
            legacy = sqlite3.connect(path)
            legacy.executescript(
                """
                CREATE TABLE tasks (
                    task_id TEXT PRIMARY KEY, goal_ref TEXT NOT NULL, state TEXT NOT NULL,
                    prior_active_state TEXT, resume_checkpoint_ref TEXT,
                    evidence_refs TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, termination_reason TEXT
                );
                CREATE TABLE runtime_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id), event_type TEXT NOT NULL,
                    actor TEXT NOT NULL, reason TEXT NOT NULL, prior_state TEXT, new_state TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, correlation_ref TEXT NOT NULL, causal_ref TEXT,
                    payload TEXT NOT NULL, schema_version TEXT NOT NULL
                );
                INSERT INTO tasks VALUES ('task:legacy','goal:legacy','EXECUTING',NULL,NULL,'["evidence:old"]',4,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',NULL);
                """
            )
            legacy.commit()
            legacy.close()

            store = SQLiteTaskStore(path)
            try:
                task = store.fetch_task("task:legacy")
                self.assertEqual(task["revision"], 4)
                self.assertEqual(task["evidence_refs"], ["evidence:old"])
                self.assertEqual(task["accountable_identity"], "BRO")
                self.assertEqual(task["authority_state"], "UNASSESSED")
                self.assertEqual(task["artifact_refs"], [])
                with self.assertRaises(TaskContractViolation):
                    store.canonical_task("task:legacy")
                runtime = TaskRuntime(store)
                runtime.transition("task:legacy", TaskState.VERIFYING, "BRO", "resume after migration", 4,
                                   plan_ref="plan:legacy", plan_revision=2, context_manifest_ref="context:legacy",
                                   authority_state="ALLOWED")
                self.assertEqual(store.canonical_task("task:legacy")["plan_revision"], 2)
            finally:
                store.close()


class ArchitectureAlignmentTests(unittest.TestCase):
    def test_task_schema_uses_exact_runtime_states(self) -> None:
        schema = json.loads(Path("contracts/v0.1/task.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["properties"]["state"]["enum"]), {state.value for state in TaskState})

    def test_task_schema_authority_states_match_the_runtime(self) -> None:
        schema = json.loads(Path("contracts/v0.1/task.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["properties"]["authority_state"]["enum"]), set(AUTHORITY_STATES))


if __name__ == "__main__":
    unittest.main()

