import unittest

from bro_runtime.task_runtime import SQLiteTaskStore, TaskContractViolation, TaskRuntime


class TaskAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteTaskStore()
        self.runtime = TaskRuntime(self.store)
        self.addCleanup(self.store.close)

    def test_duplicate_create_adopts_only_matching_received_task(self):
        self.runtime.create_task("task:reserved", "goal:reserved", "NERVOUS_SYSTEM", "reserved")
        adopted = self.runtime.create_task("task:reserved", "goal:reserved", "BRO", "governed open")
        self.assertEqual(adopted["state"], "RECEIVED")
        events = [row["event_type"] for row in self.store.events("task:reserved")]
        self.assertEqual(events, ["task.received", "task.adopted"])

    def test_duplicate_create_rejects_unrelated_goal(self):
        self.runtime.create_task("task:reserved", "goal:reserved", "NERVOUS_SYSTEM", "reserved")
        with self.assertRaises(TaskContractViolation):
            self.runtime.create_task("task:reserved", "goal:other", "BRO", "governed open")


if __name__ == "__main__":
    unittest.main()
