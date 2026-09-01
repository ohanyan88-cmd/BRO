"""Governed SELF + HEART continuity records and minimal activation envelope."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum

from .task_runtime import utc_now


class ContinuityStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"
    QUARANTINED = "QUARANTINED"


class ContinuityRejected(ValueError):
    pass


@dataclass(frozen=True)
class SelfRecord:
    self_id: str
    schema_version: str
    identity_version: int
    product_name: str
    identity_statement: str
    character_traits: tuple[str, ...]
    stable_values: tuple[str, ...]
    behavioral_invariants: tuple[str, ...]
    voice_baseline_ref: str
    visual_identity_ref: str | None
    continuity_policy_ref: str
    provider_independence: bool
    effective_from: str
    supersedes: str | None
    authority_record_ref: str
    integrity_digest: str
    status: ContinuityStatus


@dataclass(frozen=True)
class HeartRecord:
    heart_id: str
    schema_version: str
    heart_version: int
    relationship_scope: str
    stance_principles: tuple[str, ...]
    care_rules: tuple[str, ...]
    loyalty_rules: tuple[str, ...]
    honesty_rules: tuple[str, ...]
    disagreement_rules: tuple[str, ...]
    warmth_rules: tuple[str, ...]
    privacy_rules: tuple[str, ...]
    non_flattery_rules: tuple[str, ...]
    non_deception_rules: tuple[str, ...]
    long_horizon_commitments: tuple[str, ...]
    private_foundation_refs: tuple[str, ...]
    expression_constraints_ref: str
    effective_from: str
    supersedes: str | None
    authority_record_ref: str
    integrity_digest: str
    status: ContinuityStatus


@dataclass(frozen=True)
class ContinuityEnvelope:
    self_ref: str
    self_version: int
    heart_ref: str
    heart_version: int
    relationship_scope: str
    behavioral_invariants: tuple[str, ...]
    voice_baseline_ref: str
    privacy_labels: tuple[str, ...]
    prohibited_disclosures: tuple[str, ...]
    integrity_proofs: tuple[str, ...]


class ContinuityStore:
    """Append-only source store. MEMORY may retain refs but never owns these records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS self_records(
              self_id TEXT NOT NULL, identity_version INTEGER NOT NULL, status TEXT NOT NULL,
              body TEXT NOT NULL, recorded_at TEXT NOT NULL, UNIQUE(self_id, identity_version));
            CREATE TABLE IF NOT EXISTS heart_records(
              heart_id TEXT NOT NULL, heart_version INTEGER NOT NULL, relationship_scope TEXT NOT NULL,
              status TEXT NOT NULL, body TEXT NOT NULL, recorded_at TEXT NOT NULL,
              UNIQUE(heart_id, heart_version));
            """
        )

    @staticmethod
    def digest(payload: dict) -> str:
        body = dict(payload)
        body.pop("integrity_digest", None)
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @staticmethod
    def _encode(record) -> str:
        body = asdict(record)
        body["status"] = record.status.value
        return json.dumps(body, sort_keys=True)

    def record_self(self, record: SelfRecord) -> SelfRecord:
        if record.self_id != "BRO" or record.product_name != "BRO":
            raise ContinuityRejected("SELF identity and product name must remain BRO")
        if not record.provider_independence:
            raise ContinuityRejected("SELF must be provider-independent")
        if record.integrity_digest != self.digest(asdict(record)):
            raise ContinuityRejected("SELF integrity digest mismatch")
        with self.connection:
            self.connection.execute(
                "INSERT INTO self_records VALUES (?,?,?,?,?)",
                (record.self_id, record.identity_version, record.status.value, self._encode(record), utc_now()),
            )
        return record

    def record_heart(self, record: HeartRecord) -> HeartRecord:
        if not record.relationship_scope.strip():
            raise ContinuityRejected("HEART requires relationship_scope")
        if record.integrity_digest != self.digest(asdict(record)):
            raise ContinuityRejected("HEART integrity digest mismatch")
        with self.connection:
            self.connection.execute(
                "INSERT INTO heart_records VALUES (?,?,?,?,?,?)",
                (record.heart_id, record.heart_version, record.relationship_scope,
                 record.status.value, self._encode(record), utc_now()),
            )
        return record

    def _active(self, table: str, scope: str | None = None) -> dict:
        where = "status='ACTIVE'"
        args: tuple = ()
        if scope is not None:
            where += " AND relationship_scope=?"
            args = (scope,)
        rows = self.connection.execute(f"SELECT body FROM {table} WHERE {where}", args).fetchall()
        if len(rows) != 1:
            raise ContinuityRejected(f"expected exactly one active record in {table}, found {len(rows)}")
        return json.loads(rows[0]["body"])

    def activate(self, relationship_scope: str) -> ContinuityEnvelope:
        self_body = self._active("self_records")
        heart_body = self._active("heart_records", relationship_scope)
        if self_body["self_id"] != "BRO" or self_body["product_name"] != "BRO":
            raise ContinuityRejected("active SELF identity drift detected")
        # Deliberately derive constraints, never raw private foundation content.
        prohibited = tuple(dict.fromkeys((*heart_body["privacy_rules"], "do not disclose private foundation material")))
        return ContinuityEnvelope(
            self_ref=self_body["self_id"], self_version=self_body["identity_version"],
            heart_ref=heart_body["heart_id"], heart_version=heart_body["heart_version"],
            relationship_scope=relationship_scope,
            behavioral_invariants=tuple(self_body["behavioral_invariants"]),
            voice_baseline_ref=self_body["voice_baseline_ref"],
            privacy_labels=("RELATIONSHIP_PRIVATE",), prohibited_disclosures=prohibited,
            integrity_proofs=(self_body["integrity_digest"], heart_body["integrity_digest"]),
        )
