import unittest

from bro_runtime import (
    MemoryClass, MemoryFreshness, MemoryRejected, MemoryStatus, MemoryStore,
    SQLiteTaskStore,
)


class MemoryRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteTaskStore()
        self.addCleanup(self.store.close)
        self.memory = MemoryStore(self.store.connection)

    def put(self, **changes):
        values = dict(
            memory_class=MemoryClass.PROJECT,
            subject="repo-head",
            scope="project:BRO",
            content={"sha": "abc"},
            source_owner="PERCEPTION",
            source_ref="observation:1",
            authority_ref="authority:user:1",
            sensitivity="NORMAL",
            confidence="CONFIRMED",
            freshness=MemoryFreshness.CURRENT,
            retention="PROJECT_LIFETIME",
            integrity={"source_sha": "abc"},
            memory_id="memory:1",
        )
        values.update(changes)
        return self.memory.store(**values)

    def test_retrieval_never_promotes_memory_to_current_fact(self):
        self.put()
        item = self.memory.retrieve(scope="project:BRO", subject="repo-head")[0]
        self.assertFalse(item.usable_as_current_fact)
        self.assertIn("verification", item.reason)
        self.assertEqual(item.record.source_ref, "observation:1")
        self.assertEqual(item.record.freshness, MemoryFreshness.CURRENT)

    def test_scope_isolation(self):
        self.put()
        self.assertEqual(self.memory.retrieve(scope="project:OTHER"), ())

    def test_conflicted_memory_is_not_silently_resolved(self):
        self.put()
        other = self.memory.store(
            memory_class=MemoryClass.PROJECT, subject="repo-head", scope="project:BRO",
            content={"sha": "def"}, source_owner="PERCEPTION", source_ref="observation:2",
            authority_ref="authority:user:1", sensitivity="NORMAL", confidence="CONFIRMED",
            freshness=MemoryFreshness.CURRENT, retention="PROJECT_LIFETIME",
            integrity={"source_sha": "def"}, conflicts_with=("memory:1",), memory_id="memory:2",
        )
        self.memory.transition("memory:1", MemoryStatus.CONFLICTED, conflicts_with=(other.memory_id,))
        active = self.memory.retrieve(scope="project:BRO", subject="repo-head")
        self.assertEqual([x.record.memory_id for x in active], ["memory:2"])
        self.assertIn("conflict", active[0].reason)
        all_rows = self.memory.retrieve(scope="project:BRO", subject="repo-head", include_inactive=True)
        statuses = {x.record.memory_id: x.record.status for x in all_rows}
        self.assertEqual(statuses["memory:1"], MemoryStatus.CONFLICTED)

    def test_working_memory_cannot_be_permanent(self):
        with self.assertRaisesRegex(MemoryRejected, "expire"):
            self.put(memory_class=MemoryClass.WORKING, retention="PERMANENT")

    def test_terminal_status_is_append_only_and_cannot_reactivate(self):
        self.put()
        expired = self.memory.transition("memory:1", MemoryStatus.EXPIRED)
        self.assertEqual(expired.version, 2)
        with self.assertRaisesRegex(MemoryRejected, "terminal"):
            self.memory.transition("memory:1", MemoryStatus.ACTIVE)


if __name__ == "__main__":
    unittest.main()
