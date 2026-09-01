import unittest

from bro_runtime import ContextEntry, NervousRecordRejected, NervousRecordStore, SQLiteTaskStore


class ContextManifestIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.addCleanup(self.tasks.close)
        self.nervous = NervousRecordStore(self.tasks.connection)

    def entry(self):
        return ContextEntry(
            "intent:1", "BRO", "user request", "CURRENT", "CONFIRMED",
            "NORMAL", "current request", "BRO",
        )

    def test_manifest_id_cannot_silently_change_meaning_via_new_version(self):
        first = self.nervous.create_context_manifest(
            manifest_id="context:1", task_ref="task:1", isolation_boundary="BRO", entries=(self.entry(),)
        )
        self.assertEqual(first.version, 1)
        with self.assertRaisesRegex(NervousRecordRejected, "new manifest_id"):
            self.nervous.create_context_manifest(
                manifest_id="context:1", task_ref="task:1", isolation_boundary="BRO",
                entries=(self.entry(),), version=2,
            )
        self.assertEqual(self.nervous.context_manifest("context:1"), first)

    def test_changed_context_requires_a_new_identity(self):
        first = self.nervous.create_context_manifest(
            manifest_id="context:1", task_ref="task:1", isolation_boundary="BRO", entries=(self.entry(),)
        )
        second = self.nervous.create_context_manifest(
            manifest_id="context:2", task_ref="task:1", isolation_boundary="BRO",
            entries=(ContextEntry(
                "observation:2", "BRO", "verified evidence", "CURRENT", "CONFIRMED",
                "NORMAL", "new verified reality", "BRO",
            ),),
        )
        self.assertNotEqual(first.manifest_id, second.manifest_id)
        self.assertEqual(second.version, 1)


if __name__ == "__main__":
    unittest.main()
