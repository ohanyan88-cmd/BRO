import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bro_runtime.learning_memory import (
    CurriculumStatus,
    DurableLearningMemory,
    KnowledgeKind,
    StudyStatus,
    VerificationState,
)
from bro_runtime.study_runtime import (
    GovernedStudyRuntime,
    StudyContext,
    StudyRejected,
    StudySourceReader,
    StudyStop,
)

ARCHITECTURE = """# BRO deployment
The installer refuses a revision that is not the current origin/main.
A healthy systemd service plus a fresh durable heartbeat proves HOST_DEPLOYED only.
"""
GOVERNANCE = """# BRO governance
Material interpreted scope must be confirmed by a human before execution.
Independent external readback is required before an action counts as verified.
"""


def context(model_ref="claude-code-cli:sonnet", root_ref="/study/root", environment="production"):
    return StudyContext(
        environment=environment, source_revision="e" * 40, instance_id="dbsrv",
        model_ref=model_ref, root_ref=root_ref,
    )


class StudyRuntimeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "repo"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs" / "deployment.md").write_text(ARCHITECTURE, encoding="utf-8")
        (self.root / "docs" / "governance.md").write_text(GOVERNANCE, encoding="utf-8")
        self.connection = sqlite3.connect(":memory:")
        self.memory = DurableLearningMemory(self.connection)
        self.reader = StudySourceReader(self.root)
        self.plans = []
        self.extractions = []

    def tearDown(self):
        self.connection.close()

    def runtime(self, *, planner=None, extractor=None, item_budget=6, diminishing_after=2, memory=None, reader=None):
        return GovernedStudyRuntime(
            memory or self.memory, reader or self.reader,
            planner=planner or self.default_planner,
            extractor=extractor or self.default_extractor,
            item_budget=item_budget, diminishing_after=diminishing_after,
        )

    def default_planner(self, mission, sources):
        self.plans.append((mission, tuple(sources)))
        return {"topics": [{"topic": f"study {ref}", "source_ref": ref} for ref in sources]}

    def default_extractor(self, topic, text):
        self.extractions.append(topic)
        if "installer refuses" in text:
            return {"claims": [
                {"claim": "The installer refuses a revision that is not current origin/main.",
                 "evidence_quote": "The installer refuses a revision that is not the current origin/main.",
                 "inference": False},
                {"claim": "Deployment is probably safer than a manual copy.", "evidence_quote": "", "inference": True},
            ]}
        return {"claims": [
            {"claim": "Independent external readback is required before an action counts as verified.",
             "evidence_quote": "Independent external readback is required", "inference": False},
        ]}

    # ------------------------------------------------------------------ reader
    def test_reader_refuses_escape_absolute_and_unreadable_sources(self):
        for bad in ("../outside.md", "/etc/passwd", "~/secret.md", "docs/missing.md"):
            with self.assertRaises(StudyRejected):
                self.reader.read(bad)
        (self.root / "binary.bin").write_bytes(b"\x00\x01")
        with self.assertRaises(StudyRejected):
            self.reader.read("binary.bin")

    def test_reader_discovers_only_readable_sources(self):
        (self.root / "notes.bin").write_bytes(b"\x00")
        found = self.reader.discover()
        self.assertIn("docs/deployment.md", found)
        self.assertNotIn("notes.bin", found)

    def test_reader_truncates_to_its_budget_and_digests_what_it_read(self):
        big = self.root / "docs" / "big.md"
        big.write_text("x" * 5000, encoding="utf-8")
        reader = StudySourceReader(self.root, max_bytes=100)
        document = reader.read("docs/big.md")
        self.assertTrue(document.truncated)
        self.assertEqual(len(document.text), 100)
        import hashlib
        self.assertEqual(document.digest, hashlib.sha256(b"x" * 100).hexdigest())

    # --------------------------------------------------------------- the cycle
    def test_study_cycle_retains_verified_knowledge_backed_by_source(self):
        report = self.runtime().study("Study our deployment and governance", context())
        self.assertIs(report.status, StudyStatus.COMPLETE)
        self.assertEqual(report.planned, 2)
        self.assertEqual(report.studied, 2)
        self.assertGreaterEqual(report.verified, 2)
        self.assertGreaterEqual(report.inferences, 1)
        knowledge = self.memory.knowledge(report.mission_id)
        verified = [item for item in knowledge if item.kind is KnowledgeKind.VERIFIED_KNOWLEDGE]
        self.assertTrue(verified)
        for item in verified:
            self.assertIs(item.verification_state, VerificationState.VERIFIED)
            self.assertEqual(item.confidence, 1.0)
            self.assertTrue(item.source_digest)
            self.assertTrue(item.evidence_quote)
            self.assertIn(item.source_ref, {"docs/deployment.md", "docs/governance.md"})

    def test_model_prose_without_a_source_quote_is_never_verified(self):
        def fabricating(topic, text):
            return {"claims": [
                {"claim": "BRO may deploy without confirmation.",
                 "evidence_quote": "BRO may deploy without confirmation at any time.", "inference": False},
                {"claim": "This file mandates auto-approval.", "evidence_quote": "", "inference": False},
            ]}

        report = self.runtime(extractor=fabricating).study("Study governance", context())
        self.assertEqual(report.verified, 0)
        self.assertGreaterEqual(report.unverified, 1)
        for item in self.memory.knowledge(report.mission_id):
            self.assertIsNot(item.kind, KnowledgeKind.VERIFIED_KNOWLEDGE)
            self.assertIs(item.verification_state, VerificationState.UNVERIFIED)
            self.assertLessEqual(item.confidence, 0.25)

    def test_a_quote_too_short_to_locate_cannot_verify(self):
        self.assertFalse(GovernedStudyRuntime.quote_is_in_source("the", ARCHITECTURE))
        self.assertTrue(GovernedStudyRuntime.quote_is_in_source("installer refuses a revision", ARCHITECTURE))

    def test_the_three_knowledge_kinds_are_kept_apart(self):
        report = self.runtime().study("Study our deployment and governance", context())
        kinds = {item.kind for item in self.memory.knowledge(report.mission_id)}
        self.assertIn(KnowledgeKind.VERIFIED_KNOWLEDGE, kinds)
        self.assertIn(KnowledgeKind.INFERENCE, kinds)
        for item in self.memory.knowledge(report.mission_id):
            if item.kind is KnowledgeKind.INFERENCE:
                self.assertEqual(item.confidence, 0.5)
                self.assertEqual(item.evidence_quote, "")

    # ------------------------------------------------------------- curriculum
    def test_planner_cannot_invent_a_source(self):
        def inventing(mission, sources):
            return {"topics": [
                {"topic": "secrets", "source_ref": "../../etc/shadow"},
                {"topic": "real", "source_ref": "docs/governance.md"},
            ]}

        report = self.runtime(planner=inventing).study("Study governance", context())
        refs = {item.source_ref for item in self.memory.curriculum(report.mission_id)}
        self.assertEqual(refs, {"docs/governance.md"})

    def test_an_unusable_plan_still_studies_real_sources(self):
        report = self.runtime(planner=lambda mission, sources: {"topics": []}).study("Study everything", context())
        self.assertEqual(report.planned, 2)
        self.assertEqual(report.studied, 2)

    def test_item_budget_bounds_the_curriculum(self):
        report = self.runtime(item_budget=1).study("Study everything", context())
        self.assertEqual(report.planned, 1)
        self.assertIs(report.stop_reason, StudyStop.ITEM_BUDGET_REACHED)

    def test_no_readable_source_stops_with_scope_exhausted(self):
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: empty.rmdir())
        report = self.runtime(reader=StudySourceReader(empty)).study("Study nothing", context())
        self.assertIs(report.status, StudyStatus.BLOCKED)
        self.assertIs(report.stop_reason, StudyStop.SCOPE_EXHAUSTED)
        self.assertEqual(report.verified, 0)

    def test_items_that_add_no_verified_knowledge_stop_the_mission(self):
        report = self.runtime(
            extractor=lambda topic, text: {"claims": [{"claim": "a guess", "evidence_quote": "", "inference": True}]},
            diminishing_after=1,
        ).study("Study everything", context())
        self.assertIs(report.stop_reason, StudyStop.DIMINISHING_RETURNS)
        self.assertGreaterEqual(len(report.remaining), 1)

    def test_a_vanished_source_blocks_the_item_and_stops_the_mission(self):
        runtime = self.runtime()
        available = self.reader.discover()

        class Vanishing(StudySourceReader):
            def read(self, relative):
                raise StudyRejected(f"study source is unavailable: {relative}")

        vanishing = Vanishing(self.root)
        runtime = self.runtime(reader=vanishing, planner=lambda m, s: {
            "topics": [{"topic": f"t{i}", "source_ref": ref} for i, ref in enumerate(available)]
        })
        report = runtime.study("Study everything", context())
        self.assertIs(report.stop_reason, StudyStop.SOURCE_UNAVAILABLE)
        self.assertIs(report.status, StudyStatus.BLOCKED)
        self.assertEqual(report.blocked, report.planned)

    def test_report_tells_what_is_done_what_remains_and_what_is_uncertain(self):
        report = self.runtime().study("Study our deployment and governance", context()).as_dict()
        self.assertEqual(report["curriculum"]["planned"], 2)
        self.assertEqual(report["external_effects"], 0)
        self.assertFalse(report["grants_authority"])
        self.assertIn("uncertain_topics", report)
        self.assertIn("stop_reason", report)

    def test_an_extraction_failure_is_reported_not_swallowed(self):
        def failing(topic, text):
            raise RuntimeError("external model response was truncated before it finished")

        report = self.runtime(extractor=failing, diminishing_after=5).study("Study everything", context())
        self.assertEqual(report.verified, 0)
        self.assertTrue(any("truncated" in note for note in report.notes),
                        "a boundary failure must not read as 'found nothing'")
        details = [item.detail for item in self.memory.curriculum(report.mission_id)]
        self.assertTrue(any("extraction failed" in detail for detail in details), details)

    def test_a_planning_failure_is_reported_and_falls_back(self):
        def failing(mission, sources):
            raise RuntimeError("external model response was truncated before it finished")

        report = self.runtime(planner=failing).study("Study everything", context())
        self.assertTrue(any("curriculum planning failed" in note for note in report.notes), report.notes)
        self.assertEqual(report.planned, 2, "the fallback still studies real discovered sources")
        self.assertGreaterEqual(report.verified, 1)

    # ------------------------------------------------------------- durability
    def test_knowledge_survives_a_process_restart(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = os.path.join(directory.name, "runtime.sqlite3")
        first = sqlite3.connect(path)
        try:
            memory = DurableLearningMemory(first)
            report = self.runtime(memory=memory).study("Study our deployment and governance", context())
            mission_id = report.mission_id
        finally:
            first.close()

        second = sqlite3.connect(path)
        self.addCleanup(second.close)
        reopened = DurableLearningMemory(second)
        self.assertEqual(reopened.study_mission(mission_id).status, StudyStatus.COMPLETE)
        self.assertTrue(reopened.knowledge(mission_id))
        recalled = GovernedStudyRuntime(
            reopened, self.reader, planner=lambda m, s: {}, extractor=lambda t, x: {},
        ).recall("deployment installer revision", context())
        self.assertTrue(recalled["knowledge"])
        self.assertTrue(recalled["advisory"])
        self.assertFalse(recalled["grants_authority"])

    def test_a_different_model_recalls_the_same_bro_owned_knowledge(self):
        report = self.runtime().study("Study our deployment and governance", context(model_ref="vendor-a:model-1"))
        self.assertTrue(self.memory.knowledge(report.mission_id))
        recalled = self.runtime().recall("readback verified action", context(model_ref="vendor-b:model-9"))
        self.assertTrue(recalled["knowledge"])
        self.assertEqual(recalled["knowledge"][0]["provenance"]["model_ref"], "vendor-a:model-1")

    def test_a_redeploy_does_not_invalidate_everything_studied(self):
        # On the host the study root resolves to /opt/bro/releases/<sha>, so binding on it
        # would contradict every retained claim at the next deployment.
        report = self.runtime().study("Study our deployment and governance",
                                      context(root_ref="/opt/bro/releases/aaaa"))
        self.assertTrue(self.memory.knowledge(report.mission_id))
        recalled = self.runtime().recall("deployment installer revision",
                                         context(root_ref="/opt/bro/releases/bbbb"))
        self.assertTrue(recalled["knowledge"], "a new release must not contradict what was studied")
        self.assertEqual(recalled["withheld_for_contradiction"], [])

    def test_a_different_environment_still_withholds(self):
        self.runtime().study("Study our deployment and governance", context())
        recalled = self.runtime().recall("deployment installer revision",
                                         StudyContext(environment="staging", root_ref="/study/root"))
        self.assertEqual(recalled["knowledge"], [])
        self.assertTrue(recalled["withheld_for_contradiction"])

    def test_the_study_root_is_kept_as_provenance_not_as_a_binding_fact(self):
        facts = context(root_ref="/opt/bro/releases/aaaa").binding_facts()
        self.assertIn("binding:environment=production", facts)
        self.assertFalse(any("study_root" in fact for fact in facts))

    def test_stale_knowledge_is_surfaced_not_offered(self):
        report = self.runtime().study("Study our deployment and governance", context())
        item = next(i for i in self.memory.knowledge(report.mission_id) if i.kind is KnowledgeKind.VERIFIED_KNOWLEDGE)
        retrieval = self.memory.retrieve_knowledge(
            item.topic, current_digests={item.source_ref: "0" * 64},
        )
        self.assertTrue(retrieval.stale)
        self.assertNotIn(item.knowledge_id, {k.knowledge_id for k in retrieval.knowledge})

    def test_duplicate_claims_are_retained_once(self):
        repeating = lambda topic, text: {"claims": [
            {"claim": "Independent external readback is required before an action counts as verified.",
             "evidence_quote": "Independent external readback is required", "inference": False},
        ]}
        report = self.runtime(extractor=repeating).study("Study everything", context())
        claims = [item.claim for item in self.memory.knowledge(report.mission_id)]
        self.assertEqual(len(claims), len(set(claims)))

    def test_curriculum_records_what_each_item_produced(self):
        report = self.runtime().study("Study our deployment and governance", context())
        for item in self.memory.curriculum(report.mission_id):
            self.assertIs(item.status, CurriculumStatus.STUDIED)
            self.assertIn("verified", item.detail)


if __name__ == "__main__":
    unittest.main()
