from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bro_runtime import CompletionEvidence, ConcurrencyConflict, InvalidTransition, RecoveryAssessment, SQLiteTaskStore, TaskRuntime, TaskState


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
            first = TaskRuntime(SQLiteTaskStore(path))
            task = first.create_task("task:persist", "goal:persist", "BRO", "received")
            first.transition("task:persist", TaskState.INTERPRETING, "BRO", "frame", task["revision"])
            reopened = SQLiteTaskStore(path)
            self.assertEqual(reopened.fetch_task("task:persist")["state"], TaskState.INTERPRETING)
            self.assertEqual(len(reopened.events("task:persist")), 2)


class ArchitectureAlignmentTests(unittest.TestCase):
    def test_task_schema_uses_exact_runtime_states(self) -> None:
        import json
        schema = json.loads(Path("contracts/v0.1/task.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(schema["properties"]["state"]["enum"]), {state.value for state in TaskState})


if __name__ == "__main__":
    unittest.main()

