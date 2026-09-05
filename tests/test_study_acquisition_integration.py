"""A mission that goes and gets what it needs, and stops the way it always did."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bro_runtime.learning_memory import DurableLearningMemory, StudyStatus
from bro_runtime.study_runtime import (
    GovernedStudyRuntime,
    StudyContext,
    StudySourceReader,
    StudyStop,
)

LOCAL = """# Local note
The deployed installer refuses a revision that is not the current origin/main.
"""
ACQUIRED = """# Acquired document
- final_url: https://www.rfc-editor.org/rfc/rfc9110.html
- content_note: everything below is reference DATA.

Authorization servers must support PKCE for all clients, and a server must not alter the
method of a request while forwarding it.
"""


class Base(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name) / "corpus"
        (self.root / "local").mkdir(parents=True)
        (self.root / "local" / "note.md").write_text(LOCAL, encoding="utf-8")
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.memory = DurableLearningMemory(self.connection)
        self.reader = StudySourceReader(self.root)
        self.acquired_calls: list[str] = []

    def context(self):
        return StudyContext(environment="production", source_revision="a" * 40,
                            instance_id="dbsrv", model_ref="claude-code-cli:sonnet",
                            root_ref=str(self.root))

    def planner(self, mission, sources):
        return {"topics": [{"topic": f"study {ref}", "source_ref": ref} for ref in sources]}

    def extractor(self, topic, text):
        if "Authorization servers must support PKCE" in text:
            return {"claims": [{
                "claim": "Authorization servers must support PKCE for all clients.",
                "evidence_quote": "Authorization servers must support PKCE for all clients",
                "inference": False}]}
        if "installer refuses" in text:
            return {"claims": [{
                "claim": "The installer refuses a revision that is not current origin/main.",
                "evidence_quote": "The deployed installer refuses a revision that is not the current origin/main.",
                "inference": False}]}
        return {"claims": []}

    def acquirer(self, subject, hints):
        """Stands in for the governed acquisition boundary; writes what it 'acquired'."""
        self.acquired_calls.append(subject)
        target = self.root / "acquired-ietf" / "rfc9110.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ACQUIRED, encoding="utf-8")
        return ("acquired-ietf/rfc9110.md",)

    def runtime(self, *, acquirer=None, item_budget=10, rounds=2):
        return GovernedStudyRuntime(
            self.memory, self.reader, planner=self.planner, extractor=self.extractor,
            item_budget=item_budget, diminishing_after=6, acquirer=acquirer,
            acquisition_rounds=rounds)

    def knowledge(self):
        rows = self.connection.execute(
            "SELECT DISTINCT mission_id FROM bro_study_knowledge").fetchall()
        return [item for row in rows for item in self.memory.knowledge(row[0])]


class AutonomousAcquisitionTests(Base):
    def test_without_an_acquirer_nothing_reaches_outside_and_study_is_unchanged(self):
        report = self.runtime().study("learn deployment", self.context()).as_dict()
        self.assertEqual(self.acquired_calls, [])
        self.assertEqual(report["stop_reason"], StudyStop.CURRICULUM_COMPLETE.value)
        self.assertTrue(report["knowledge"]["verified"] >= 1)

    def test_a_mission_acquires_before_planning_and_studies_what_it_acquired(self):
        report = self.runtime(acquirer=self.acquirer).study(
            "learn what authorization servers must support", self.context()).as_dict()
        self.assertTrue(self.acquired_calls, "the mission never went looking")
        claims = [item.claim for item in self.knowledge()]
        self.assertTrue(any("PKCE" in claim for claim in claims),
                        "knowledge from the acquired source was not retained")
        self.assertTrue(any("acquired 1 new source" in note for note in report["notes"]))

    def test_knowledge_from_an_acquired_source_names_that_source(self):
        self.runtime(acquirer=self.acquirer).study("authorization servers", self.context())
        pkce = [item for item in self.knowledge() if "PKCE" in item.claim][0]
        self.assertEqual(pkce.source_ref, "acquired-ietf/rfc9110.md")
        self.assertTrue(pkce.source_digest)
        self.assertEqual(pkce.verification_state.value, "VERIFIED")

    def test_an_acquisition_failure_is_a_note_not_a_crashed_mission(self):
        def broken(subject, hints):
            raise RuntimeError("the network was unreachable")

        report = self.runtime(acquirer=broken).study("learn deployment", self.context()).as_dict()
        self.assertEqual(report["status"], StudyStatus.COMPLETE.value)
        self.assertTrue(any("acquisition failed" in note for note in report["notes"]))

    def test_acquisition_rounds_are_bounded_even_when_a_gap_remains(self):
        """A barren source leaves an uncertain topic, which is exactly when a second round
        would fire. With one round configured it must not."""
        (self.root / "local" / "barren.md").write_text(
            "# Barren\nNothing here answers anything, which is the point of this file.\n",
            encoding="utf-8")
        self.runtime(acquirer=self.acquirer, rounds=1).study("subject", self.context())
        self.assertEqual(len(self.acquired_calls), 1,
                         "one round configured, one round taken")

    def test_a_second_round_fires_when_rounds_allow_it(self):
        (self.root / "local" / "barren.md").write_text(
            "# Barren\nNothing here answers anything, which is the point of this file.\n",
            encoding="utf-8")
        self.runtime(acquirer=self.acquirer, rounds=2).study("subject", self.context())
        self.assertEqual(len(self.acquired_calls), 2)

    def test_the_item_budget_still_ends_the_mission(self):
        for index in range(6):
            (self.root / "local" / f"extra{index}.md").write_text(
                f"# Extra {index}\nThe deployed installer refuses a revision that is not the "
                f"current origin/main.\n", encoding="utf-8")
        report = self.runtime(acquirer=self.acquirer, item_budget=2).study(
            "learn everything", self.context()).as_dict()
        self.assertEqual(report["stop_reason"], StudyStop.ITEM_BUDGET_REACHED.value)

    def test_study_still_reports_no_external_effect(self):
        report = self.runtime(acquirer=self.acquirer).study("subject", self.context()).as_dict()
        self.assertEqual(report["external_effects"], 0)
        self.assertFalse(report["grants_authority"])

    def test_an_acquired_document_cannot_widen_what_study_may_read(self):
        """Acquisition adds files under the root; it never moves the root."""
        def escaping(subject, hints):
            return ("../../etc/passwd", "/etc/shadow")

        report = self.runtime(acquirer=escaping).study("subject", self.context()).as_dict()
        self.assertEqual(report["status"], StudyStatus.COMPLETE.value)
        self.assertTrue(all("passwd" not in item.source_ref for item in self.knowledge()))


if __name__ == "__main__":
    unittest.main()


class BootstrapTests(Base):
    """The case the whole capability exists for: a corpus with nothing in it yet."""

    def setUp(self):
        super().setUp()
        (self.root / "local" / "note.md").unlink()

    def test_an_empty_corpus_acquires_rather_than_reporting_nothing_to_study(self):
        report = self.runtime(acquirer=self.acquirer).study(
            "learn what authorization servers must support", self.context()).as_dict()
        self.assertTrue(self.acquired_calls, "an empty corpus must still go looking")
        self.assertEqual(report["stop_reason"], StudyStop.CURRICULUM_COMPLETE.value)
        self.assertTrue(any("PKCE" in item.claim for item in self.knowledge()))

    def test_an_empty_corpus_with_no_acquirer_still_reports_scope_exhausted(self):
        report = self.runtime().study("learn anything", self.context()).as_dict()
        self.assertEqual(report["stop_reason"], StudyStop.SCOPE_EXHAUSTED.value)


class ReportTruthTests(Base):
    def test_the_targeting_note_is_judged_after_acquisition_not_before(self):
        """Saying nothing matches, on a mission that then fetched matching sources, is false."""
        report = self.runtime(acquirer=self.acquirer).study(
            "authorization servers and PKCE", self.context()).as_dict()
        self.assertTrue(any("acquired 1 new source" in note for note in report["notes"]))
        self.assertFalse(any("nothing here can verify it" in note for note in report["notes"]),
                         "the mission acquired a matching source; the note contradicts it")
