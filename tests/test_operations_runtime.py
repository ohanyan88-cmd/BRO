import tempfile
import unittest
from pathlib import Path

from bro_runtime.operations_runtime import RuntimeOperations
from bro_runtime.provider_lifecycle import ProviderLifecycleStore
from bro_runtime.service_runtime import SQLiteWorkQueue, WorkState
from bro_runtime.task_runtime import SQLiteTaskStore, TaskRuntime


class RuntimeOperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "bro.sqlite"
        self.store = SQLiteTaskStore(self.db)
        self.tasks = TaskRuntime(self.store)
        self.queue = SQLiteWorkQueue(self.store.connection)
        self.providers = ProviderLifecycleStore(self.store.connection, failure_threshold=2)
        self.ops = RuntimeOperations(self.store.connection)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_health_projects_queue_provider_and_task_state(self):
        self.tasks.create_task("task:ops", "goal:ops", "BRO", "ops test")
        item = self.queue.enqueue("task:ops")
        leased = self.queue.claim("worker:ops", now_epoch=1000.0, lease_seconds=30)
        self.assertIsNotNone(leased)
        self.queue.settle(leased, WorkState.BLOCKED)
        self.providers.register("github", "github-issue-comment", "v1")
        self.providers.failure("github", "github-issue-comment", "v1", "timeout")
        health = self.ops.health()
        self.assertEqual(health.state, "DEGRADED")
        self.assertIn(("BLOCKED", 1), health.queue_counts)
        self.assertIn(("DEGRADED", 1), health.provider_counts)
        self.assertTrue(health.integrity_ok)

    def test_backup_is_verified_and_task_audit_remains_available(self):
        self.tasks.create_task("task:audit", "goal:audit", "BRO", "audit test")
        audit = self.ops.task_audit("task:audit")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["event_type"], "task.received")
        receipt = self.ops.backup(Path(self.tmp.name) / "backup.sqlite")
        self.assertTrue(receipt.integrity_ok)
        self.assertEqual(len(receipt.sha256), 64)
        self.assertTrue(Path(receipt.path).is_file())


if __name__ == "__main__":
    unittest.main()
