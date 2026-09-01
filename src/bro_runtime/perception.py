"""Durable PERCEPTION runtime: Intent and Observation records only."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Freshness(StrEnum):
    CURRENT = "CURRENT"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class TrustState(StrEnum):
    CONFIRMED = "CONFIRMED"
    DERIVED = "DERIVED"
    UNVERIFIED = "UNVERIFIED"
    UNKNOWN = "UNKNOWN"
    CONFLICTED = "CONFLICTED"


class PerceptionRejected(ValueError):
    pass


@dataclass(frozen=True)
class Intent:
    intent_id: str
    content: object
    source: str
    received_at: str
    scope: str
    authority_ref: str | None = None
    sensitivity: str = "NORMAL"
    version: str = "0.1.0"


@dataclass(frozen=True)
class Observation:
    observation_id: str
    claim: object
    source: str
    provenance: dict
    observed_at: str
    freshness: Freshness
    trust_state: TrustState
    scope: str
    limitations: tuple[str, ...]
    raw_result_ref: str | None = None
    integrity: dict | None = None
    version: str = "0.1.0"


class PerceptionStore:
    """Append-only owner store for PERCEPTION primitives."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS perception_intents(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              intent_id TEXT NOT NULL UNIQUE,
              body TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS perception_observations(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,
              observation_id TEXT NOT NULL UNIQUE,
              body TEXT NOT NULL,
              recorded_at TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _require_ref(value: str, field: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise PerceptionRejected(f"{field} must be a non-empty reference")

    def record_intent(
        self,
        *,
        content: object,
        source: str,
        scope: str,
        authority_ref: str | None = None,
        sensitivity: str = "NORMAL",
        intent_id: str | None = None,
        received_at: str | None = None,
    ) -> Intent:
        self._require_ref(source, "source")
        self._require_ref(scope, "scope")
        record = Intent(
            intent_id=intent_id or f"intent:{uuid.uuid4()}",
            content=content,
            source=source,
            received_at=received_at or utc_now(),
            scope=scope,
            authority_ref=authority_ref,
            sensitivity=sensitivity,
        )
        with self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO perception_intents(intent_id,body,recorded_at) VALUES (?,?,?)",
                    (record.intent_id, json.dumps(asdict(record), sort_keys=True), utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise PerceptionRejected(f"Intent {record.intent_id} already exists") from exc
        return record

    def observe(
        self,
        *,
        claim: object,
        source: str,
        provenance: dict,
        freshness: Freshness,
        trust_state: TrustState,
        scope: str,
        limitations: tuple[str, ...] = (),
        raw_result_ref: str | None = None,
        integrity: dict | None = None,
        observation_id: str | None = None,
        observed_at: str | None = None,
    ) -> Observation:
        self._require_ref(source, "source")
        self._require_ref(scope, "scope")
        if not isinstance(provenance, dict) or not provenance:
            raise PerceptionRejected("provenance must be a non-empty record")
        record = Observation(
            observation_id=observation_id or f"observation:{uuid.uuid4()}",
            claim=claim,
            source=source,
            provenance=dict(provenance),
            observed_at=observed_at or utc_now(),
            freshness=Freshness(freshness),
            trust_state=TrustState(trust_state),
            scope=scope,
            limitations=tuple(limitations),
            raw_result_ref=raw_result_ref,
            integrity=dict(integrity) if integrity is not None else None,
        )
        body = asdict(record)
        body["freshness"] = record.freshness.value
        body["trust_state"] = record.trust_state.value
        body["limitations"] = list(record.limitations)
        with self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO perception_observations(observation_id,body,recorded_at) VALUES (?,?,?)",
                    (record.observation_id, json.dumps(body, sort_keys=True), utc_now()),
                )
            except sqlite3.IntegrityError as exc:
                raise PerceptionRejected(f"Observation {record.observation_id} already exists") from exc
        return record

    def intent(self, intent_id: str) -> Intent:
        row = self.connection.execute(
            "SELECT body FROM perception_intents WHERE intent_id=?", (intent_id,)
        ).fetchone()
        if row is None:
            raise PerceptionRejected(f"unknown Intent {intent_id}")
        return Intent(**json.loads(row["body"]))

    def observation(self, observation_id: str) -> Observation:
        row = self.connection.execute(
            "SELECT body FROM perception_observations WHERE observation_id=?", (observation_id,)
        ).fetchone()
        if row is None:
            raise PerceptionRejected(f"unknown Observation {observation_id}")
        body = json.loads(row["body"])
        body["freshness"] = Freshness(body["freshness"])
        body["trust_state"] = TrustState(body["trust_state"])
        body["limitations"] = tuple(body["limitations"])
        return Observation(**body)
