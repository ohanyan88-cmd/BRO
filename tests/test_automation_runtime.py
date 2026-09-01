from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bro_runtime.automation import AutomationDispatcher, AutomationRuntime, AutomationStatus, MisfirePolicy, OccurrenceState
from bro_runtime.task_runtime import SQLiteTaskStore, TaskRuntime


class AutomationRuntimeTests(unittest.TestCase):
    def test_dispatcher_materializes_reserved_task_once_and_never_grants_authority(self) -> None:
        store = SQLiteTaskStore()
        automation = AutomationRuntime(store.connection)
        automation.create_interval(
            automation_id="automation:daily-ops",
            project_boundary="project:BRO",
            desired_outcome="Run governed operations check",
            interval_seconds=3600,
            first_due_at="2026-09-01T10:00:00Z",
        )
        dispatcher = AutomationDispatcher(automation, TaskRuntime(store))
        first = dispatcher.tick(now="2026-09-01T10:00:00Z")[0]
        second = dispatcher.tick(now="2026-09-01T10:30:00Z")
        self.assertEqual(second, ())
        self.assertEqual(first.state, OccurrenceState.TASK_CREATED)
        task = store.fetch_task(first.task_ref)
        self.assertEqual(task["state"], "RECEIVED")
        self.assertEqual(task["authority_state"], "UNASSESSED")
        self.assertEqual(len(automation.occurrences("automation:daily-ops")), 1)

    def test_restart_reconciles_reserved_task_without_duplicate_after_crash_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bro.db"
            first_store = SQLiteTaskStore(path)
            first_automation = AutomationRuntime(first_store.connection)
            first_automation.create_interval(
                automation_id="automation:restart",
                project_boundary="project:BRO",
                desired_outcome="Continue after restart",
                interval_seconds=60,
                first_due_at="2026-09-01T10:00:00Z",
            )
            reserved = first_automation.claim_due(now="2026-09-01T10:00:00Z")[0]
            task_runtime = TaskRuntime(first_store)
            task_runtime.create_task(reserved.task_ref, "automation-goal:automation:restart", "NERVOUS_SYSTEM", "simulated crash after Task create", correlation_ref=reserved.occurrence_id)
            self.assertEqual(first_automation.fetch_occurrence(reserved.occurrence_id).state, OccurrenceState.TASK_RESERVED)
            first_store.close()

            second_store = SQLiteTaskStore(path)
            second_automation = AutomationRuntime(second_store.connection)
            reconciled = AutomationDispatcher(second_automation, TaskRuntime(second_store)).reconcile_pending()
            self.assertEqual(len(reconciled), 1)
            self.assertEqual(reconciled[0].task_ref, reserved.task_ref)
            self.assertEqual(reconciled[0].state, OccurrenceState.TASK_CREATED)
            count = second_store.connection.execute("SELECT COUNT(*) AS count FROM tasks WHERE task_id=?", (reserved.task_ref,)).fetchone()["count"]
            self.assertEqual(count, 1)
            second_store.close()

    def test_coalesce_skips_missed_backlog_and_advances_after_now(self) -> None:
        store = SQLiteTaskStore()
        runtime = AutomationRuntime(store.connection)
        runtime.create_interval(
            automation_id="automation:coalesce",
            project_boundary="project:BRO",
            desired_outcome="Coalesce stale wakeups",
            interval_seconds=60,
            first_due_at="2026-09-01T10:00:00Z",
            misfire_policy=MisfirePolicy.COALESCE,
        )
        claimed = runtime.claim_due(now="2026-09-01T10:05:30Z")
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].due_at, "2026-09-01T10:00:00Z")
        self.assertEqual(runtime.fetch("automation:coalesce").next_due_at, "2026-09-01T10:06:00Z")

    def test_catch_up_is_bounded_per_tick(self) -> None:
        store = SQLiteTaskStore()
        runtime = AutomationRuntime(store.connection)
        runtime.create_interval(
            automation_id="automation:catch-up",
            project_boundary="project:BRO",
            desired_outcome="Bound recovery burst",
            interval_seconds=60,
            first_due_at="2026-09-01T10:00:00Z",
            misfire_policy=MisfirePolicy.CATCH_UP,
            max_catch_up=3,
        )
        claimed = runtime.claim_due(now="2026-09-01T10:05:00Z")
        self.assertEqual([item.due_at for item in claimed], ["2026-09-01T10:00:00Z", "2026-09-01T10:01:00Z", "2026-09-01T10:02:00Z"])
        self.assertEqual(runtime.fetch("automation:catch-up").next_due_at, "2026-09-01T10:03:00Z")

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
