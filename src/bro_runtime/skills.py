"""SKILLS & KNOWLEDGE capability registry and deterministic discovery.

Capability describes what BRO can do; it never grants authority to do it.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum

from .task_runtime import utc_now


class CapabilityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
    RETIRED = "RETIRED"


class CapabilityKind(StrEnum):
    SKILL = "SKILL"
    KNOWLEDGE = "KNOWLEDGE"
    TOOL_ADAPTER = "TOOL_ADAPTER"
    SPECIALIST = "SPECIALIST"


class CapabilityRejected(ValueError):
    pass


@dataclass(frozen=True)
class Capability:
    capability_id: str
    version: int
    kind: CapabilityKind
    name: str
    description: str
    operations: tuple[str, ...]
    domains: tuple[str, ...]
    input_contract_ref: str | None
    output_contract_ref: str | None
    dependency_refs: tuple[str, ...]
    authority_requirements: tuple[str, ...]
    evidence_capabilities: tuple[str, ...]
    provider_ref: str | None
    health_ref: str | None
    status: CapabilityStatus
    recorded_at: str


@dataclass(frozen=True)
class CapabilityMatch:
    capability: Capability
    matched_operations: tuple[str, ...]
    matched_domains: tuple[str, ...]


class CapabilityRegistry:
    """Append-only capability registry. Discovery is descriptive, not authorizing."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS capabilities(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              capability_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              status TEXT NOT NULL,
              body TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              UNIQUE(capability_id, version));
            """
        )

    @staticmethod
    def _encode(record: Capability) -> str:
        body = asdict(record)
        body["kind"] = record.kind.value
        body["status"] = record.status.value
        for key in ("operations", "domains", "dependency_refs", "authority_requirements", "evidence_capabilities"):
            body[key] = list(body[key])
        return json.dumps(body, sort_keys=True)

    @staticmethod
    def _decode(body: str) -> Capability:
        data = json.loads(body)
        data["kind"] = CapabilityKind(data["kind"])
        data["status"] = CapabilityStatus(data["status"])
        for key in ("operations", "domains", "dependency_refs", "authority_requirements", "evidence_capabilities"):
            data[key] = tuple(data[key])
        return Capability(**data)

    def register(self, record: Capability) -> Capability:
        if not record.capability_id.strip() or not record.name.strip():
            raise CapabilityRejected("capability_id and name are required")
        if record.version < 1:
            raise CapabilityRejected("capability version must be positive")
        if not record.operations and record.kind is not CapabilityKind.KNOWLEDGE:
            raise CapabilityRejected("executable capability requires operations")
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO capabilities(capability_id,version,status,body,recorded_at) VALUES (?,?,?,?,?)",
                    (record.capability_id, record.version, record.status.value, self._encode(record), record.recorded_at),
                )
        except sqlite3.IntegrityError as exc:
            raise CapabilityRejected("capability version is immutable") from exc
        return record

    def latest(self, capability_id: str) -> Capability:
        row = self.connection.execute(
            "SELECT body FROM capabilities WHERE capability_id=? ORDER BY version DESC LIMIT 1", (capability_id,)
        ).fetchone()
        if row is None:
            raise CapabilityRejected(f"unknown capability: {capability_id}")
        return self._decode(row["body"])

    def discover(self, *, operations: tuple[str, ...] = (), domains: tuple[str, ...] = ()) -> tuple[CapabilityMatch, ...]:
        rows = self.connection.execute(
            """SELECT c.body FROM capabilities c
               JOIN (SELECT capability_id, MAX(version) version FROM capabilities GROUP BY capability_id) latest
                 ON latest.capability_id=c.capability_id AND latest.version=c.version
               WHERE c.status IN ('ACTIVE','DEGRADED') ORDER BY c.capability_id"""
        ).fetchall()
        wanted_ops, wanted_domains = set(operations), set(domains)
        matches = []
        for row in rows:
            capability = self._decode(row["body"])
            matched_ops = tuple(sorted(wanted_ops.intersection(capability.operations)))
            matched_domains = tuple(sorted(wanted_domains.intersection(capability.domains)))
            if wanted_ops and not matched_ops:
                continue
            if wanted_domains and not matched_domains:
                continue
            matches.append(CapabilityMatch(capability, matched_ops, matched_domains))
        return tuple(matches)

    def next_version(self, capability_id: str, *, status: CapabilityStatus | None = None, **changes) -> Capability:
        prior = self.latest(capability_id)
        body = asdict(prior)
        body.update(changes)
        body["kind"] = changes.get("kind", prior.kind)
        body["status"] = status or changes.get("status", prior.status)
        body["version"] = prior.version + 1
        body["recorded_at"] = utc_now()
        for key in ("operations", "domains", "dependency_refs", "authority_requirements", "evidence_capabilities"):
            body[key] = tuple(body[key])
        record = Capability(**body)
        return self.register(record)
