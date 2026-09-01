"""Governed durable MEMORY runtime.

MEMORY preserves continuity without turning stored claims into current fact.
Every retrieval returns provenance, freshness, authority and conflict state.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum

from .task_runtime import utc_now


class MemoryClass(StrEnum):
    SELF = "SELF_MEMORY"
    RELATIONSHIP_FOUNDATION = "RELATIONSHIP_FOUNDATION"
    USER_CONTEXT = "USER_CONTEXT"
    PROJECT = "PROJECT_MEMORY"
    WORK = "WORK_MEMORY"
    DECISION = "DECISION_MEMORY"
    EVIDENCE_REFERENCE = "EVIDENCE_REFERENCE_MEMORY"
    FAILURE_LEARNING = "FAILURE_LEARNING_MEMORY"
    WORKING = "WORKING_MEMORY"
    QUARANTINE = "QUARANTINE"


class MemoryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class MemoryFreshness(StrEnum):
    CURRENT = "CURRENT"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class MemoryRejected(ValueError):
    pass


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    memory_class: MemoryClass
    subject: str
    scope: str
    content: object
    source_owner: str
    source_ref: str
    authority_ref: str | None
    sensitivity: str
    confidence: str
    effective_at: str | None
    freshness: MemoryFreshness
    supersedes: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    retention: str
    promotion_allowed: bool
    integrity: dict
    status: MemoryStatus
    recorded_at: str
    version: int


@dataclass(frozen=True)
class MemoryRetrieval:
    record: MemoryRecord
    usable_as_current_fact: bool
    reason: str


class MemoryStore:
    """Append-only version history for MEMORY-owned records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS memory_records(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              memory_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              memory_class TEXT NOT NULL,
              subject TEXT NOT NULL,
              scope TEXT NOT NULL,
              status TEXT NOT NULL,
              body TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              UNIQUE(memory_id, version)
            );
            CREATE INDEX IF NOT EXISTS idx_memory_scope_subject
              ON memory_records(scope, subject, sequence);
            """
        )

    @staticmethod
    def _require_text(value: str, field: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise MemoryRejected(f"{field} must be non-empty")

    @staticmethod
    def _encode(record: MemoryRecord) -> str:
        body = asdict(record)
        body["memory_class"] = record.memory_class.value
        body["freshness"] = record.freshness.value
        body["status"] = record.status.value
        body["supersedes"] = list(record.supersedes)
        body["conflicts_with"] = list(record.conflicts_with)
        return json.dumps(body, sort_keys=True)

    @staticmethod
    def _decode(body: str) -> MemoryRecord:
        data = json.loads(body)
        data["memory_class"] = MemoryClass(data["memory_class"])
        data["freshness"] = MemoryFreshness(data["freshness"])
        data["status"] = MemoryStatus(data["status"])
        data["supersedes"] = tuple(data["supersedes"])
        data["conflicts_with"] = tuple(data["conflicts_with"])
        return MemoryRecord(**data)

    def store(
        self,
        *,
        memory_class: MemoryClass,
        subject: str,
        scope: str,
        content: object,
        source_owner: str,
        source_ref: str,
        authority_ref: str | None,
        sensitivity: str,
        confidence: str,
        freshness: MemoryFreshness,
        retention: str,
        integrity: dict,
        effective_at: str | None = None,
        supersedes: tuple[str, ...] = (),
        conflicts_with: tuple[str, ...] = (),
        promotion_allowed: bool = False,
        status: MemoryStatus = MemoryStatus.ACTIVE,
        memory_id: str | None = None,
    ) -> MemoryRecord:
        for value, field in ((subject, "subject"), (scope, "scope"), (source_owner, "source_owner"),
                             (source_ref, "source_ref"), (sensitivity, "sensitivity"),
                             (confidence, "confidence"), (retention, "retention")):
            self._require_text(value, field)
        if not isinstance(integrity, dict) or not integrity:
            raise MemoryRejected("integrity must be a non-empty record")
        if MemoryClass(memory_class) is MemoryClass.WORKING and retention.upper() in {"FOREVER", "PERMANENT"}:
            raise MemoryRejected("WORKING_MEMORY must expire by policy")
        record = MemoryRecord(
            memory_id=memory_id or f"memory:{uuid.uuid4()}",
            memory_class=MemoryClass(memory_class), subject=subject, scope=scope, content=content,
            source_owner=source_owner, source_ref=source_ref, authority_ref=authority_ref,
            sensitivity=sensitivity, confidence=confidence, effective_at=effective_at,
            freshness=MemoryFreshness(freshness), supersedes=tuple(supersedes),
            conflicts_with=tuple(conflicts_with), retention=retention,
            promotion_allowed=promotion_allowed, integrity=dict(integrity), status=MemoryStatus(status),
            recorded_at=utc_now(), version=1,
        )
        self._validate_links(record)
        self._insert(record)
        return record

    def _validate_links(self, record: MemoryRecord) -> None:
        if record.memory_id in record.supersedes or record.memory_id in record.conflicts_with:
            raise MemoryRejected("memory record cannot link to itself")
        for ref in (*record.supersedes, *record.conflicts_with):
            self.latest(ref)

    def _insert(self, record: MemoryRecord) -> None:
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO memory_records(memory_id,version,memory_class,subject,scope,status,body,recorded_at) VALUES (?,?,?,?,?,?,?,?)",
                    (record.memory_id, record.version, record.memory_class.value, record.subject,
                     record.scope, record.status.value, self._encode(record), record.recorded_at),
                )
        except sqlite3.IntegrityError as exc:
            raise MemoryRejected("Memory records are immutable per version") from exc

    def latest(self, memory_id: str) -> MemoryRecord:
        row = self.connection.execute(
            "SELECT body FROM memory_records WHERE memory_id=? ORDER BY version DESC LIMIT 1",
            (memory_id,),
        ).fetchone()
        if row is None:
            raise MemoryRejected(f"unknown memory: {memory_id}")
        return self._decode(row["body"])

    def transition(self, memory_id: str, status: MemoryStatus, *, conflicts_with: tuple[str, ...] = ()) -> MemoryRecord:
        prior = self.latest(memory_id)
        if prior.status in {MemoryStatus.DELETED, MemoryStatus.EXPIRED}:
            raise MemoryRejected(f"terminal memory status {prior.status} cannot transition")
        for ref in conflicts_with:
            self.latest(ref)
        next_record = MemoryRecord(
            **{**asdict(prior),
               "memory_class": prior.memory_class,
               "freshness": prior.freshness,
               "status": MemoryStatus(status),
               "supersedes": prior.supersedes,
               "conflicts_with": tuple(dict.fromkeys((*prior.conflicts_with, *conflicts_with))),
               "integrity": dict(prior.integrity),
               "recorded_at": utc_now(), "version": prior.version + 1}
        )
        self._insert(next_record)
        return next_record

    def retrieve(self, *, scope: str, subject: str | None = None, include_inactive: bool = False) -> tuple[MemoryRetrieval, ...]:
        self._require_text(scope, "scope")
        params: list[object] = [scope]
        where = "scope=?"
        if subject is not None:
            where += " AND subject=?"
            params.append(subject)
        rows = self.connection.execute(
            f"SELECT m.body FROM memory_records m JOIN (SELECT memory_id, MAX(version) v FROM memory_records GROUP BY memory_id) latest ON latest.memory_id=m.memory_id AND latest.v=m.version WHERE m.{where} ORDER BY m.sequence DESC",
            tuple(params),
        ).fetchall()
        out = []
        for row in rows:
            record = self._decode(row["body"])
            if not include_inactive and record.status is not MemoryStatus.ACTIVE:
                continue
            current = (
                record.status is MemoryStatus.ACTIVE
                and record.freshness is MemoryFreshness.CURRENT
                and not record.conflicts_with
            )
            reason = "stored memory is supporting context, not current reality"
            if record.status is not MemoryStatus.ACTIVE:
                reason = f"memory status is {record.status.value}"
            elif record.conflicts_with:
                reason = "memory has unresolved conflict links"
            elif record.freshness is not MemoryFreshness.CURRENT:
                reason = f"memory freshness is {record.freshness.value}"
            elif current:
                reason = "memory is current-looking but still requires source/reality verification when material"
            out.append(MemoryRetrieval(record=record, usable_as_current_fact=False, reason=reason))
        return tuple(out)
