"""NERVOUS SYSTEM-owned durable automation trigger runtime.

Automation decides *when work should be considered*, never whether that work is
authorized. Trigger materialization produces durable, deduplicated invocations
that must still enter the canonical BRO Task -> IMMUNE -> HANDS -> Evidence path.
No trigger, condition, schedule, or event grants execution authority.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Iterable

from .task_runtime import utc_now


class AutomationRejected(ValueError):
    pass


class TriggerKind(StrEnum):
    EVENT = "EVENT"
    INTERVAL = "INTERVAL"


class AutomationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class InvocationState(StrEnum):
    PENDING = "PENDING"
    TASK_BOUND = "TASK_BOUND"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class AutomationDefinition:
    automation_id: str
    version: int
    name: str
    project_boundary: str
    desired_outcome: str
    operation: str
    domain: str
    authority_basis: str
    materiality: str
    risk_class: str
    expected_output: str
    verification_requirement: str
    success_conditions: tuple[str, ...]
    trigger_kind: TriggerKind
    trigger_spec: dict
    condition_spec: dict
    status: AutomationStatus = AutomationStatus.ACTIVE


@dataclass(frozen=True)
class AutomationInvocation:
    invocation_id: str
    automation_id: str
    automation_version: int
    trigger_kind: TriggerKind
    trigger_ref: str
    dedupe_key: str
    payload: dict
    state: InvocationState
    task_ref: str | None
    created_at: str


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomationRejected("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AutomationRejected("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _path(payload: object, dotted: str) -> object:
    current = payload
    for part in dotted.split("."):
        if not part or not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def condition_matches(spec: dict, payload: dict) -> bool:
    """Evaluate a deliberately small declarative condition language.

    Supported form: {"all": [{"path": "customer.status", "equals": "past_due"}]}
    Empty conditions match. Arbitrary code/expression evaluation is forbidden.
    """
    if not spec:
        return True
    if set(spec) != {"all"} or not isinstance(spec["all"], list):
        raise AutomationRejected("condition_spec supports only an 'all' predicate list")
    for predicate in spec["all"]:
        if not isinstance(predicate, dict) or set(predicate) != {"path", "equals"}:
            raise AutomationRejected("condition predicate requires exactly path and equals")
        path = predicate["path"]
        if not isinstance(path, str) or not path.strip():
            raise AutomationRejected("condition path must be a non-empty string")
        if _path(payload, path) != predicate["equals"]:
            return False
    return True


class AutomationRuntime:
    """Versioned automation registry plus idempotent trigger materialization."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS automation_definitions (
                automation_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (automation_id, version)
            );
            CREATE TABLE IF NOT EXISTS automation_invocations (
                invocation_id TEXT PRIMARY KEY,
                automation_id TEXT NOT NULL,
                automation_version INTEGER NOT NULL,
                trigger_kind TEXT NOT NULL,
                trigger_ref TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL,
                state TEXT NOT NULL,
                task_ref TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_automation_invocations_automation
                ON automation_invocations(automation_id, automation_version, created_at);
            """
        )

    def register(self, definition: AutomationDefinition, *, recorded_at: str | None = None) -> AutomationDefinition:
        self._validate(definition)
        body = json.dumps(asdict(definition), sort_keys=True)
        with self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO automation_definitions VALUES (?, ?, ?, ?, ?)",
                    (
                        definition.automation_id,
                        definition.version,
                        body,
                        definition.status,
                        recorded_at or utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise AutomationRejected("automation version is immutable") from exc
        return definition

    def latest(self, automation_id: str) -> AutomationDefinition:
        row = self.connection.execute(
            "SELECT * FROM automation_definitions WHERE automation_id=? ORDER BY version DESC LIMIT 1",
            (automation_id,),
        ).fetchone()
        if row is None:
            raise AutomationRejected("unknown automation")
        return self._definition(row)

    def set_status(self, automation_id: str, version: int, status: AutomationStatus) -> AutomationDefinition:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE automation_definitions SET status=? WHERE automation_id=? AND version=?",
                (status, automation_id, version),
            )
            if cursor.rowcount != 1:
                raise AutomationRejected("unknown automation version")
        return self.definition(automation_id, version)

    def definition(self, automation_id: str, version: int) -> AutomationDefinition:
        row = self.connection.execute(
            "SELECT * FROM automation_definitions WHERE automation_id=? AND version=?",
            (automation_id, version),
        ).fetchone()
        if row is None:
            raise AutomationRejected("unknown automation version")
        return self._definition(row)

    def ingest_event(
        self,
        *,
        topic: str,
        event_id: str,
        payload: dict,
        occurred_at: str | None = None,
    ) -> tuple[AutomationInvocation, ...]:
        if not topic.strip() or not event_id.strip():
            raise AutomationRejected("event topic and event_id are required")
        if not isinstance(payload, dict):
            raise AutomationRejected("event payload must be an object")
        moment = occurred_at or utc_now()
        _parse_iso(moment)
        invocations: list[AutomationInvocation] = []
        for definition in self._active(TriggerKind.EVENT):
            if definition.trigger_spec["topic"] != topic:
                continue
            if not condition_matches(definition.condition_spec, payload):
                continue
            invocation = self._materialize(
                definition,
                trigger_ref=f"event:{topic}:{event_id}",
                dedupe_source=f"event:{event_id}",
                payload={"topic": topic, "event_id": event_id, "occurred_at": moment, "data": payload},
                created_at=moment,
            )
            if invocation is not None:
                invocations.append(invocation)
        return tuple(invocations)

    def materialize_due(self, now: str | None = None) -> tuple[AutomationInvocation, ...]:
        moment_text = now or utc_now()
        moment = _parse_iso(moment_text)
        invocations: list[AutomationInvocation] = []
        for definition in self._active(TriggerKind.INTERVAL):
            spec = definition.trigger_spec
            anchor = _parse_iso(spec["anchor_at"])
            if moment < anchor:
                continue
            every = int(spec["every_seconds"])
            slot = int((moment - anchor).total_seconds()) // every
            slot_at = anchor.timestamp() + slot * every
            trigger_ref = f"interval:{definition.automation_id}:{definition.version}:{slot}"
            invocation = self._materialize(
                definition,
                trigger_ref=trigger_ref,
                dedupe_source=f"interval:{slot}",
                payload={
                    "scheduled_slot": slot,
                    "scheduled_at": datetime.fromtimestamp(slot_at, timezone.utc).isoformat().replace("+00:00", "Z"),
                    "materialized_at": moment_text,
                },
                created_at=moment_text,
            )
            if invocation is not None:
                invocations.append(invocation)
        return tuple(invocations)

    def pending(self, *, project_boundary: str | None = None) -> tuple[AutomationInvocation, ...]:
        if project_boundary is None:
            rows = self.connection.execute(
                "SELECT * FROM automation_invocations WHERE state=? ORDER BY created_at, invocation_id",
                (InvocationState.PENDING,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT i.* FROM automation_invocations i
                JOIN automation_definitions d
                  ON d.automation_id=i.automation_id AND d.version=i.automation_version
                WHERE i.state=? AND json_extract(d.body, '$.project_boundary')=?
                ORDER BY i.created_at, i.invocation_id
                """,
                (InvocationState.PENDING, project_boundary),
            ).fetchall()
        return tuple(self._invocation(row) for row in rows)

    def bind_task(self, invocation_id: str, task_ref: str) -> AutomationInvocation:
        if not task_ref.strip():
            raise AutomationRejected("task_ref is required")
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE automation_invocations
                   SET state=?, task_ref=?
                 WHERE invocation_id=? AND state=? AND task_ref IS NULL
                """,
                (InvocationState.TASK_BOUND, task_ref, invocation_id, InvocationState.PENDING),
            )
            if cursor.rowcount != 1:
                current = self.invocation(invocation_id)
                if current.state is InvocationState.TASK_BOUND and current.task_ref == task_ref:
                    return current
                raise AutomationRejected("automation invocation is already bound or unavailable")
        return self.invocation(invocation_id)

    def invocation(self, invocation_id: str) -> AutomationInvocation:
        row = self.connection.execute(
            "SELECT * FROM automation_invocations WHERE invocation_id=?", (invocation_id,)
        ).fetchone()
        if row is None:
            raise AutomationRejected("unknown automation invocation")
        return self._invocation(row)

    def _active(self, kind: TriggerKind) -> Iterable[AutomationDefinition]:
        rows = self.connection.execute(
            "SELECT * FROM automation_definitions WHERE status=? ORDER BY automation_id, version",
            (AutomationStatus.ACTIVE,),
        ).fetchall()
        latest: dict[str, AutomationDefinition] = {}
        for row in rows:
            definition = self._definition(row)
            prior = latest.get(definition.automation_id)
            if prior is None or definition.version > prior.version:
                latest[definition.automation_id] = definition
        return tuple(d for d in latest.values() if d.trigger_kind is kind)

    def _materialize(
        self,
        definition: AutomationDefinition,
        *,
        trigger_ref: str,
        dedupe_source: str,
        payload: dict,
        created_at: str,
    ) -> AutomationInvocation | None:
        canonical = f"{definition.automation_id}:{definition.version}:{dedupe_source}"
        dedupe_key = hashlib.sha256(canonical.encode()).hexdigest()
        invocation_id = f"automation-invocation:{uuid.uuid5(uuid.NAMESPACE_URL, canonical)}"
        with self.connection:
            try:
                self.connection.execute(
                    "INSERT INTO automation_invocations VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (
                        invocation_id,
                        definition.automation_id,
                        definition.version,
                        definition.trigger_kind,
                        trigger_ref,
                        dedupe_key,
                        json.dumps(payload, sort_keys=True),
                        InvocationState.PENDING,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError:
                return None
        return self.invocation(invocation_id)

    @staticmethod
    def _definition(row: sqlite3.Row) -> AutomationDefinition:
        body = json.loads(row["body"])
        body["trigger_kind"] = TriggerKind(body["trigger_kind"])
        body["status"] = AutomationStatus(row["status"])
        body["success_conditions"] = tuple(body["success_conditions"])
        return AutomationDefinition(**body)

    @staticmethod
    def _invocation(row: sqlite3.Row) -> AutomationInvocation:
        return AutomationInvocation(
            invocation_id=row["invocation_id"],
            automation_id=row["automation_id"],
            automation_version=row["automation_version"],
            trigger_kind=TriggerKind(row["trigger_kind"]),
            trigger_ref=row["trigger_ref"],
            dedupe_key=row["dedupe_key"],
            payload=json.loads(row["payload"]),
            state=InvocationState(row["state"]),
            task_ref=row["task_ref"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _validate(definition: AutomationDefinition) -> None:
        if not definition.automation_id.strip() or definition.version <= 0:
            raise AutomationRejected("automation_id and positive version are required")
        required = (
            definition.name,
            definition.project_boundary,
            definition.desired_outcome,
            definition.operation,
            definition.domain,
            definition.authority_basis,
            definition.materiality,
            definition.risk_class,
            definition.expected_output,
            definition.verification_requirement,
        )
        if any(not value.strip() for value in required) or not definition.success_conditions:
            raise AutomationRejected("automation execution contract fields are required")
        if definition.trigger_kind is TriggerKind.EVENT:
            if set(definition.trigger_spec) != {"topic"} or not str(definition.trigger_spec["topic"]).strip():
                raise AutomationRejected("EVENT trigger_spec requires exactly a non-empty topic")
        elif definition.trigger_kind is TriggerKind.INTERVAL:
            if set(definition.trigger_spec) != {"anchor_at", "every_seconds"}:
                raise AutomationRejected("INTERVAL trigger_spec requires exactly anchor_at and every_seconds")
            _parse_iso(str(definition.trigger_spec["anchor_at"]))
            try:
                every = int(definition.trigger_spec["every_seconds"])
            except (TypeError, ValueError) as exc:
                raise AutomationRejected("every_seconds must be an integer") from exc
            if every < 60:
                raise AutomationRejected("interval automation minimum cadence is 60 seconds")
        condition_matches(definition.condition_spec, {})
