"""What BRO has actually learned, and what it has only visited.

A mission's CURRICULUM_COMPLETE says one bounded plan finished. It has never said the long
study programme finished, and the two were easy to confuse because nothing held the second
answer. This module holds it -- and holds it as a *derivation* rather than a second store,
because a coverage table maintained beside the knowledge it summarises drifts from it, and
then two things claim to know the same fact.

Coverage is evidence-based on purpose. A domain is not covered because a mission mentioned
it, because one document was read, or because rows exist. It is covered when enough distinct
sources that were genuinely studied carry enough verified knowledge about it. Everything
short of that is PARTIAL, which is a different sentence and reads like one.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .learning_memory import KnowledgeKind, query_terms

DEFAULT_MIN_VERIFIED_ROWS = 12
DEFAULT_MIN_SOURCES = 2
SOURCE_MIN_VERIFIED_ROWS = 3
# One keyword is not evidence. Ordinary technical English appears in every document,
# and matching on a single word made 27 of 32 domains look covered by BRO's own
# architecture notes -- including Rust, which it has never studied.
DEFAULT_MIN_DISTINCT_KEYWORDS = 2
# What the planner is shown. Bounded on purpose: the point is to tell it where the empty
# territory is, not to hand it the knowledge base and hope it reads carefully.
PLANNING_DOMAIN_LIMIT = 10
PLANNING_SOURCE_LIMIT = 40


class CurriculumRejected(RuntimeError):
    pass


class DomainState(StrEnum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    UNSTUDIED = "UNSTUDIED"


class RevisitReason(StrEnum):
    """The only grounds on which already-studied material may be planned again."""

    CONTRADICTION = "CONTRADICTION"
    STALE_SOURCE = "STALE_SOURCE"
    MISSING_VERIFICATION = "MISSING_VERIFICATION"
    DEPENDENCY_DEPTH = "DEPENDENCY_DEPTH"
    INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
    EXPLICIT_REFRESH = "EXPLICIT_REFRESH"


@dataclass(frozen=True)
class Domain:
    domain: str
    title: str
    depends_on: tuple[str, ...]
    keywords: tuple[str, ...]
    min_verified_rows: int = DEFAULT_MIN_VERIFIED_ROWS
    min_sources: int = DEFAULT_MIN_SOURCES


@dataclass(frozen=True)
class DomainCoverage:
    domain: str
    title: str
    state: DomainState
    verified_rows: int
    studied_sources: tuple[str, ...]
    depends_on: tuple[str, ...]
    unmet_dependencies: tuple[str, ...] = ()

    @property
    def is_open(self) -> bool:
        return self.state is not DomainState.COVERED

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain, "title": self.title, "state": self.state.value,
            "verified_rows": self.verified_rows, "studied_sources": len(self.studied_sources),
            "unmet_dependencies": list(self.unmet_dependencies),
        }


@dataclass(frozen=True)
class PlanningContext:
    """The bounded view of durable state a planner is given before it plans."""

    covered: tuple[DomainCoverage, ...]
    partial: tuple[DomainCoverage, ...]
    unstudied: tuple[DomainCoverage, ...]
    studied_sources: tuple[str, ...]
    revisit_allowed: Mapping[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "master_curriculum_complete": not (self.partial or self.unstudied),
            "covered_domains": [item.as_dict() for item in self.covered[:PLANNING_DOMAIN_LIMIT]],
            "partially_covered_domains": [item.as_dict() for item in self.partial[:PLANNING_DOMAIN_LIMIT]],
            "next_uncovered_domains": [item.as_dict() for item in self.unstudied[:PLANNING_DOMAIN_LIMIT]],
            "already_studied_sources": list(self.studied_sources[:PLANNING_SOURCE_LIMIT]),
            "sources_that_may_be_revisited": dict(self.revisit_allowed),
        }

    def summary(self) -> str:
        return (f"{len(self.covered)} covered, {len(self.partial)} partial, "
                f"{len(self.unstudied)} unstudied of "
                f"{len(self.covered) + len(self.partial) + len(self.unstudied)} domains")


class MasterCurriculum:
    """The programme, and the deterministic answer to how far through it BRO is."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        domains = document.get("domains") or ()
        if not domains:
            raise CurriculumRejected("a master curriculum must declare its domains")
        rule = dict(document.get("coverage_rule", {}))
        source_rule = dict(rule.get("source_sufficiently_studied", {}))
        self.source_min_verified = int(source_rule.get("min_verified_rows", SOURCE_MIN_VERIFIED_ROWS))
        self.min_distinct_keywords = int(
            rule.get("min_distinct_keywords", DEFAULT_MIN_DISTINCT_KEYWORDS))
        self.domains = tuple(
            Domain(
                domain=str(entry["domain"]), title=str(entry["title"]),
                depends_on=tuple(str(name) for name in entry.get("depends_on", ())),
                keywords=tuple(str(word).lower() for word in entry["keywords"]),
                min_verified_rows=int(entry.get("min_verified_rows",
                                                rule.get("default_min_verified_rows",
                                                         DEFAULT_MIN_VERIFIED_ROWS))),
                min_sources=int(entry.get("min_sources",
                                          rule.get("default_min_sources", DEFAULT_MIN_SOURCES))),
            )
            for entry in domains
        )
        known = {domain.domain for domain in self.domains}
        dangling = sorted({dep for domain in self.domains for dep in domain.depends_on} - known)
        if dangling:
            raise CurriculumRejected(f"dependencies name domains that do not exist: {dangling}")

    @classmethod
    def load(cls, path: str | Path) -> "MasterCurriculum":
        try:
            return cls(json.loads(Path(path).read_text(encoding="utf-8")))
        except OSError as exc:
            raise CurriculumRejected(f"master curriculum is unreadable: {exc}") from None
        except json.JSONDecodeError as exc:
            raise CurriculumRejected(f"master curriculum is not valid JSON: {exc}") from None

    # ------------------------------------------------------------------- coverage
    def coverage(self, memory, *, current_digests: Mapping[str, str] | None = None
                 ) -> tuple[DomainCoverage, ...]:
        """Read the one memory and say, per domain, what the evidence supports."""
        rows = self._rows(memory)
        per_source = self._sufficient_sources(rows)
        stale = self._stale_sources(rows, current_digests or {})
        states: dict[str, DomainCoverage] = {}
        for domain in self.domains:
            wanted = set(domain.keywords)
            verified = 0
            sources: set[str] = set()
            for row in rows:
                if row["kind"] != KnowledgeKind.VERIFIED_KNOWLEDGE.value:
                    continue
                if not self._matches(row, wanted, self.min_distinct_keywords):
                    continue
                verified += 1
                if row["source_ref"] in per_source and row["source_ref"] not in stale:
                    sources.add(row["source_ref"])
            state = DomainState.UNSTUDIED
            if verified >= domain.min_verified_rows and len(sources) >= domain.min_sources:
                state = DomainState.COVERED
            elif verified:
                state = DomainState.PARTIAL
            states[domain.domain] = DomainCoverage(
                domain=domain.domain, title=domain.title, state=state,
                verified_rows=verified, studied_sources=tuple(sorted(sources)),
                depends_on=domain.depends_on,
            )
        # A domain whose prerequisites are open is worth naming as blocked, so the planner
        # does not walk into advanced material before its foundation exists.
        return tuple(
            DomainCoverage(
                **{**item.__dict__,
                   "unmet_dependencies": tuple(
                       dep for dep in item.depends_on
                       if dep in states and states[dep].is_open)}
            )
            for item in states.values()
        )

    def planning_context(self, memory, *, current_digests: Mapping[str, str] | None = None,
                         revisit_allowed: Mapping[str, str] | None = None) -> PlanningContext:
        """Everything a planner needs about the past, and nothing more."""
        coverage = self.coverage(memory, current_digests=current_digests)
        order = {domain.domain: index for index, domain in enumerate(self.domains)}
        unstudied = sorted(
            (item for item in coverage if item.state is DomainState.UNSTUDIED),
            key=lambda item: (len(item.unmet_dependencies), order[item.domain]))
        partial = sorted(
            (item for item in coverage if item.state is DomainState.PARTIAL),
            key=lambda item: (len(item.unmet_dependencies), -item.verified_rows, order[item.domain]))
        covered = sorted((item for item in coverage if item.state is DomainState.COVERED),
                         key=lambda item: order[item.domain])
        return PlanningContext(
            covered=tuple(covered), partial=tuple(partial), unstudied=tuple(unstudied),
            studied_sources=tuple(sorted(self._sufficient_sources(self._rows(memory)))),
            revisit_allowed=dict(revisit_allowed or {}),
        )

    def master_complete(self, memory, *, current_digests: Mapping[str, str] | None = None) -> bool:
        """Whether the programme is finished. A mission's stop reason never answers this."""
        return all(item.state is DomainState.COVERED
                   for item in self.coverage(memory, current_digests=current_digests))

    # -------------------------------------------------------------------- helpers
    @staticmethod
    def _rows(memory) -> list[dict[str, str]]:
        cursor = memory.connection.execute(
            "SELECT topic, claim, source_ref, kind, source_digest FROM bro_study_knowledge")
        return [{"topic": row[0], "claim": row[1], "source_ref": row[2], "kind": row[3],
                 "source_digest": row[4]} for row in cursor]

    def _sufficient_sources(self, rows: Sequence[Mapping[str, str]]) -> set[str]:
        counts: dict[str, int] = {}
        for row in rows:
            if row["kind"] == KnowledgeKind.VERIFIED_KNOWLEDGE.value:
                counts[row["source_ref"]] = counts.get(row["source_ref"], 0) + 1
        return {ref for ref, count in counts.items() if count >= self.source_min_verified}

    @staticmethod
    def _stale_sources(rows: Sequence[Mapping[str, str]],
                       current_digests: Mapping[str, str]) -> set[str]:
        """A source whose bytes changed since it was studied no longer counts as covered."""
        stale: set[str] = set()
        for row in rows:
            expected = current_digests.get(row["source_ref"])
            if expected and row["source_digest"] and expected != row["source_digest"]:
                stale.add(row["source_ref"])
        return stale

    @staticmethod
    def _matches(row: Mapping[str, str], wanted: set[str], minimum: int) -> bool:
        """Enough distinct signals, where distinct means genuinely separate evidence.

        Two signals one of which contains the other are one signal wearing two hats: the
        word "evaluation" satisfied both "evaluation" and "eval", which was the whole of the
        evidence that made agent-evaluation look COVERED by BRO's own authority notes.
        """
        haystack = f"{row['topic']} {row['claim']} {row['source_ref']}".lower()
        found = [keyword for keyword in wanted if keyword in haystack]
        independent = [
            keyword for keyword in found
            if not any(other != keyword and keyword in other for other in found)
        ]
        return len(independent) >= minimum
