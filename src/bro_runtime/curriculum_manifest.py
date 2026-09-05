"""Where each domain is studied, what counts as progress in it, and what settles that.

Coverage used to be a word search. A domain was covered when enough VERIFIED rows contained
enough of its keywords, which meant the authoritative answer to "has BRO learned Rust" was
decided by which strings someone had guessed into a contract. That guess was wrong twice in
opposite directions -- once making 27 of 32 domains look covered by BRO's own architecture
notes, once scoring thirty rows from the Rust Book as one -- and the second correction is
what showed the mechanism was the problem rather than the vocabulary.

Here the question is answered by identity instead of by language. The manifest declares, per
requirement, the canonical documents that are evidence for it. A requirement is satisfied
when enough VERIFIED knowledge has actually been retained from those declared documents.
Nothing else can satisfy it: an unrelated source cannot advance a domain, because the
derivation never looks at what a row says, only at where it came from.

Two consequences are deliberate and are not defects.

A requirement whose publisher no admitted source family claims is a SOURCE_GAP. It is
reported by name, with the publisher and the hosts that would be needed. It is never
satisfied, never fabricated a source for, and never quietly dropped from the curriculum --
admitting a publisher is a governance decision and is nobody's to take from inside here.

And a domain is not covered by reading one canonical document, however good. Every
requirement that has a source path must be satisfied on its own evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from .curriculum import CurriculumRejected, DomainState
from .learning_memory import KnowledgeKind

DEFAULT_MIN_VERIFIED_ROWS = 3
# A corpus document with this much verified knowledge retained from it is not planned again
# without a reason. Unchanged from the lexical model: it was never the part that was wrong.
SOURCE_SUFFICIENTLY_STUDIED = 3
DEFAULT_MIN_SOURCES = 1
PLANNING_DOMAIN_LIMIT = 10
PLANNING_REQUIREMENT_LIMIT = 6


class RequirementState(StrEnum):
    SATISFIED = "SATISFIED"
    IN_PROGRESS = "IN_PROGRESS"
    UNSATISFIED = "UNSATISFIED"
    SOURCE_GAP = "SOURCE_GAP"


def normalise_url(url: str) -> str:
    """One spelling per document, so a declared entry point and a stored one can meet.

    Only the parts that never change which document is addressed are normalised: the scheme,
    the case of the host, a leading ``www.`` and a trailing slash. The path's case is left
    alone, because on most of these publishers it is significant.
    """
    parts = urlsplit(str(url or "").strip())
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return urlunsplit(("https", host, path, parts.query, ""))


@dataclass(frozen=True)
class DeclaredSource:
    url: str
    family: str
    publisher: str
    authority_tier: str

    @property
    def key(self) -> str:
        return normalise_url(self.url)


@dataclass(frozen=True)
class SourceGap:
    """A requirement with no admitted way to study it, named rather than hidden."""

    needed_publisher: str
    hosts: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"needed_publisher": self.needed_publisher, "hosts": list(self.hosts),
                "reason": self.reason}


@dataclass(frozen=True)
class Requirement:
    requirement: str
    competency: str
    basis: str
    sources: tuple[DeclaredSource, ...]
    min_verified_rows: int = DEFAULT_MIN_VERIFIED_ROWS
    min_sources: int = DEFAULT_MIN_SOURCES
    source_gap: SourceGap | None = None


@dataclass(frozen=True)
class RequirementProgress:
    requirement: str
    competency: str
    state: RequirementState
    verified_rows: int
    satisfied_sources: tuple[str, ...]
    declared_sources: tuple[str, ...]
    unstudied_sources: tuple[str, ...]
    source_gap: SourceGap | None = None

    @property
    def is_open(self) -> bool:
        return self.state is not RequirementState.SATISFIED

    @property
    def next_entry_point(self) -> str | None:
        """The canonical document to study next for this requirement, if there is one."""
        if self.state is RequirementState.SOURCE_GAP:
            return None
        return self.unstudied_sources[0] if self.unstudied_sources else None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "requirement": self.requirement, "competency": self.competency,
            "state": self.state.value, "verified_rows": self.verified_rows,
            "satisfied_sources": len(self.satisfied_sources),
            "declared_sources": len(self.declared_sources),
        }
        if self.next_entry_point:
            payload["next_entry_point"] = self.next_entry_point
        if self.source_gap:
            payload["source_gap"] = self.source_gap.as_dict()
        return payload


@dataclass(frozen=True)
class DomainProgress:
    domain: str
    title: str
    state: DomainState
    requirements: tuple[RequirementProgress, ...]
    depends_on: tuple[str, ...]
    unmet_dependencies: tuple[str, ...] = ()

    @property
    def is_open(self) -> bool:
        return self.state is not DomainState.COVERED

    @property
    def satisfied(self) -> tuple[RequirementProgress, ...]:
        return tuple(item for item in self.requirements
                     if item.state is RequirementState.SATISFIED)

    @property
    def source_gaps(self) -> tuple[RequirementProgress, ...]:
        return tuple(item for item in self.requirements
                     if item.state is RequirementState.SOURCE_GAP)

    @property
    def open_with_a_source(self) -> tuple[RequirementProgress, ...]:
        """The requirements BRO can actually do something about right now."""
        return tuple(item for item in self.requirements
                     if item.is_open and item.state is not RequirementState.SOURCE_GAP)

    @property
    def verified_rows(self) -> int:
        return sum(item.verified_rows for item in self.requirements)

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain, "title": self.title, "state": self.state.value,
            "requirements_total": len(self.requirements),
            "requirements_satisfied": len(self.satisfied),
            "requirements_open": len(self.open_with_a_source),
            "source_gaps": len(self.source_gaps),
            "unmet_dependencies": list(self.unmet_dependencies),
            "open_requirements": [item.as_dict()
                                  for item in self.open_with_a_source[:PLANNING_REQUIREMENT_LIMIT]],
        }


@dataclass(frozen=True)
class ManifestPlanningContext:
    """What the planner is given: where the gaps are, and the document that closes one."""

    covered: tuple[DomainProgress, ...]
    partial: tuple[DomainProgress, ...]
    unstudied: tuple[DomainProgress, ...]
    source_gaps: tuple[tuple[str, RequirementProgress], ...]
    selected_domain: str | None = None
    selected_requirement: RequirementProgress | None = None
    # What the runtime needs to keep its own promises: which corpus documents are already
    # studied enough to withhold, and which of them something justifies returning to.
    studied_sources: tuple[str, ...] = ()
    revisit_allowed: Mapping[str, str] = field(default_factory=dict)
    entry_points: tuple[str, ...] = ()

    @property
    def selected_entry_point(self) -> str | None:
        return self.selected_requirement.next_entry_point if self.selected_requirement else None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "master_curriculum_complete": not (self.partial or self.unstudied),
            "covered_domains": [item.as_dict() for item in self.covered[:PLANNING_DOMAIN_LIMIT]],
            "partially_covered_domains": [item.as_dict()
                                          for item in self.partial[:PLANNING_DOMAIN_LIMIT]],
            "next_uncovered_domains": [item.as_dict()
                                       for item in self.unstudied[:PLANNING_DOMAIN_LIMIT]],
            "source_gaps": [{"domain": domain, **item.as_dict()}
                            for domain, item in self.source_gaps],
        }
        if self.selected_requirement is not None:
            payload["selected"] = {
                "domain": self.selected_domain,
                "requirement": self.selected_requirement.requirement,
                "competency": self.selected_requirement.competency,
                "entry_point": self.selected_entry_point,
            }
        return payload

    def summary(self) -> str:
        return (f"{len(self.covered)} covered, {len(self.partial)} partial, "
                f"{len(self.unstudied)} unstudied of "
                f"{len(self.covered) + len(self.partial) + len(self.unstudied)} domains, "
                f"{len(self.source_gaps)} source gap(s)")


def source_index(connection) -> dict[str, set[str]]:
    """Map every declared spelling of an acquired document to the ref its knowledge carries.

    The knowledge library records what was asked for, what answered, and what the publisher
    calls the document; a manifest may reasonably name any of the three. The study rows are
    keyed by the corpus path, so this is the join between a declared entry point and the
    evidence that came from it.
    """
    index: dict[str, set[str]] = {}
    try:
        cursor = connection.execute(
            "SELECT local_path, requested_url, final_url, canonical_url FROM bro_knowledge_sources")
    except Exception:
        return index
    for local_path, requested, final, canonical in cursor:
        if not local_path:
            continue
        for url in (requested, final, canonical):
            if url:
                index.setdefault(normalise_url(url), set()).add(local_path)
    return index


class CurriculumManifest:
    """The declared programme, and the deterministic answer to how far through it BRO is."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        domains = document.get("domains") or ()
        if not domains:
            raise CurriculumRejected("a curriculum manifest must declare its domains")
        rule = dict(document.get("evidence_rule", {}))
        self.default_min_rows = int(rule.get("default_min_verified_rows",
                                             DEFAULT_MIN_VERIFIED_ROWS))
        self.default_min_sources = int(rule.get("default_min_sources", DEFAULT_MIN_SOURCES))
        self.domains: tuple[tuple[str, str, tuple[str, ...], tuple[Requirement, ...]], ...] = tuple(
            (str(entry["domain"]), str(entry["title"]),
             tuple(str(name) for name in entry.get("depends_on", ())),
             self._requirements(entry))
            for entry in domains
        )
        known = {name for name, _, _, _ in self.domains}
        dangling = sorted({dep for _, _, deps, _ in self.domains for dep in deps} - known)
        if dangling:
            raise CurriculumRejected(f"dependencies name domains that do not exist: {dangling}")
        empty = sorted(name for name, _, _, reqs in self.domains if not reqs)
        if empty:
            raise CurriculumRejected(f"domains declare no requirements: {empty}")
        seen: set[str] = set()
        for _, _, _, reqs in self.domains:
            for requirement in reqs:
                if requirement.requirement in seen:
                    raise CurriculumRejected(
                        f"requirement id is declared twice: {requirement.requirement}")
                seen.add(requirement.requirement)

    def _requirements(self, entry: Mapping[str, Any]) -> tuple[Requirement, ...]:
        result = []
        for item in entry.get("requirements", ()):
            gap = item.get("source_gap")
            sources = tuple(
                DeclaredSource(url=str(s["url"]), family=str(s.get("family", "")),
                               publisher=str(s.get("publisher", "")),
                               authority_tier=str(s.get("authority_tier", "")))
                for s in item.get("sources", ()))
            if not sources and not gap:
                raise CurriculumRejected(
                    f"{item.get('requirement')!r} declares neither a source nor a source gap")
            if sources and gap:
                raise CurriculumRejected(
                    f"{item.get('requirement')!r} declares both a source and a source gap")
            result.append(Requirement(
                requirement=str(item["requirement"]), competency=str(item["competency"]),
                basis=str(item.get("basis", "judgement")), sources=sources,
                min_verified_rows=int(item.get("min_verified_rows", self.default_min_rows)),
                min_sources=int(item.get("min_sources", self.default_min_sources)),
                source_gap=SourceGap(needed_publisher=str(gap["needed_publisher"]),
                                     hosts=tuple(str(h) for h in gap.get("hosts", ())),
                                     reason=str(gap.get("reason", ""))) if gap else None,
            ))
        return tuple(result)

    @classmethod
    def load(cls, path: str | Path) -> "CurriculumManifest":
        try:
            return cls(json.loads(Path(path).read_text(encoding="utf-8")))
        except OSError as exc:
            raise CurriculumRejected(f"curriculum manifest is unreadable: {exc}") from None
        except json.JSONDecodeError as exc:
            raise CurriculumRejected(f"curriculum manifest is not valid JSON: {exc}") from None
        except KeyError as exc:
            raise CurriculumRejected(f"curriculum manifest is incomplete: {exc}") from None

    # ------------------------------------------------------------------- derivation
    def coverage(self, memory, *, index: Mapping[str, set[str]] | None = None,
                 current_digests: Mapping[str, str] | None = None) -> tuple[DomainProgress, ...]:
        """Read the one memory and say, per requirement, what the evidence actually supports."""
        resolved = dict(index) if index is not None else source_index(memory.connection)
        rows = self._rows(memory)
        stale = self._stale(rows, current_digests or {})
        per_ref: dict[str, int] = {}
        for row in rows:
            if row["kind"] == KnowledgeKind.VERIFIED_KNOWLEDGE.value:
                per_ref[row["source_ref"]] = per_ref.get(row["source_ref"], 0) + 1

        states: dict[str, DomainProgress] = {}
        for domain, title, depends_on, requirements in self.domains:
            progress = tuple(self._progress(item, per_ref, resolved, stale)
                             for item in requirements)
            states[domain] = DomainProgress(
                domain=domain, title=title, state=self._domain_state(progress),
                requirements=progress, depends_on=depends_on)
        return tuple(
            DomainProgress(
                **{**item.__dict__,
                   "unmet_dependencies": tuple(dep for dep in item.depends_on
                                               if dep in states and states[dep].is_open)})
            for item in states.values()
        )

    def _progress(self, requirement: Requirement, per_ref: Mapping[str, int],
                  index: Mapping[str, set[str]], stale: set[str]) -> RequirementProgress:
        if requirement.source_gap is not None:
            return RequirementProgress(
                requirement=requirement.requirement, competency=requirement.competency,
                state=RequirementState.SOURCE_GAP, verified_rows=0, satisfied_sources=(),
                declared_sources=(), unstudied_sources=(), source_gap=requirement.source_gap)

        rows = 0
        studied: list[str] = []
        unstudied: list[str] = []
        for source in requirement.sources:
            refs = index.get(source.key, set())
            count = sum(per_ref.get(ref, 0) for ref in refs if ref not in stale)
            rows += count
            (studied if count else unstudied).append(source.url)

        state = RequirementState.UNSATISFIED
        if rows >= requirement.min_verified_rows and len(studied) >= requirement.min_sources:
            state = RequirementState.SATISFIED
        elif rows:
            state = RequirementState.IN_PROGRESS
        return RequirementProgress(
            requirement=requirement.requirement, competency=requirement.competency, state=state,
            verified_rows=rows, satisfied_sources=tuple(studied),
            declared_sources=tuple(source.url for source in requirement.sources),
            unstudied_sources=tuple(unstudied or
                                    [source.url for source in requirement.sources]))

    @staticmethod
    def _domain_state(progress: Sequence[RequirementProgress]) -> DomainState:
        """Covered means every requirement that can be worked is satisfied -- not most of them.

        A source gap neither satisfies a domain nor blocks it forever: the domain is covered
        on the requirements it has a way to study, and the gap stays visible on its own.
        """
        actionable = [item for item in progress if item.state is not RequirementState.SOURCE_GAP]
        if not actionable:
            return DomainState.UNSTUDIED
        if all(item.state is RequirementState.SATISFIED for item in actionable):
            return DomainState.COVERED
        if any(item.verified_rows for item in actionable):
            return DomainState.PARTIAL
        return DomainState.UNSTUDIED

    # -------------------------------------------------------------------- planning
    def planning_context(self, memory, *, index: Mapping[str, set[str]] | None = None,
                         current_digests: Mapping[str, str] | None = None,
                         revisit_allowed: Mapping[str, str] | None = None
                         ) -> ManifestPlanningContext:
        resolved = dict(index) if index is not None else source_index(memory.connection)
        coverage = self.coverage(memory, index=resolved, current_digests=current_digests)
        order = {name: position for position, (name, _, _, _) in enumerate(self.domains)}

        def by_state(state):
            return sorted((item for item in coverage if item.state is state),
                          key=lambda item: (len(item.unmet_dependencies), order[item.domain]))

        unstudied, partial = by_state(DomainState.UNSTUDIED), by_state(DomainState.PARTIAL)
        covered = by_state(DomainState.COVERED)
        gaps = tuple((item.domain, requirement) for item in coverage
                     for requirement in item.source_gaps)

        selected_domain, selected = None, None
        for candidate in [*partial, *unstudied]:
            open_now = candidate.open_with_a_source
            if open_now:
                selected_domain, selected = candidate.domain, open_now[0]
                break
        entry_points: list[str] = []
        if selected_domain is not None:
            chosen = {item.domain: item for item in coverage}[selected_domain]
            for requirement in chosen.open_with_a_source:
                for url in requirement.unstudied_sources:
                    if url not in entry_points:
                        entry_points.append(url)
        return ManifestPlanningContext(
            covered=tuple(covered), partial=tuple(partial), unstudied=tuple(unstudied),
            source_gaps=gaps, selected_domain=selected_domain, selected_requirement=selected,
            studied_sources=self.studied_sources(memory), entry_points=tuple(entry_points[:6]),
            revisit_allowed=dict(revisit_allowed or {}))

    def entry_points(self, memory, *, index: Mapping[str, set[str]] | None = None,
                     limit: int = 6) -> tuple[str, ...]:
        """The canonical documents that would advance the currently selected domain."""
        return self.planning_context(memory, index=index).entry_points[:limit]

    def studied_sources(self, memory, *, minimum: int = SOURCE_SUFFICIENTLY_STUDIED
                        ) -> tuple[str, ...]:
        """Corpus documents carrying enough verified knowledge to be withheld from planning."""
        counts: dict[str, int] = {}
        for row in self._rows(memory):
            if row["kind"] == KnowledgeKind.VERIFIED_KNOWLEDGE.value:
                counts[row["source_ref"]] = counts.get(row["source_ref"], 0) + 1
        return tuple(sorted(ref for ref, count in counts.items() if count >= minimum))

    def master_complete(self, memory, *, index: Mapping[str, set[str]] | None = None,
                        current_digests: Mapping[str, str] | None = None) -> bool:
        """Whether the programme is finished. A mission's stop reason never answers this."""
        return all(item.state is DomainState.COVERED
                   for item in self.coverage(memory, index=index,
                                             current_digests=current_digests))

    def declared_source_urls(self) -> tuple[str, ...]:
        return tuple(sorted({source.url for _, _, _, requirements in self.domains
                             for requirement in requirements
                             for source in requirement.sources}))

    # --------------------------------------------------------------------- helpers
    @staticmethod
    def _rows(memory) -> list[dict[str, str]]:
        cursor = memory.connection.execute(
            "SELECT source_ref, kind, source_digest FROM bro_study_knowledge")
        return [{"source_ref": row[0], "kind": row[1], "source_digest": row[2]}
                for row in cursor]

    @staticmethod
    def _stale(rows: Iterable[Mapping[str, str]],
               current_digests: Mapping[str, str]) -> set[str]:
        """A source whose bytes changed since it was studied no longer counts as evidence."""
        stale: set[str] = set()
        for row in rows:
            expected = current_digests.get(row["source_ref"])
            if expected and row["source_digest"] and expected != row["source_digest"]:
                stale.add(row["source_ref"])
        return stale
