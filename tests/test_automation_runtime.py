from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bro_runtime.automation import AutomationRuntime, AutomationStatus
from bro_runtime.task_runtime import SQLiteTaskStore, TaskRuntime


class AutomationRuntimeTests(unittest.TestCase):
    def test_due_occurrence_materializes_one_canonical_task_and_never_duplicates(self) -> None:
        store = SQLiteTaskStore()
        automation = AutomationRuntime(store.connection)
        automation.create_interval(
            automation_id="automation:daily-ops",
            project_boundary="project:BRO",
            desired_outcome="Run governed operations check",
            interval_seconds=3600,
            first_due_at="2026-09-01T10:00:00Z",
        )
        occurrence = automation.claim_due(now="2026-09-01T10:00:00Z")[0]
        advanced = automation.fetch("automation:daily-ops")
        self.assertEqual(advanced.next_due_at, "2026-09-01T11:00:00Z")
        self.assertEqual(advanced.revision, 2)
        runtime = TaskRuntime(store)

        def factory(definition, claimed):
            task_id = f"task:{claimed.occurrence_id}"
            runtime.create_task(task_id, f"automation-goal:{definition.automation_id}", "NERVOUS_SYSTEM", "automation occurrence became canonical work", correlation_ref=claimed.occurrence_id)
            return task_id

        first = automation.materialize_task(occurrence.occurrence_id, factory)
        second = automation.materialize_task(occurrence.occurrence_id, factory)
        self.assertEqual(first.task_ref, second.task_ref)
        self.assertEqual(store.fetch_task(first.task_ref)["state"], "RECEIVED")
        self.assertEqual(len(automation.occurrences("automation:daily-ops")), 1)
        self.assertEqual(automation.claim_due(now="2026-09-01T10:30:00Z"), ())

    def test_restart_keeps_schedule_and_does_not_reclaim_same_due_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bro.db"
            first_store = SQLiteTaskStore(path)
            first = AutomationRuntime(first_store.connection)
            first.create_interval(
                automation_id="automation:restart",
                project_boundary="project:BRO",
                desired_outcome="Continue after restart",
                interval_seconds=60,
                first_due_at="2026-09-01T10:00:00Z",
            )
            claimed = first.claim_due(now="2026-09-01T10:00:00Z")
            self.assertEqual(len(claimed), 1)
            first_store.close()

            second_store = SQLiteTaskStore(path)
            second = AutomationRuntime(second_store.connection)
            self.assertEqual(second.claim_due(now="2026-09-01T10:00:30Z"), ())
            next_claim = second.claim_due(now="2026-09-01T10:01:00Z")
            self.assertEqual(len(next_claim), 1)
            self.assertEqual(next_claim[0].due_at, "2026-09-01T10:01:00Z")
            second_store.close()

    def test_paused_automation_cannot_wake_work(self) -> None:
        store = SQLiteTaskStore()
        runtime = AutomationRuntime(store.connection)
        runtime.create_interval(
            automation_id="automation:paused",
            project_boundary="project:BRO",
            desired_outcome="Do not run while paused",
            interval_seconds=60,
            first_due_at="2026-09-01T10:00:00Z",
        )
        runtime.set_status("automation:paused", AutomationStatus.PAUSED)
        self.assertEqual(runtime.claim_due(now="2026-09-01T11:00:00Z"), ())

    def test_schedule_never_embeds_or_grants_authority(self) -> None:
        store = SQLiteTaskStore()
        runtime = AutomationRuntime(store.connection)
        definition = runtime.create_interval(
            automation_id="automation:no-authority",
            project_boundary="project:BRO",
            desired_outcome="Wake BRO only",
            interval_seconds=60,
            first_due_at="2026-09-01T10:00:00Z",
        )
        self.assertFalse(hasattr(definition, "authority"))
        self.assertFalse(hasattr(definition, "approval"))
        self.assertFalse(hasattr(definition, "allowed_tools"))


if __name__ == "__main__":
    unittest.main()
