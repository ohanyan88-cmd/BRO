"""A mission's plan is bounded; the programme is not, and the runtime now knows the difference.

The defect these tests exist for: the planner saw the mission text and a list of file paths,
and nothing else. It could not know what BRO already knew, so continuation missions re-read
familiar documents and reported CURRICULUM_COMPLETE while most of the programme was
untouched. Telling the model not to repeat itself does not fix that -- the runtime has to
withhold the material, which is what is tested here.
"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bro_runtime.curriculum import (
    CurriculumRejected,
    DomainState,
    RevisitReason,
)
from bro_runtime.curriculum_manifest import CurriculumManifest, normalise_url
from bro_runtime.learning_memory import (
    DurableLearningMemory,
    KnowledgeKind,
    Provenance,
    SourceType,
)
from bro_runtime.study_runtime import (
    GovernedStudyRuntime,
    StudyContext,
    StudySourceReader,
    StudyStop,
)

ISOLATION_URL = "https://www.sqlite.org/isolation.html"
CONSENSUS_URL = "https://pdos.csail.mit.edu/6.824/papers/raft-extended.pdf"
RUST_URL = "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html"

CURRICULUM = {
    "manifest": "test.v1",
    "evidence_rule": {"default_min_verified_rows": 2, "default_min_sources": 1},
    "domains": [
        {"domain": "transactions", "title": "Transactions", "depends_on": [], "requirements": [
            {"requirement": "tx.isolation", "competency": "Isolation levels",
             "basis": "publisher-structure", "min_verified_rows": 2, "min_sources": 1,
             "sources": [{"url": ISOLATION_URL, "family": "sqlite",
                          "publisher": "SQLite project", "authority_tier": "A"}]}]},
        {"domain": "rust", "title": "Rust engineering", "depends_on": [], "requirements": [
            {"requirement": "rs.ownership", "competency": "Ownership and borrowing",
             "basis": "publisher-structure", "min_verified_rows": 2, "min_sources": 1,
             "sources": [{"url": RUST_URL, "family": "rust", "publisher": "Rust project",
                          "authority_tier": "A"}]}]},
        {"domain": "distributed", "title": "Distributed systems",
         "depends_on": ["transactions"], "requirements": [
            {"requirement": "dist.consensus", "competency": "Replication and consensus",
             "basis": "publisher-structure", "min_verified_rows": 2, "min_sources": 1,
             "sources": [{"url": CONSENSUS_URL, "family": "mit",
                          "publisher": "Massachusetts Institute of Technology",
                          "authority_tier": "B"}]}]},
    ],
}

# The corpus documents these tests seed are the local form of those declared documents.
CORPUS_INDEX = {
    normalise_url(ISOLATION_URL): {"isolation.md"},
    normalise_url(CONSENSUS_URL): {"consensus.md"},
    normalise_url(RUST_URL): {"ownership.md"},
}


class IndexedManifest(CurriculumManifest):
    """The manifest with the test corpus's url-to-path join wired in.

    Production reads that join from the knowledge registry, which these tests do not populate
    because what they are about is the runtime's behaviour, not the registry's schema. The
    registry path has its own test in test_curriculum_manifest.py.
    """

    def coverage(self, memory, *, index=None, current_digests=None):
        return super().coverage(memory, index=index or CORPUS_INDEX,
                                current_digests=current_digests)

    def planning_context(self, memory, *, index=None, current_digests=None,
                         revisit_allowed=None):
        return super().planning_context(memory, index=index or CORPUS_INDEX,
                                        current_digests=current_digests,
                                        revisit_allowed=revisit_allowed)

ISOLATION = """# Isolation
A transaction running at the serializable isolation level behaves as if it ran alone.
"""
CONSENSUS = """# Consensus
A quorum is the smallest set of nodes that must agree before a consensus decision holds.
"""


class Base(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)
        self.root = self.home / "corpus"
        self.root.mkdir()
        (self.root / "isolation.md").write_text(ISOLATION, encoding="utf-8")
        (self.root / "consensus.md").write_text(CONSENSUS, encoding="utf-8")
        self.db = self.home / "runtime.sqlite3"
        self.connection = sqlite3.connect(self.db)
        self.addCleanup(self.connection.close)
        self.memory = DurableLearningMemory(self.connection)
        self.reader = StudySourceReader(self.root)
        self.curriculum = IndexedManifest(CURRICULUM)
        self.planned_with: list[dict] = []

    def context(self):
        return StudyContext(environment="production", source_revision="a" * 40,
                            instance_id="dbsrv", model_ref="claude-code-cli:sonnet",
                            root_ref=str(self.root))

    def planner(self, mission, sources, coverage=None):
        self.planned_with.append({"sources": list(sources), "coverage": coverage})
        return {"topics": [{"topic": f"study {ref}", "source_ref": ref} for ref in sources]}

    def extractor(self, topic, text):
        if "serializable isolation level" in text:
            return {"claims": [{
                "claim": "A transaction at the serializable isolation level behaves as if alone.",
                "evidence_quote": "A transaction running at the serializable isolation level behaves as if it ran alone.",
                "inference": False}]}
        if "quorum" in text:
            return {"claims": [{
                "claim": "A quorum is the smallest set of nodes that must agree for consensus.",
                "evidence_quote": "A quorum is the smallest set of nodes that must agree before a consensus decision holds.",
                "inference": False}]}
        return {"claims": []}

    def runtime(self, *, curriculum=None, refresh=False, acquirer=None):
        return GovernedStudyRuntime(
            self.memory, self.reader, planner=self.planner, extractor=self.extractor,
            item_budget=10, diminishing_after=6, curriculum=curriculum, refresh=refresh,
            acquirer=acquirer)

    def seed(self, source_ref: str, keyword_claim: str, rows: int, digest: str = ""):
        """Put verified knowledge in the store the way a real mission would have.

        The digest must be the file's real one, or every seeded source looks stale and the
        staleness rule quietly permits every revisit -- which is a fixture that proves the
        opposite of what it claims.
        """
        if not digest:
            try:
                digest = self.reader.read(source_ref).digest
            except Exception:
                digest = "d" * 64
        mission = self.memory.open_study_mission(mission=f"seed {source_ref}", scope=(),
                                                 item_budget=10)
        item = self.memory.add_curriculum_item(mission.mission_id, topic=keyword_claim,
                                               source_ref=source_ref, sequence=0)
        for index in range(rows):
            self.memory.record_knowledge(
                mission_id=mission.mission_id, item_id=item.item_id, topic=keyword_claim,
                claim=f"{keyword_claim} fact {index}", kind=KnowledgeKind.VERIFIED_KNOWLEDGE,
                source_ref=source_ref, source_type=SourceType.REPOSITORY_FILE,
                source_digest=digest, evidence_quote=f"{keyword_claim} evidence {index}",
                provenance=Provenance(source_revision="a" * 40))
        return mission.mission_id


class CoverageTests(Base):
    def test_a_domain_with_no_evidence_is_unstudied(self):
        coverage = {item.domain: item for item in self.curriculum.coverage(self.memory)}
        self.assertIs(coverage["rust"].state, DomainState.UNSTUDIED)

    def test_evidence_below_the_threshold_leaves_a_domain_partial(self):
        """Coverage is evidence-based: rows existing is not the same as a domain being learned."""
        self.seed("isolation.md", "transaction isolation level", rows=1)
        coverage = {item.domain: item for item in self.curriculum.coverage(self.memory)}
        self.assertIs(coverage["transactions"].state, DomainState.PARTIAL)

    def test_enough_evidence_from_a_studied_source_covers_a_domain(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        coverage = {item.domain: item for item in self.curriculum.coverage(self.memory)}
        self.assertIs(coverage["transactions"].state, DomainState.COVERED)

    def test_a_source_the_curriculum_never_declared_is_not_evidence(self):
        """What replaced the keyword rule. Ordinary technical English appears in every
        document, and matching on it covered 27 of 32 domains from BRO's own notes; the
        answer is not a better word list but not reading the words at all."""
        self.seed("consensus.md", "transaction isolation level serializable", rows=9)
        coverage = {item.domain: item for item in self.curriculum.coverage(self.memory)}
        self.assertIs(coverage["transactions"].state, DomainState.UNSTUDIED)

    def test_a_stale_source_stops_counting_toward_coverage(self):
        self.seed("isolation.md", "transaction isolation level serializable", 5,
                  "old" + "0" * 61)
        fresh = self.curriculum.coverage(self.memory,
                                         current_digests={"isolation.md": "new" + "0" * 61})
        self.assertIs({item.domain: item for item in fresh}["transactions"].state,
                      DomainState.UNSTUDIED)

    def test_dependencies_are_reported_as_unmet(self):
        coverage = {item.domain: item for item in self.curriculum.coverage(self.memory)}
        self.assertEqual(coverage["distributed"].unmet_dependencies, ("transactions",))

    def test_a_curriculum_with_a_dangling_dependency_is_refused(self):
        broken = dict(CURRICULUM)
        broken["domains"] = [dict(CURRICULUM["domains"][0], depends_on=["nowhere"])]
        with self.assertRaises(CurriculumRejected):
            CurriculumManifest(broken)


class PlanningContextTests(Base):
    def test_the_planner_is_given_prior_coverage(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime(curriculum=self.curriculum).study("learn", self.context())
        coverage = self.planned_with[-1]["coverage"]
        self.assertTrue(coverage, "the planner was handed no durable state")
        self.assertIn("next_uncovered_domains", coverage)
        self.assertIn("rust", [item["domain"] for item in coverage["next_uncovered_domains"]])
        self.assertIn("transactions", [item["domain"] for item in coverage["covered_domains"]])

    def test_the_planning_view_is_bounded(self):
        """The point is to name the empty territory, not to hand over the knowledge base."""
        for index in range(60):
            self.seed(f"source{index}.md", "transaction isolation level serializable", rows=3)
        context = self.curriculum.planning_context(self.memory)
        rendered = json.dumps(context.as_dict())
        self.assertLess(len(rendered), 8000, "the planning context must stay small")
        self.assertLessEqual(len(context.as_dict()["next_uncovered_domains"]), 10)

    def test_a_sufficiently_studied_source_is_withheld_from_planning(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime(curriculum=self.curriculum).study("learn", self.context())
        offered = self.planned_with[-1]["sources"]
        self.assertNotIn("isolation.md", offered, "covered material was offered again")
        self.assertIn("consensus.md", offered)

    def test_without_a_curriculum_nothing_is_withheld(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime().study("learn", self.context())
        self.assertIn("isolation.md", self.planned_with[-1]["sources"])

    def test_a_partially_covered_domain_is_still_offered(self):
        self.seed("isolation.md", "transaction isolation", rows=1)
        self.runtime(curriculum=self.curriculum).study("learn", self.context())
        self.assertIn("isolation.md", self.planned_with[-1]["sources"])

    def test_an_exhausted_corpus_stops_the_mission_rather_than_being_read_again(self):
        """This asserted the opposite until the curriculum manifest landed.

        Handing every already-studied source back kept missions running and kept them
        producing reports, and what they were doing was reading the same shelf again. A
        corpus with nothing new in it is a fact about the corpus; the answer is the declared
        canonical document, not a second pass.
        """
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.seed("consensus.md", "consensus quorum network partition", rows=5)
        report = self.runtime(curriculum=self.curriculum).study("learn", self.context()).as_dict()
        self.assertEqual(report["stop_reason"], StudyStop.SCOPE_EXHAUSTED.value)
        self.assertEqual(report["curriculum"]["studied"], 0)


class RevisitTests(Base):
    def test_a_stale_source_may_be_revisited_and_the_reason_is_recorded(self):
        self.seed("isolation.md", "transaction isolation level serializable", 5,
                  "stale" + "0" * 59)
        report = self.runtime(curriculum=self.curriculum).study("learn", self.context()).as_dict()
        self.assertIn("isolation.md", self.planned_with[-1]["sources"])
        reasons = {row["source_ref"]: row["reason"] for row in self.memory.revisits()}
        self.assertEqual(reasons.get("isolation.md"), RevisitReason.STALE_SOURCE.value)
        self.assertTrue(any("STALE_SOURCE" in note for note in report["notes"]))

    def test_an_explicit_refresh_may_revisit_covered_material(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime(curriculum=self.curriculum, refresh=True).study("learn", self.context())
        self.assertIn("isolation.md", self.planned_with[-1]["sources"])
        reasons = {row["source_ref"]: row["reason"] for row in self.memory.revisits()}
        self.assertEqual(reasons.get("isolation.md"), RevisitReason.EXPLICIT_REFRESH.value)

    def test_a_contradiction_may_revisit_covered_material(self):
        from bro_runtime.learning_memory import Contradiction
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.memory.record_contradictions([
            Contradiction("isolation.md", "environment", "staging", "production", "drift")])
        self.runtime(curriculum=self.curriculum).study("learn", self.context())
        self.assertIn("isolation.md", self.planned_with[-1]["sources"])
        reasons = {row["source_ref"]: row["reason"] for row in self.memory.revisits()}
        self.assertEqual(reasons.get("isolation.md"), RevisitReason.CONTRADICTION.value)

    def test_revisits_survive_a_restart(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime(curriculum=self.curriculum, refresh=True).study("learn", self.context())
        self.connection.close()
        reopened = sqlite3.connect(self.db)
        self.addCleanup(reopened.close)
        rows = DurableLearningMemory(reopened).revisits()
        self.assertTrue(rows)
        self.assertEqual(rows[0]["reason"], RevisitReason.EXPLICIT_REFRESH.value)


class MasterCurriculumStateTests(Base):
    def test_a_local_curriculum_complete_does_not_mean_the_programme_is_done(self):
        """The confusion this whole change exists to remove."""
        report = self.runtime(curriculum=self.curriculum).study("learn", self.context()).as_dict()
        self.assertEqual(report["stop_reason"], StudyStop.CURRICULUM_COMPLETE.value)
        self.assertFalse(report["master_curriculum"]["complete"])
        self.assertTrue(report["master_curriculum"]["remaining"])

    def test_the_next_mission_moves_into_uncovered_territory(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime(curriculum=self.curriculum).study("continue", self.context())
        studied = [topic for topic, _ in
                   [(item.topic, item.source_ref)
                    for item in self.memory.curriculum(
                        self.memory.connection.execute(
                            "SELECT mission_id FROM bro_study_missions ORDER BY rowid DESC LIMIT 1"
                        ).fetchone()[0])]]
        self.assertTrue(any("consensus" in topic for topic in studied),
                        "the mission did not move into new territory")
        self.assertFalse(any("isolation" in topic for topic in studied))

    def test_coverage_survives_a_restart(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        before = {item.domain: item.state for item in self.curriculum.coverage(self.memory)}
        self.connection.close()
        reopened = sqlite3.connect(self.db)
        self.addCleanup(reopened.close)
        after = {item.domain: item.state
                 for item in self.curriculum.coverage(DurableLearningMemory(reopened))}
        self.assertEqual(before, after)
        self.assertIs(after["transactions"], DomainState.COVERED)

    def test_the_report_names_covered_partial_and_remaining_separately(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        report = self.runtime(curriculum=self.curriculum).study("learn", self.context()).as_dict()
        master = report["master_curriculum"]
        self.assertIn("transactions", master["covered"])
        self.assertIn("rust", master["remaining"])
        self.assertNotIn("rust", master["covered"])


class AcquisitionOutcomeTests(Base):
    def test_every_candidate_outcome_is_durably_recorded(self):
        recorded: list[tuple] = []

        def acquirer(subject, hints, record):
            record("https://www.rfc-editor.org/rfc/rfc9110.txt", "www.rfc-editor.org",
                   "ALREADY_PRESENT_UNCHANGED", "digest matched")
            record("https://random.example/x", "random.example", "REJECTED_BY_POLICY",
                   "no family claims random.example")
            recorded.append((subject, hints))
            return ()

        self.runtime(curriculum=self.curriculum, acquirer=acquirer).study("learn", self.context())
        outcomes = {row["outcome"] for row in self.memory.acquisition_outcomes()}
        self.assertEqual(outcomes, {"ALREADY_PRESENT_UNCHANGED", "REJECTED_BY_POLICY"})

    def test_a_zero_new_source_mission_can_be_explained_from_the_record(self):
        """The ambiguity found in acceptance: nothing acquired, and no way to say why."""
        def acquirer(subject, hints, record):
            record("", "", "NOT_PROPOSED", "the model proposed no classifiable source")
            return ()

        self.runtime(curriculum=self.curriculum, acquirer=acquirer).study("learn", self.context())
        rows = self.memory.acquisition_outcomes()
        self.assertEqual([row["outcome"] for row in rows], ["NOT_PROPOSED"])
        self.assertIn("proposed no classifiable source", rows[0]["detail"])

    def test_outcomes_survive_a_restart(self):
        def acquirer(subject, hints, record):
            record("https://x.test/a", "x.test", "ACQUIRED_NEW", "admitted")
            return ()

        self.runtime(curriculum=self.curriculum, acquirer=acquirer).study("learn", self.context())
        self.connection.close()
        reopened = sqlite3.connect(self.db)
        self.addCleanup(reopened.close)
        rows = DurableLearningMemory(reopened).acquisition_outcomes()
        self.assertEqual(rows[0]["outcome"], "ACQUIRED_NEW")

    def test_an_acquirer_without_a_recorder_still_works(self):
        def acquirer(subject, hints):
            return ()

        report = self.runtime(curriculum=self.curriculum, acquirer=acquirer).study(
            "learn", self.context()).as_dict()
        self.assertEqual(report["status"], "COMPLETE")


class BoundaryTests(Base):
    def test_provenance_and_verification_states_are_untouched(self):
        self.seed("isolation.md", "transaction isolation level serializable", rows=5)
        self.runtime(curriculum=self.curriculum).study("learn", self.context())
        rows = self.connection.execute(
            "SELECT verification_state, source_digest, provenance_json FROM bro_study_knowledge"
        ).fetchall()
        self.assertTrue(rows)
        for state, digest, provenance in rows:
            self.assertIn(state, ("VERIFIED", "UNVERIFIED"))
            self.assertTrue(digest)
            self.assertIn("source_revision", provenance)

    def test_authority_is_unchanged(self):
        report = self.runtime(curriculum=self.curriculum).study("learn", self.context()).as_dict()
        self.assertEqual(report["external_effects"], 0)
        self.assertFalse(report["grants_authority"])

    def test_the_curriculum_creates_no_second_store(self):
        """Coverage is derived from the one memory, never maintained beside it."""
        source = (Path(__file__).resolve().parents[1]
                  / "src/bro_runtime/curriculum.py").read_text(encoding="utf-8")
        for writer in ("INSERT INTO", "UPDATE ", "DELETE ", "CREATE TABLE", "commit()"):
            self.assertNotIn(writer, source)


if __name__ == "__main__":
    unittest.main()


class GapRoundExclusionTests(Base):
    """Acquiring a url is not the same as needing to study it."""

    def acquirer_returning(self, *paths):
        def acquirer(subject, hints, record=None):
            return tuple(paths)
        return acquirer

    def barren(self):
        """A source that teaches nothing, so the mission ends with an uncertain topic and the
        gap round actually fires. Without one the round never runs and the assertion below
        passes for the wrong reason."""
        (self.root / "barren.md").write_text(
            "# Barren\nThis file answers nothing, which is the point of it.\n", encoding="utf-8")

    def test_the_gap_round_skips_material_already_sufficiently_studied(self):
        """Found in live acceptance: a re-acquired document with 15 verified rows was studied
        again because the second round never consulted the exclusion."""
        self.barren()
        self.seed("isolation.md", "transaction isolation level serializable", 5)
        runtime = self.runtime(curriculum=self.curriculum,
                               acquirer=self.acquirer_returning("isolation.md"))
        report = runtime.study("continue", self.context()).as_dict()
        mission = self.memory.connection.execute(
            "SELECT mission_id FROM bro_study_missions ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        sources = [item.source_ref for item in self.memory.curriculum(mission)]
        self.assertNotIn("isolation.md", sources)
        self.assertTrue(any("already sufficiently studied" in note for note in report["notes"]))

    def test_the_gap_round_still_studies_genuinely_new_material(self):
        self.barren()
        self.seed("isolation.md", "transaction isolation level serializable", 5)
        runtime = self.runtime(curriculum=self.curriculum,
                               acquirer=self.acquirer_returning("consensus.md"))
        runtime.study("continue", self.context())
        mission = self.memory.connection.execute(
            "SELECT mission_id FROM bro_study_missions ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertIn("consensus.md", [item.source_ref for item in self.memory.curriculum(mission)])

    def test_the_gap_round_studies_no_source_twice_in_one_mission(self):
        self.barren()
        runtime = self.runtime(curriculum=self.curriculum,
                               acquirer=self.acquirer_returning("consensus.md", "consensus.md"))
        runtime.study("continue", self.context())
        mission = self.memory.connection.execute(
            "SELECT mission_id FROM bro_study_missions ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        sources = [item.source_ref for item in self.memory.curriculum(mission)]
        self.assertEqual(sources.count("consensus.md"), 1)

    def test_an_explicit_refresh_still_lets_the_gap_round_restudy(self):
        self.barren()
        self.seed("isolation.md", "transaction isolation level serializable", 5)
        runtime = self.runtime(curriculum=self.curriculum, refresh=True,
                               acquirer=self.acquirer_returning("isolation.md"))
        runtime.study("continue", self.context())
        mission = self.memory.connection.execute(
            "SELECT mission_id FROM bro_study_missions ORDER BY rowid DESC LIMIT 1").fetchone()[0]
        self.assertIn("isolation.md", [item.source_ref for item in self.memory.curriculum(mission)])


class ExhaustedCorpusReportTests(Base):
    """When everything is studied, say that -- not that everything was withheld."""

    def test_an_exhausted_corpus_is_reported_as_exhausted_and_nothing_is_offered_back(self):
        """Live acceptance printed "withheld 72" while handing all 72 back.

        Both halves of that were wrong and only one was fixed at the time. The count is now
        the real count, and the sources are genuinely withheld.
        """
        self.seed("isolation.md", "transaction isolation level serializable", 5)
        self.seed("consensus.md", "consensus quorum network partition", 5)
        report = self.runtime(curriculum=self.curriculum).study("continue", self.context()).as_dict()
        self.assertEqual(report["repetition"]["withheld_sufficiently_studied_sources"], 2)
        self.assertTrue(any("none was offered again" in note for note in report["notes"]))
        self.assertEqual(report["stop_reason"], StudyStop.SCOPE_EXHAUSTED.value)

    def test_a_partly_studied_corpus_still_reports_a_real_withholding(self):
        self.seed("isolation.md", "transaction isolation level serializable", 5)
        report = self.runtime(curriculum=self.curriculum).study("continue", self.context()).as_dict()
        self.assertEqual(report["repetition"]["withheld_sufficiently_studied_sources"], 1)
        self.assertTrue(any("withheld 1" in note for note in report["notes"]))
