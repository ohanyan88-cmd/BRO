"""Hints steer relevance. They must never steer authority."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bro_runtime.learning_memory import DurableLearningMemory, KnowledgeKind
from bro_runtime.study_runtime import (
    GovernedStudyRuntime,
    StudyContext,
    StudySourceReader,
    StudyStop,
    derive_hints,
)

CONTEXT_MODEL = """# BRO Project and Context Model
A Project is the durable boundary for related work and context.
Context is assembled per task and reassembled on material change.
"""
LOGICAL = """# BRO Logical Architecture
Evidence before DONE: completion is a governed state supported by evidence.
"""
CONTRACT = """{"contract": "unrelated.registry.v1", "note": "alphabetically first and rarely relevant"}"""
README = """# BRO
BRO is one persistent AI operating partner.
"""


def context(environment="production"):
    return StudyContext(environment=environment, source_revision="a" * 40, instance_id="dbsrv",
                        model_ref="vendor:model-a", root_ref="/study/root")


class StudyTargetingTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "repo"
        (self.root / "contracts").mkdir(parents=True)
        (self.root / "docs" / "architecture").mkdir(parents=True)
        (self.root / "contracts" / "aaa_registry.json").write_text(CONTRACT, encoding="utf-8")
        (self.root / "README.md").write_text(README, encoding="utf-8")
        (self.root / "docs" / "architecture" / "BRO_PROJECT_AND_CONTEXT_MODEL.md").write_text(CONTEXT_MODEL, encoding="utf-8")
        (self.root / "docs" / "architecture" / "BRO_LOGICAL_ARCHITECTURE.md").write_text(LOGICAL, encoding="utf-8")
        self.connection = sqlite3.connect(":memory:")
        self.memory = DurableLearningMemory(self.connection)
        self.reader = StudySourceReader(self.root)
        self.seen_sources = []

    def tearDown(self):
        self.connection.close()

    def planner(self, mission, sources):
        self.seen_sources.append(tuple(sources))
        return {}

    def extractor(self, topic, text):
        first = text.strip().splitlines()[1] if len(text.strip().splitlines()) > 1 else text.strip()
        return {"claims": [{"claim": f"about {topic}", "evidence_quote": first, "inference": False}]}

    def runtime(self, *, item_budget=2, planner=None, extractor=None):
        return GovernedStudyRuntime(
            self.memory, self.reader, planner=planner or self.planner,
            extractor=extractor or self.extractor, item_budget=item_budget, diminishing_after=5,
        )

    # -------------------------------------------------------------- derivation
    def test_hints_are_derived_from_the_mission_without_a_model(self):
        hints = derive_hints("Continue studying yourself. Focus specifically on the Introduction to BRO "
                             "and the BRO Project and Context Model.")
        self.assertIn("context", hints)
        self.assertIn("model", hints)
        self.assertIn("introduction", hints)
        for noise in ("the", "and", "studying", "focus", "specifically", "yourself"):
            self.assertNotIn(noise, hints)

    def test_non_english_missions_still_produce_hints(self):
        hints = derive_hints("վավերացման կանոնները և բացառությունները։")
        self.assertEqual(hints, ("վավերացման", "կանոնները", "բացառությունները"))

    def test_hint_derivation_is_deterministic_and_deduplicated(self):
        mission = "context model context MODEL context"
        self.assertEqual(derive_hints(mission), derive_hints(mission))
        self.assertEqual(derive_hints(mission), ("context", "model"))

    # ---------------------------------------------------------------- ordering
    def test_a_targeted_mission_reaches_the_planner_with_relevant_sources_first(self):
        self.runtime().study("Study the BRO project and context model", context())
        offered = self.seen_sources[0]
        self.assertEqual(offered[0], "docs/architecture/BRO_PROJECT_AND_CONTEXT_MODEL.md")
        self.assertIn("contracts/aaa_registry.json", offered, "nothing is hidden, only reordered")

    def test_a_targeted_mission_studies_the_relevant_source_not_the_alphabetical_one(self):
        report = self.runtime().study("Study the BRO project and context model", context())
        studied = [item.source_ref for item in self.memory.curriculum(report.mission_id)]
        self.assertIn("docs/architecture/BRO_PROJECT_AND_CONTEXT_MODEL.md", studied)
        self.assertNotIn("contracts/aaa_registry.json", studied)
        self.assertGreaterEqual(report.targeted_sources, 1)
        self.assertLessEqual(len(studied), report.targeted_sources + report.available_sources)

    def test_an_untargeted_mission_still_reads_the_alphabetical_order(self):
        report = self.runtime().study("Study", context())
        offered = self.seen_sources[0]
        self.assertEqual(offered[0], "README.md")
        self.assertEqual(report.targeted_sources, 0)

    def test_hints_that_match_nothing_fall_back_and_say_so(self):
        report = self.runtime().study("Study quantum chromodynamics", context())
        self.assertEqual(report.targeted_sources, 0)
        self.assertTrue(any("nothing here can verify it" in note for note in report.notes), report.notes)
        self.assertTrue(any("matches this mission's subject" in note for note in report.notes), report.notes)
        self.assertIsNot(report.stop_reason, StudyStop.SCOPE_EXHAUSTED)
        self.assertGreater(report.planned, 0)

    def test_explicit_hints_override_derivation(self):
        self.runtime().study("Study the project and context model", context(),
                             hints=("logical_architecture",))
        self.assertEqual(self.seen_sources[0][0], "docs/architecture/BRO_LOGICAL_ARCHITECTURE.md")

    def test_the_report_states_what_targeting_did(self):
        report = self.runtime().study("Study the BRO project and context model", context()).as_dict()
        self.assertIn("context", report["targeting"]["hints"])
        self.assertGreaterEqual(report["targeting"]["targeted_sources"], 1)
        self.assertGreaterEqual(report["targeting"]["available_sources"], 4)

    # -------------------------------------------------------------- boundaries
    def test_hints_cannot_introduce_a_path_outside_the_study_root(self):
        outside = self.root.parent / "secret.md"
        outside.write_text("# secret\nnot for study\n", encoding="utf-8")
        for escape in ("../secret", "/etc/passwd", "secret", "..", "~"):
            available, targeted = self.runtime().ordered_sources((escape,))
            for ref in available + targeted:
                self.assertFalse(ref.startswith("/") or ref.startswith(".."), ref)
                self.assertTrue((self.root / ref).resolve().is_relative_to(self.root.resolve()), ref)
            self.assertNotIn("secret.md", available)

    def test_a_hint_cannot_make_the_planner_source_set_larger_than_the_reader_allows(self):
        runtime = self.runtime()
        available, _ = runtime.ordered_sources(("bro", "contracts", "docs", "readme"))
        self.assertLessEqual(len(available), self.reader.max_sources)
        self.assertEqual(len(available), len(set(available)), "ordering must not duplicate a source")

    def test_targeted_continuation_does_not_manufacture_verified_knowledge(self):
        def unsupported(topic, text):
            return {"claims": [
                {"claim": "The context model guarantees certainty.", "evidence_quote": "", "inference": False},
                {"claim": "Probably related to projects.", "evidence_quote": "", "inference": True},
            ]}

        report = self.runtime(extractor=unsupported).study(
            "Study the BRO project and context model and resolve the uncertainty", context())
        self.assertEqual(report.verified, 0, "targeting must improve evidence, never invent it")
        self.assertGreaterEqual(report.unverified + report.inferences, 2)
        for item in self.memory.knowledge(report.mission_id):
            self.assertIsNot(item.kind, KnowledgeKind.VERIFIED_KNOWLEDGE)

    def test_targeting_still_produces_no_external_effect_and_no_authority(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = self.runtime().study("Study the BRO project and context model", context()).as_dict()
        after = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(report["external_effects"], 0)
        self.assertFalse(report["grants_authority"])
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bro_skill_candidates").fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM bro_learned_lessons").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
