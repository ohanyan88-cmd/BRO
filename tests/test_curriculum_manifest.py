"""The curriculum manifest: coverage by document identity rather than by vocabulary.

Every test here exists because the mechanism it guards was got wrong at least once. The
lexical model reported 27 of 32 domains covered on BRO's own architecture notes, then scored
thirty rows from the Rust Book as one, and both were the same mistake: asking what a claim
says instead of where it came from.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

from bro_runtime.curriculum import CurriculumRejected, DomainState
from bro_runtime.curriculum_manifest import (
    CurriculumManifest, RequirementState, normalise_url, source_index)
from bro_runtime.knowledge_library import GovernedKnowledgeLibrary
from bro_runtime.learning_memory import (
    DurableLearningMemory, KnowledgeKind, Provenance, SourceType)

REAL = Path(__file__).resolve().parents[1] / "contracts" / "curriculum_manifest.json"


def url_host(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or "").lower()

RUST_BOOK = "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html"
RUST_REFS = "https://doc.rust-lang.org/book/ch04-02-references-and-borrowing.html"
RUST_CARGO = "https://doc.rust-lang.org/cargo/"
PY_MODEL = "https://docs.python.org/3/reference/datamodel.html"

FIXTURE = {
    "manifest": "bro.curriculum-manifest.v1",
    "evidence_rule": {"default_min_verified_rows": 3, "default_min_sources": 1},
    "domains": [
        {"domain": "rust-engineering", "title": "Rust", "depends_on": [], "requirements": [
            {"requirement": "rs.ownership", "competency": "Ownership and borrowing",
             "basis": "publisher-structure", "min_verified_rows": 3, "min_sources": 1,
             "sources": [{"url": RUST_BOOK, "family": "rust", "publisher": "Rust project",
                          "authority_tier": "A"},
                         {"url": RUST_REFS, "family": "rust", "publisher": "Rust project",
                          "authority_tier": "A"}]},
            {"requirement": "rs.cargo", "competency": "Cargo and crates",
             "basis": "publisher-structure", "min_verified_rows": 3, "min_sources": 1,
             "sources": [{"url": RUST_CARGO, "family": "rust", "publisher": "Rust project",
                          "authority_tier": "A"}]},
        ]},
        {"domain": "python-engineering", "title": "Python", "depends_on": [], "requirements": [
            {"requirement": "py.data-model", "competency": "The Python data model",
             "basis": "publisher-structure", "min_verified_rows": 3, "min_sources": 1,
             "sources": [{"url": PY_MODEL, "family": "python",
                          "publisher": "Python Software Foundation", "authority_tier": "A"}]},
        ]},
        {"domain": "linux-systems", "title": "Linux", "depends_on": [], "requirements": [
            {"requirement": "linux.kernel", "competency": "Kernel subsystems",
             "basis": "publisher-structure", "sources": [],
             "source_gap": {"needed_publisher": "Linux kernel organisation",
                            "hosts": ["kernel.org"],
                            "reason": "no admitted source family claims this publisher"}},
        ]},
    ],
}

INDEX = {
    normalise_url(RUST_BOOK): {"acquired-rust/book-ch04-01-what-is-ownership.md"},
    normalise_url(RUST_REFS): {"acquired-rust/book-ch04-02-references-and-borrowing.md"},
    normalise_url(RUST_CARGO): {"acquired-rust/cargo.md"},
    normalise_url(PY_MODEL): {"acquired-python/3-reference-datamodel.md"},
}


class Base(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.memory = DurableLearningMemory(self.connection)
        self.manifest = CurriculumManifest(FIXTURE)

    def learn(self, source_ref: str, rows: int, *, claim: str = "a verified statement",
              digest: str = "d" * 64) -> None:
        mission = self.memory.open_study_mission(mission="study", scope=(), item_budget=50)
        item = self.memory.add_curriculum_item(mission.mission_id, topic="study",
                                               source_ref=source_ref, sequence=0)
        for index in range(rows):
            # Distinct claims on purpose: the memory keeps one row per claim, so seeding the
            # same sentence five times seeds one row and a test written that way measures
            # deduplication while believing it measures coverage.
            self.memory.record_knowledge(
                mission_id=mission.mission_id, item_id=item.item_id, topic="study",
                claim=f"{claim} ({index})",
                kind=KnowledgeKind.VERIFIED_KNOWLEDGE, source_ref=source_ref,
                source_type=SourceType.REPOSITORY_FILE, source_digest=digest,
                evidence_quote=f"{claim} ({index})",
                provenance=Provenance(source_revision="a" * 40))

    def domains(self, **kwargs):
        return {item.domain: item
                for item in self.manifest.coverage(self.memory, index=INDEX, **kwargs)}

    def requirement(self, domain: str, requirement: str):
        return {item.requirement: item
                for item in self.domains()[domain].requirements}[requirement]


class EvidenceIdentityTests(Base):
    def test_rust_progress_comes_from_the_declared_document_not_from_words(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5, claim="a statement")
        progress = self.requirement("rust-engineering", "rs.ownership")
        self.assertIs(progress.state, RequirementState.SATISFIED)
        self.assertEqual(progress.verified_rows, 5)
        self.assertEqual(progress.satisfied_sources, (RUST_BOOK,))

    def test_python_progress_comes_from_the_declared_document(self):
        self.learn("acquired-python/3-reference-datamodel.md", 4)
        progress = self.requirement("python-engineering", "py.data-model")
        self.assertIs(progress.state, RequirementState.SATISFIED)
        self.assertIs(self.domains()["python-engineering"].state, DomainState.COVERED)

    def test_the_words_in_a_claim_change_nothing(self):
        """The whole point: a row saying "ownership borrowing lifetimes Cargo" from a source
        the curriculum never declared is not evidence for Rust, and the same row from the
        Rust Book is -- whatever either of them says."""
        self.learn("docs/architecture/BRO_ARCHITECTURE_FOUNDATION_V0_2.md", 40,
                   claim="ownership borrowing lifetimes traits Cargo crate unsafe Rustonomicon")
        self.assertIs(self.domains()["rust-engineering"].state, DomainState.UNSTUDIED)
        self.assertEqual(self.requirement("rust-engineering", "rs.ownership").verified_rows, 0)

    def test_an_unrelated_source_cannot_advance_any_domain(self):
        for ref in ("acquired-nist/zero-trust.md", "src/bro_runtime/production_control.py",
                    "README.md", "contracts/self_study.json"):
            self.learn(ref, 30)
        for domain in self.domains().values():
            self.assertIs(domain.state, DomainState.UNSTUDIED, domain.domain)

    def test_one_canonical_document_does_not_cover_a_domain(self):
        """Rust has two requirements. Reading one of them well is not reading Rust."""
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 50)
        domain = self.domains()["rust-engineering"]
        self.assertIs(domain.state, DomainState.PARTIAL)
        self.assertEqual(len(domain.satisfied), 1)
        self.assertEqual(len(domain.open_with_a_source), 1)

    def test_a_domain_is_covered_only_when_every_requirement_is(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        self.assertIs(self.domains()["rust-engineering"].state, DomainState.PARTIAL)
        self.learn("acquired-rust/cargo.md", 5)
        self.assertIs(self.domains()["rust-engineering"].state, DomainState.COVERED)

    def test_evidence_below_the_threshold_is_in_progress_and_still_visible(self):
        self.learn("acquired-rust/cargo.md", 2)
        progress = self.requirement("rust-engineering", "rs.cargo")
        self.assertIs(progress.state, RequirementState.IN_PROGRESS)
        self.assertEqual(progress.verified_rows, 2)
        self.assertIn("rs.cargo", [item.requirement
                                   for item in self.domains()["rust-engineering"].open_with_a_source])

    def test_a_source_whose_bytes_changed_stops_being_evidence(self):
        self.learn("acquired-rust/cargo.md", 5, digest="old" + "0" * 61)
        self.assertIs(self.requirement("rust-engineering", "rs.cargo").state,
                      RequirementState.SATISFIED)
        moved = self.manifest.coverage(self.memory, index=INDEX,
                                       current_digests={"acquired-rust/cargo.md": "new" + "0" * 61})
        progress = {item.requirement: item
                    for domain in moved for item in domain.requirements}["rs.cargo"]
        self.assertIs(progress.state, RequirementState.UNSATISFIED)


class SourceGapTests(Base):
    def test_a_publisher_no_family_admits_becomes_a_source_gap(self):
        gap = self.requirement("linux-systems", "linux.kernel")
        self.assertIs(gap.state, RequirementState.SOURCE_GAP)
        self.assertEqual(gap.source_gap.needed_publisher, "Linux kernel organisation")
        self.assertEqual(gap.source_gap.hosts, ("kernel.org",))
        self.assertIsNone(gap.next_entry_point)

    def test_a_source_gap_is_never_satisfied_and_never_hidden(self):
        self.learn("acquired-rust/cargo.md", 99)
        domain = self.domains()["linux-systems"]
        self.assertIs(domain.state, DomainState.UNSTUDIED)
        self.assertEqual(len(domain.source_gaps), 1)
        self.assertEqual(domain.satisfied, ())

    def test_a_source_gap_reaches_the_planner_by_name(self):
        planning = self.manifest.planning_context(self.memory, index=INDEX)
        named = [(domain, item.requirement) for domain, item in planning.source_gaps]
        self.assertIn(("linux-systems", "linux.kernel"), named)
        self.assertIn("linux-systems", json.dumps(planning.as_dict()))

    def test_a_requirement_may_not_declare_both_a_source_and_a_gap(self):
        broken = json.loads(json.dumps(FIXTURE))
        broken["domains"][2]["requirements"][0]["sources"] = [
            {"url": RUST_CARGO, "family": "rust", "publisher": "x", "authority_tier": "A"}]
        with self.assertRaises(CurriculumRejected):
            CurriculumManifest(broken)

    def test_a_requirement_must_declare_one_or_the_other(self):
        broken = json.loads(json.dumps(FIXTURE))
        broken["domains"][0]["requirements"][0]["sources"] = []
        with self.assertRaises(CurriculumRejected):
            CurriculumManifest(broken)


class PlannerTests(Base):
    def test_the_planner_selects_an_unsatisfied_requirement_and_its_entry_point(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        planning = self.manifest.planning_context(self.memory, index=INDEX)
        self.assertEqual(planning.selected_domain, "rust-engineering")
        self.assertEqual(planning.selected_requirement.requirement, "rs.cargo")
        self.assertEqual(planning.selected_entry_point, RUST_CARGO)

    def test_the_planner_never_selects_a_satisfied_requirement(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        self.learn("acquired-rust/cargo.md", 5)
        planning = self.manifest.planning_context(self.memory, index=INDEX)
        self.assertEqual(planning.selected_domain, "python-engineering")
        self.assertEqual(planning.selected_requirement.requirement, "py.data-model")

    def test_the_planner_never_selects_a_domain_it_cannot_study(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        self.learn("acquired-rust/cargo.md", 5)
        self.learn("acquired-python/3-reference-datamodel.md", 5)
        planning = self.manifest.planning_context(self.memory, index=INDEX)
        self.assertIsNone(planning.selected_domain)
        self.assertEqual(len(planning.source_gaps), 1)

    def test_entry_points_are_declared_documents_and_nothing_else(self):
        declared = set(self.manifest.declared_source_urls())
        self.assertTrue(set(self.manifest.entry_points(self.memory, index=INDEX)) <= declared)

    def test_a_studied_entry_point_stops_being_offered_as_the_next_one(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        progress = self.requirement("rust-engineering", "rs.ownership")
        self.assertNotIn(RUST_BOOK, progress.unstudied_sources)
        self.assertIn(RUST_REFS, progress.unstudied_sources)


class DeterminismTests(Base):
    def test_state_survives_a_restart_and_is_not_stored_anywhere(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        before = {d.domain: d.state for d in self.manifest.coverage(self.memory, index=INDEX)}
        tables = {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        reopened = DurableLearningMemory(self.connection)
        again = CurriculumManifest(FIXTURE)
        after = {d.domain: d.state for d in again.coverage(reopened, index=INDEX)}
        self.assertEqual(before, after)
        self.assertEqual(tables, {row[0] for row in self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")})
        self.assertNotIn("bro_curriculum_coverage", tables)

    def test_the_derivation_writes_nothing(self):
        self.learn("acquired-rust/cargo.md", 5)
        rows = self.connection.execute("SELECT COUNT(*) FROM bro_study_knowledge").fetchone()[0]
        self.manifest.coverage(self.memory, index=INDEX)
        self.manifest.planning_context(self.memory, index=INDEX)
        self.manifest.master_complete(self.memory, index=INDEX)
        self.assertEqual(rows, self.connection.execute(
            "SELECT COUNT(*) FROM bro_study_knowledge").fetchone()[0])

    def test_master_completion_is_not_a_mission_stopping(self):
        self.learn("acquired-rust/book-ch04-01-what-is-ownership.md", 5)
        self.learn("acquired-rust/cargo.md", 5)
        self.learn("acquired-python/3-reference-datamodel.md", 5)
        self.assertFalse(self.manifest.master_complete(self.memory, index=INDEX))
        self.assertEqual(len(self.manifest.planning_context(
            self.memory, index=INDEX).source_gaps), 1)

    def test_one_spelling_of_a_document_meets_another(self):
        self.assertEqual(normalise_url("http://WWW.Rfc-Editor.org/rfc/rfc2119.html/"),
                         normalise_url("https://rfc-editor.org/rfc/rfc2119.html"))
        self.assertNotEqual(normalise_url("https://doc.rust-lang.org/book/ch04-01.html"),
                            normalise_url("https://doc.rust-lang.org/book/ch04-02.html"))

    def test_the_index_is_read_from_the_knowledge_registry(self):
        """The join is the registry's own record, so it is tested through the registry's
        own API rather than against a hand-written row that can drift from the schema."""
        from bro_runtime.knowledge_library import AuthorityClass
        library = GovernedKnowledgeLibrary(self.memory)
        library.stage(shelf="acquired-rust", publisher="Rust project", canonical_url=RUST_CARGO,
                      authority_class=AuthorityClass.OFFICIAL_VENDOR_DOCUMENTATION,
                      source_scope="the Rust build system", upstream_version="1",
                      content=b"Cargo is the Rust build system and package manager.",
                      local_path="acquired-rust/cargo.md", source_language="en",
                      acquisition={"requested_url": RUST_CARGO, "final_url": RUST_CARGO})
        index = source_index(self.connection)
        self.assertIn("acquired-rust/cargo.md", index[normalise_url(RUST_CARGO)])
        self.assertNotIn(normalise_url(PY_MODEL), index)


class RealManifestTests(unittest.TestCase):
    """The shipped manifest, checked for the properties that make it usable at all."""

    def setUp(self):
        self.document = json.loads(REAL.read_text(encoding="utf-8"))
        self.manifest = CurriculumManifest(self.document)

    def test_the_whole_programme_is_mapped_and_its_dependencies_resolve(self):
        """The manifest is the programme now -- there is no second file holding the domains,
        because two documents claiming the same list is how they came to disagree."""
        names = [name for name, _, _, _ in self.manifest.domains]
        self.assertEqual(len(names), 32)
        self.assertEqual(len(set(names)), 32)
        declared = set(names)
        for name, _, depends_on, requirements in self.manifest.domains:
            with self.subTest(name):
                self.assertTrue(requirements, name)
                self.assertTrue(set(depends_on) <= declared, name)

    def test_every_requirement_declares_a_source_or_names_the_publisher_it_needs(self):
        for domain in self.document["domains"]:
            for requirement in domain["requirements"]:
                with self.subTest(requirement["requirement"]):
                    self.assertTrue(bool(requirement.get("sources"))
                                    ^ bool(requirement.get("source_gap")))
                    if requirement.get("source_gap"):
                        self.assertTrue(requirement["source_gap"]["needed_publisher"])
                        self.assertTrue(requirement["source_gap"]["hosts"])

    def test_every_declared_source_is_on_an_admitted_evidence_host(self):
        from bro_runtime.source_policy import SourcePolicy
        policy = SourcePolicy.load(REAL.parent / "source_policy.json")
        for url in self.manifest.declared_source_urls():
            with self.subTest(url):
                verdict = policy.classify(url)
                self.assertTrue(verdict.admissible, url)
                self.assertTrue(verdict.auto_admit, url)
                self.assertTrue(verdict.may_produce_verified_knowledge, url)

    def test_no_source_gap_names_a_host_the_policy_already_admits(self):
        """A gap that is not a gap hides work behind a governance question nobody needs to
        answer, and is how a domain quietly stops being studied."""
        from bro_runtime.source_policy import SourcePolicy, SourcePolicyRejected
        policy = SourcePolicy.load(REAL.parent / "source_policy.json")
        for domain in self.document["domains"]:
            for requirement in domain["requirements"]:
                gap = requirement.get("source_gap")
                if not gap:
                    continue
                for host in gap["hosts"]:
                    with self.subTest(host):
                        try:
                            verdict = policy.classify(f"https://{host}/")
                        except SourcePolicyRejected:
                            continue
                        self.assertFalse(verdict.admissible and verdict.auto_admit, host)

    def test_the_manifest_declares_a_source_path_for_most_of_the_programme(self):
        total = sum(len(d["requirements"]) for d in self.document["domains"])
        gaps = sum(1 for d in self.document["domains"]
                   for r in d["requirements"] if r.get("source_gap"))
        self.assertGreaterEqual(total, 32)
        self.assertLess(gaps, total // 4, "too much of the curriculum has no admitted path")


if __name__ == "__main__":
    unittest.main()


class ReviewedRefusalTests(unittest.TestCase):
    """The two publishers the source-gap review refused, held refused.

    A governance decision that lives only in a document is one edit away from being
    reversed by someone who never read it. Both refusals had a reason, and both reasons
    are still true; if either changes, this test is where the argument has to be made
    again rather than quietly assumed.
    """

    def setUp(self):
        from bro_runtime.source_policy import SourcePolicy
        self.policy = SourcePolicy.load(REAL.parent / "source_policy.json")
        self.document = json.loads(REAL.read_text(encoding="utf-8"))

    def admitted(self, host: str) -> bool:
        from bro_runtime.source_policy import SourcePolicyRejected
        try:
            verdict = self.policy.classify(f"https://{host}/")
        except SourcePolicyRejected:
            return False
        return bool(verdict.admissible and verdict.auto_admit)

    def test_man7_org_is_not_admitted(self):
        """The man-pages project designates it as its rendering host, but this policy
        matches hosts and not paths, and admitting it would admit a book, a training
        business and a blog on the strength of one directory."""
        self.assertFalse(self.admitted("man7.org"))

    def test_sre_google_is_not_admitted(self):
        """One company's book about how that company runs its services, published by
        O'Reilly, with no standards body behind it."""
        self.assertFalse(self.admitted("sre.google"))

    def test_the_requirement_man7_was_refused_for_is_served_by_the_kernel_itself(self):
        requirement = {r["requirement"]: r for domain in self.document["domains"]
                       for r in domain["requirements"]}["linux.syscall-interface"]
        self.assertNotIn("source_gap", requirement)
        hosts = {url_host(s["url"]) for s in requirement["sources"]}
        self.assertTrue(hosts and hosts <= {"www.kernel.org", "kernel.org", "docs.kernel.org"},
                        hosts)

    def test_service_level_objectives_remain_an_honest_gap(self):
        """Refusing the only available source means the requirement stays unsatisfied, and
        saying so is the point. Closing it by admitting the book would make BRO's knowledge
        about SLOs an account of one company's practice that reads as a claim about the
        field."""
        requirement = {r["requirement"]: r for domain in self.document["domains"]
                       for r in domain["requirements"]}["sre.service-objectives"]
        self.assertIn("source_gap", requirement)
        self.assertEqual(requirement["sources"], [])
        self.assertEqual(requirement["source_gap"]["hosts"], ["sre.google"])

    def test_anthropic_kept_its_family_rather_than_gaining_a_second_one(self):
        """The publisher moved host; it did not become a new publisher. A second family for
        the same organisation is how one publisher ends up with two tiers."""
        families = [f for f in self.policy.families if "platform.claude.com" in f.hosts]
        self.assertEqual([f.family for f in families], ["anthropic"])
        self.assertEqual(len([f for f in self.policy.families
                              if f.publisher == "Anthropic"]), 1)
