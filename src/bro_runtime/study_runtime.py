"""Governed self-study: BRO reads, thinks and learns, and never acts.

"BRO, go learn" is a real capability here, and a deliberately small one. A study
mission plans a bounded curriculum, reads only sources inside a declared root,
asks the model to extract claims, and then decides for itself which of those claims
are knowledge: a claim is VERIFIED only when the model supplied a quote that is
actually present in the source it named. Everything else is kept, and kept labelled,
as inference or unverified observation.

The runtime has no executor, no provider, no network client and no writer outside
the one durable learning store. It cannot approve a skill, promote a skill, widen
authority, deploy, merge or cause any external effect, because none of those things
are reachable from here. Study produces knowledge; it never produces permission.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .learning_memory import (
    BINDING_PREFIX,
    CurriculumStatus,
    DurableLearningMemory,
    KnowledgeItem,
    KnowledgeKind,
    Provenance,
    SourceType,
    StudyStatus,
)

# A quote shorter than this proves nothing: "the" appears in every file.
MIN_EVIDENCE_QUOTE = 12
DEFAULT_SUFFIXES = (".md", ".py", ".json", ".txt", ".toml", ".yml", ".yaml", ".sh", ".cfg", ".ini")
DEFAULT_MAX_BYTES = 200_000
DEFAULT_ITEM_BUDGET = 8
DEFAULT_DIMINISHING_AFTER = 2


class StudyRejected(RuntimeError):
    pass


class StudyStop(StrEnum):
    CURRICULUM_COMPLETE = "CURRICULUM_COMPLETE"
    ITEM_BUDGET_REACHED = "ITEM_BUDGET_REACHED"
    DIMINISHING_RETURNS = "DIMINISHING_RETURNS"
    UNRESOLVED_CONTRADICTION = "UNRESOLVED_CONTRADICTION"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    SCOPE_EXHAUSTED = "SCOPE_EXHAUSTED"


@dataclass(frozen=True)
class SourceDocument:
    source_ref: str
    text: str
    digest: str
    source_type: SourceType = SourceType.REPOSITORY_FILE
    truncated: bool = False


class StudySourceReader:
    """Read-only, root-bounded, extension-bounded, size-bounded. No network at all."""

    def __init__(
        self, root: str | Path, *, allowed_suffixes: Sequence[str] = DEFAULT_SUFFIXES,
        max_bytes: int = DEFAULT_MAX_BYTES, max_sources: int = 200,
    ) -> None:
        resolved = Path(root).resolve()
        if not resolved.is_dir():
            raise StudyRejected(f"study root is not a readable directory: {root}")
        if max_bytes < 1 or max_sources < 1:
            raise StudyRejected("study reader budgets must be positive")
        self.root = resolved
        self.allowed_suffixes = tuple(allowed_suffixes)
        self.max_bytes = int(max_bytes)
        self.max_sources = int(max_sources)

    def _resolve(self, relative: str) -> Path:
        candidate = str(relative).strip()
        if not candidate:
            raise StudyRejected("source reference must not be empty")
        if candidate.startswith("/") or candidate.startswith("~"):
            raise StudyRejected("study sources are named relative to the study root")
        target = (self.root / candidate).resolve()
        if self.root != target and self.root not in target.parents:
            raise StudyRejected("study source escapes the declared study root")
        if target.suffix not in self.allowed_suffixes:
            raise StudyRejected(f"study source type is not readable: {target.suffix or '(none)'}")
        if not target.is_file():
            raise StudyRejected(f"study source is unavailable: {relative}")
        return target

    def discover(self, hints: Sequence[str] = ()) -> tuple[str, ...]:
        """List readable sources under the root, optionally narrowed by plain hints."""
        wanted = {hint.strip().lower() for hint in hints if str(hint).strip()}
        found: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if len(found) >= self.max_sources:
                break
            if not path.is_file() or path.suffix not in self.allowed_suffixes:
                continue
            if any(part.startswith(".") or part in {"__pycache__", "node_modules"} for part in path.parts):
                continue
            relative = str(path.relative_to(self.root))
            if wanted and not any(hint in relative.lower() for hint in wanted):
                continue
            found.append(relative)
        return tuple(found)

    def read(self, relative: str) -> SourceDocument:
        target = self._resolve(relative)
        raw = target.read_bytes()
        truncated = len(raw) > self.max_bytes
        body = raw[: self.max_bytes]
        return SourceDocument(
            source_ref=str(target.relative_to(self.root)),
            text=body.decode("utf-8", "replace"),
            digest=hashlib.sha256(body).hexdigest(),
            source_type=SourceType.REPOSITORY_FILE,
            truncated=truncated,
        )


@dataclass(frozen=True)
class StudyReport:
    mission_id: str
    mission: str
    status: StudyStatus
    stop_reason: StudyStop
    planned: int = 0
    studied: int = 0
    blocked: int = 0
    remaining: tuple[str, ...] = ()
    verified: int = 0
    inferences: int = 0
    unverified: int = 0
    uncertain_topics: tuple[str, ...] = ()
    contradictions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission_id": self.mission_id,
            "mission": self.mission,
            "status": self.status.value,
            "stop_reason": self.stop_reason.value,
            "curriculum": {
                "planned": self.planned, "studied": self.studied,
                "blocked": self.blocked, "remaining": list(self.remaining),
            },
            "knowledge": {
                "verified": self.verified, "inference": self.inferences,
                "unverified_observation": self.unverified,
            },
            "uncertain_topics": list(self.uncertain_topics),
            "contradictions": list(self.contradictions),
            "notes": list(self.notes),
            "external_effects": 0,
            "grants_authority": False,
        }


@dataclass(frozen=True)
class StudyContext:
    """What is true now, and who is reasoning. Provenance, never ownership."""

    environment: str = ""
    source_revision: str = ""
    instance_id: str = ""
    model_ref: str = ""
    root_ref: str = ""

    def provenance(self) -> Provenance:
        from .learning_memory import utc_now

        now = utc_now()
        return Provenance(
            model_ref=self.model_ref, source_revision=self.source_revision,
            environment=self.environment, instance_id=self.instance_id,
            first_seen_at=now, last_seen_at=now,
        )

    def binding_facts(self) -> tuple[str, ...]:
        facts = []
        if self.environment:
            facts.append(f"{BINDING_PREFIX}environment={self.environment}")
        if self.root_ref:
            facts.append(f"{BINDING_PREFIX}study_root={self.root_ref}")
        return tuple(facts)

    def current_truth(self) -> dict[str, str]:
        truth = {}
        if self.environment:
            truth["environment"] = self.environment
        if self.root_ref:
            truth["study_root"] = self.root_ref
        return truth


class GovernedStudyRuntime:
    """Plan a bounded curriculum, read, verify against source, retain, and stop."""

    def __init__(
        self,
        memory: DurableLearningMemory,
        reader: StudySourceReader,
        *,
        planner: Callable[[str, Sequence[str]], Mapping[str, Any]],
        extractor: Callable[[str, str], Mapping[str, Any]],
        item_budget: int = DEFAULT_ITEM_BUDGET,
        diminishing_after: int = DEFAULT_DIMINISHING_AFTER,
    ) -> None:
        if item_budget < 1:
            raise StudyRejected("study item_budget must be at least 1")
        if diminishing_after < 1:
            raise StudyRejected("diminishing_after must be at least 1")
        self.memory = memory
        self.reader = reader
        self.planner = planner
        self.extractor = extractor
        self.item_budget = int(item_budget)
        self.diminishing_after = int(diminishing_after)
        self.last_planner_error = ""

    # ------------------------------------------------------------ verification
    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.split()).lower()

    @classmethod
    def quote_is_in_source(cls, quote: str, source_text: str) -> bool:
        """The only route to VERIFIED: the words are demonstrably in the source."""
        cleaned = str(quote or "").strip()
        if len(cleaned) < MIN_EVIDENCE_QUOTE:
            return False
        return cls._normalize(cleaned) in cls._normalize(source_text)

    @classmethod
    def classify(cls, claim: Mapping[str, Any], document: SourceDocument) -> tuple[KnowledgeKind, str]:
        quote = str(claim.get("evidence_quote", "")).strip()
        if cls.quote_is_in_source(quote, document.text):
            return KnowledgeKind.VERIFIED_KNOWLEDGE, quote
        if bool(claim.get("inference", False)):
            return KnowledgeKind.INFERENCE, ""
        return KnowledgeKind.UNVERIFIED_OBSERVATION, ""

    # ------------------------------------------------------------------- study
    def study(self, mission: str, context: StudyContext, *, hints: Sequence[str] = ()) -> StudyReport:
        available = self.reader.discover(hints)
        record = self.memory.open_study_mission(
            mission, scope=context.binding_facts(), item_budget=self.item_budget,
            provenance=context.provenance(),
        )
        notes: list[str] = []
        self.last_planner_error = ""
        if not available:
            self.memory.set_study_status(record.mission_id, StudyStatus.BLOCKED, stop_reason=StudyStop.SCOPE_EXHAUSTED.value)
            return self._report(record.mission_id, mission, StudyStatus.BLOCKED, StudyStop.SCOPE_EXHAUSTED,
                                notes=("no readable source matched the requested scope",))

        planned = self._plan(mission, available)
        if self.last_planner_error:
            notes.append(f"curriculum planning failed, fell back to discovered sources: {self.last_planner_error}")
        if not planned:
            self.memory.set_study_status(record.mission_id, StudyStatus.BLOCKED, stop_reason=StudyStop.SCOPE_EXHAUSTED.value)
            return self._report(record.mission_id, mission, StudyStatus.BLOCKED, StudyStop.SCOPE_EXHAUSTED,
                                notes=("the study planner produced no curriculum item inside the declared scope",))

        self.memory.set_study_status(record.mission_id, StudyStatus.IN_PROGRESS)
        items = [
            self.memory.add_curriculum_item(record.mission_id, topic=topic, source_ref=source_ref, sequence=index)
            for index, (topic, source_ref) in enumerate(planned)
        ]

        stop = StudyStop.CURRICULUM_COMPLETE
        barren_streak = 0
        blocked_sources = 0
        truth = context.current_truth()
        for item in items:
            drift = self._mission_contradiction(record.mission_id, truth)
            if drift:
                notes.append(drift)
                stop = StudyStop.UNRESOLVED_CONTRADICTION
                break
            try:
                document = self.reader.read(item.source_ref)
            except StudyRejected as exc:
                blocked_sources += 1
                self.memory.set_curriculum_status(item.item_id, CurriculumStatus.BLOCKED, detail=str(exc))
                if blocked_sources >= len(items):
                    stop = StudyStop.SOURCE_UNAVAILABLE
                    break
                continue
            retained = self._study_item(record.mission_id, item, document, context)
            detail = f"{retained['verified']} verified, {retained['inference']} inference, {retained['unverified']} unverified"
            if document.truncated:
                detail += "; source truncated to the reader budget"
            if retained["error"]:
                # A study item that produced nothing because the boundary failed is not
                # an item that found nothing, and the report must not conflate them.
                detail += f"; extraction failed: {retained['error']}"
                if retained["error"] not in notes:
                    notes.append(retained["error"])
            self.memory.set_curriculum_status(item.item_id, CurriculumStatus.STUDIED, detail=detail)
            barren_streak = 0 if retained["verified"] else barren_streak + 1
            if barren_streak >= self.diminishing_after:
                stop = StudyStop.DIMINISHING_RETURNS
                notes.append(f"{barren_streak} consecutive items added no verified knowledge")
                break
        else:
            if len(items) >= self.item_budget:
                stop = StudyStop.ITEM_BUDGET_REACHED

        status = StudyStatus.COMPLETE if stop in {
            StudyStop.CURRICULUM_COMPLETE, StudyStop.ITEM_BUDGET_REACHED, StudyStop.DIMINISHING_RETURNS
        } else StudyStatus.BLOCKED
        self.memory.set_study_status(record.mission_id, status, stop_reason=stop.value)
        return self._report(record.mission_id, mission, status, stop, notes=tuple(notes))

    def _plan(self, mission: str, available: Sequence[str]) -> list[tuple[str, str]]:
        """The model may choose among real sources; it may not invent one."""
        self.last_planner_error = ""
        try:
            proposal = dict(self.planner(mission, list(available)))
        except Exception as exc:
            self.last_planner_error = f"{type(exc).__name__}:{exc}"
            proposal = {}
        allowed = set(available)
        planned: list[tuple[str, str]] = []
        seen: set[str] = set()
        for entry in proposal.get("topics", []) or []:
            if not isinstance(entry, Mapping):
                continue
            topic = str(entry.get("topic", "")).strip()
            source_ref = str(entry.get("source_ref", "")).strip()
            if not topic or source_ref not in allowed or source_ref in seen:
                continue
            seen.add(source_ref)
            planned.append((topic, source_ref))
            if len(planned) >= self.item_budget:
                break
        if not planned:
            # A planner that produced nothing usable does not end the mission: read the
            # discovered sources in order, so "study this" still studies something real.
            for source_ref in list(available)[: self.item_budget]:
                planned.append((f"{mission} :: {source_ref}", source_ref))
        return planned

    def _study_item(self, mission_id: str, item, document: SourceDocument, context: StudyContext) -> dict[str, int]:
        try:
            extracted = dict(self.extractor(item.topic, document.text))
            error = ""
        except Exception as exc:
            extracted = {}
            error = f"{type(exc).__name__}:{exc}"
        counts = {"verified": 0, "inference": 0, "unverified": 0, "error": error}
        for claim in extracted.get("claims", []) or []:
            if not isinstance(claim, Mapping):
                continue
            text = str(claim.get("claim", "")).strip()
            if not text:
                continue
            kind, quote = self.classify(claim, document)
            stored = self.memory.record_knowledge(
                mission_id=mission_id, item_id=item.item_id, topic=item.topic, claim=text,
                kind=kind, source_ref=document.source_ref,
                source_type=document.source_type if kind is not KnowledgeKind.INFERENCE else SourceType.MODEL_INFERENCE,
                source_digest=document.digest, evidence_quote=quote,
                scope=context.binding_facts(), provenance=context.provenance(),
            )
            if stored is None:
                continue
            if kind is KnowledgeKind.VERIFIED_KNOWLEDGE:
                counts["verified"] += 1
            elif kind is KnowledgeKind.INFERENCE:
                counts["inference"] += 1
            else:
                counts["unverified"] += 1
        return counts

    def _mission_contradiction(self, mission_id: str, current_truth: Mapping[str, str]) -> str:
        record = self.memory.study_mission(mission_id)
        for key, current in current_truth.items():
            prefix = f"{BINDING_PREFIX}{key}="
            for fact in record.scope:
                if fact.startswith(prefix) and fact[len(prefix):] != str(current):
                    return f"mission was planned with {key}={fact[len(prefix):]} but current truth says {current}"
        return ""

    def _report(self, mission_id: str, mission: str, status: StudyStatus, stop: StudyStop,
                notes: Sequence[str] = ()) -> StudyReport:
        curriculum = self.memory.curriculum(mission_id)
        knowledge = self.memory.knowledge(mission_id)
        remaining = tuple(item.topic for item in curriculum if item.status is CurriculumStatus.PENDING)
        uncertain = tuple(dict.fromkeys(
            item.topic for item in knowledge if item.kind is not KnowledgeKind.VERIFIED_KNOWLEDGE
        ))
        return StudyReport(
            mission_id=mission_id, mission=mission, status=status, stop_reason=stop,
            planned=len(curriculum),
            studied=sum(1 for item in curriculum if item.status is CurriculumStatus.STUDIED),
            blocked=sum(1 for item in curriculum if item.status is CurriculumStatus.BLOCKED),
            remaining=remaining,
            verified=sum(1 for item in knowledge if item.kind is KnowledgeKind.VERIFIED_KNOWLEDGE),
            inferences=sum(1 for item in knowledge if item.kind is KnowledgeKind.INFERENCE),
            unverified=sum(1 for item in knowledge if item.kind is KnowledgeKind.UNVERIFIED_OBSERVATION),
            uncertain_topics=uncertain, notes=tuple(notes),
        )

    # ---------------------------------------------------------------- recall
    def recall(self, topic: str, context: StudyContext, *, limit: int = 5) -> dict[str, Any]:
        """Retained study knowledge, offered as context and never as permission."""
        digests = {}
        retrieval = self.memory.retrieve_knowledge(
            topic, current_truth=context.current_truth(), current_digests=digests, limit=limit
        )
        return {
            "advisory": True,
            "grants_authority": False,
            "knowledge": [self._payload(item) for item in retrieval.knowledge],
            "withheld_for_contradiction": [self._payload(item) for item in retrieval.withheld],
            "stale": [self._payload(item) for item in retrieval.stale],
        }

    @staticmethod
    def _payload(item: KnowledgeItem) -> dict[str, Any]:
        return {
            "knowledge_id": item.knowledge_id,
            "topic": item.topic,
            "claim": item.claim,
            "kind": item.kind.value,
            "verification_state": item.verification_state.value,
            "confidence": item.confidence,
            "source_ref": item.source_ref,
            "source_type": item.source_type.value,
            "source_digest": item.source_digest,
            "evidence_quote": item.evidence_quote,
            "recorded_at": item.created_at,
            "provenance": item.provenance.as_dict(),
        }
