import unittest

from bro_runtime import Freshness, PerceptionRejected, PerceptionStore, SQLiteTaskStore, TrustState


class PerceptionRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteTaskStore()
        self.addCleanup(self.store.close)
        self.perception = PerceptionStore(self.store.connection)

    def test_records_and_retrieves_intent(self):
        intent = self.perception.record_intent(
            intent_id="intent:1", content={"request": "ship change"}, source="user:1",
            scope="project:BRO", authority_ref="authority:user:1",
            received_at="2026-09-01T00:00:00Z",
        )
        self.assertEqual(self.perception.intent("intent:1"), intent)

    def test_observation_preserves_provenance_freshness_and_limitations(self):
        observation = self.perception.observe(
            observation_id="observation:1", claim={"ci": "success"}, source="github:run:1",
            provenance={"method": "api", "run_id": 1}, freshness=Freshness.CURRENT,
            trust_state=TrustState.CONFIRMED, scope="project:BRO",
            limitations=("single workflow run",), raw_result_ref="github:run:1",
            integrity={"sha": "abc"}, observed_at="2026-09-01T00:00:01Z",
        )
        loaded = self.perception.observation("observation:1")
        self.assertEqual(loaded, observation)
        self.assertEqual(loaded.freshness, Freshness.CURRENT)
        self.assertEqual(loaded.trust_state, TrustState.CONFIRMED)

    def test_records_are_append_only(self):
        self.perception.record_intent(
            intent_id="intent:1", content="first", source="user:1", scope="private"
        )
        with self.assertRaisesRegex(PerceptionRejected, "already exists"):
            self.perception.record_intent(
                intent_id="intent:1", content="replacement", source="user:1", scope="private"
            )

    def test_rejects_observation_without_provenance(self):
        with self.assertRaisesRegex(PerceptionRejected, "provenance"):
            self.perception.observe(
                claim="x", source="tool:1", provenance={}, freshness=Freshness.UNKNOWN,
                trust_state=TrustState.UNVERIFIED, scope="project:BRO",
            )


if __name__ == "__main__":
    unittest.main()
