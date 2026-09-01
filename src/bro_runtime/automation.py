"""Durable automation trigger control owned by NERVOUS SYSTEM.

Automation decides *when* BRO should receive work, never whether an effect is
authorized. Each due occurrence is durably claimed once and becomes a canonical
Task through a caller-supplied task factory. Execution then follows the normal
BRO authority, HANDS, evidence, and completion path.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable

from .task_runtime import utc_now


class AutomationRejected(ValueError):
    pass


class AutomationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class OccurrenceState(StrEnum):
    CLAIMED = "CLAIMED"
    TASK_CREATED = "TASK_CREATED"


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomationRejected("automation timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AutomationRejected("automation timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class AutomationDefinition:
    automation_id: str
    project_boundary: str
    desired_outcome: str
    schedule_kind: str
    interval_seconds: int
    next_due_at: str
    status: AutomationStatus
    revision: int


@dataclass(frozen=True)
class AutomationOccurrence:
    occurrence_id: str
    automation_ref: str
    due_at: str
    state: OccurrenceState
    task_ref: str | None


class AutomationRuntime:
    """Durably claims interval occurrences and wakes canonical BRO Tasks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS automations(
                automation_id TEXT PRIMARY KEY,
                project_boundary TEXT NOT NULL,
                desired_outcome TEXT NOT NULL,
                schedule_kind TEXT NOT NULL,
                interval_seconds INTEGER NOT NULL,
                next_due_at TEXT NOT NULL,
                status TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS automation_occurrences(
                occurrence_id TEXT PRIMARY KEY,
                automation_ref TEXT NOT NULL REFERENCES automations(automation_id),
                due_at TEXT NOT NULL,
                state TEXT NOT NULL,
                task_ref TEXT,
                claimed_at TEXT NOT NULL,
                UNIQUE(automation_ref, due_at)
            );
            """
        )

    def create_interval(
        self,
        *,
        automation_id: str,
        project_boundary: str,
        desired_outcome: str,
        interval_seconds: int,
        first_due_at: str,
    ) -> AutomationDefinition:
        if not automation_id or not project_boundary or not desired_outcome:
            raise AutomationRejected("automation identity, boundary, and outcome are required")
        if interval_seconds < 1:
            raise AutomationRejected("interval_seconds must be positive")
        _parse_utc(first_due_at)
        now = utc_now()
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO automations VALUES (?,?,?,?,?,'ACTIVE',1,?,?)",
                    (automation_id, project_boundary, desired_outcome, "INTERVAL", interval_seconds, first_due_at, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise AutomationRejected("automation_id already exists") from exc
        return self.fetch(automation_id)

    def fetch(self, automation_id: str) -> AutomationDefinition:
        row = self.connection.execute("SELECT * FROM automations WHERE automation_id=?", (automation_id,)).fetchone()
        if row is None:
            raise AutomationRejected("automation does not exist")
        return AutomationDefinition(
            row["automation_id"], row["project_boundary"], row["desired_outcome"], row["schedule_kind"],
            row["interval_seconds"], row["next_due_at"], AutomationStatus(row["status"]), row["revision"],
        )

    def set_status(self, automation_id: str, status: AutomationStatus) -> AutomationDefinition:
        if status not in {AutomationStatus.ACTIVE, AutomationStatus.PAUSED, AutomationStatus.CANCELLED}:
            raise AutomationRejected("invalid automation status")
        now = utc_now()
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE automations SET status=?,revision=revision+1,updated_at=? WHERE automation_id=?",
                (status, now, automation_id),
            )
            if cursor.rowcount != 1:
                raise AutomationRejected("automation does not exist")
        return self.fetch(automation_id)

    def claim_due(self, *, now: str) -> tuple[AutomationOccurrence, ...]:
        instant = _parse_utc(now)
        rows = self.connection.execute(
            "SELECT * FROM automations WHERE status='ACTIVE' ORDER BY next_due_at,automation_id"
        ).fetchall()
        claimed: list[AutomationOccurrence] = []
        for row in rows:
            due = _parse_utc(row["next_due_at"])
            if due > instant:
                continue
            occurrence_id = f"occurrence:{uuid.uuid4()}"
            next_due = due.timestamp() + row["interval_seconds"]
            next_due_at = datetime.fromtimestamp(next_due, timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                with self.connection:
                    self.connection.execute(
                        "INSERT INTO automation_occurrences VALUES (?,?,?,?,NULL,?)",
                        (occurrence_id, row["automation_id"], row["next_due_at"], OccurrenceState.CLAIMED, utc_now()),
                    )
                    self.connection.execute(
                        "UPDATE automations SET next_due_at=?,revision=revision+1,updated_at=? WHERE automation_id=? AND next_due_at=? AND status='ACTIVE'",
                        (next_due_at, utc_now(), row["automation_id"], row["next_due_at"]),
                    )
            except sqlite3.IntegrityError:
                continue
            claimed.append(AutomationOccurrence(occurrence_id, row["automation_id"], row["next_due_at"], OccurrenceState.CLAIMED, None))
        return tuple(claimed)

    def materialize_task(
        self,
        occurrence_id: str,
        task_factory: Callable[[AutomationDefinition, AutomationOccurrence], str],
    ) -> AutomationOccurrence:
        row = self.connection.execute(
            "SELECT * FROM automation_occurrences WHERE occurrence_id=?", (occurrence_id,)
        ).fetchone()
        if row is None:
            raise AutomationRejected("occurrence does not exist")
        occurrence = AutomationOccurrence(row["occurrence_id"], row["automation_ref"], row["due_at"], OccurrenceState(row["state"]), row["task_ref"])
        if occurrence.task_ref:
            return occurrence
        definition = self.fetch(occurrence.automation_ref)
        task_ref = task_factory(definition, occurrence)
        if not task_ref:
            raise AutomationRejected("task factory returned no canonical Task reference")
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE automation_occurrences SET state=?,task_ref=? WHERE occurrence_id=? AND task_ref IS NULL",
                (OccurrenceState.TASK_CREATED, task_ref, occurrence_id),
            )
            if cursor.rowcount != 1:
                persisted = self.connection.execute(
                    "SELECT task_ref FROM automation_occurrences WHERE occurrence_id=?", (occurrence_id,)
                ).fetchone()
                return AutomationOccurrence(occurrence_id, occurrence.automation_ref, occurrence.due_at, OccurrenceState.TASK_CREATED, persisted["task_ref"])
        return AutomationOccurrence(occurrence_id, occurrence.automation_ref, occurrence.due_at, OccurrenceState.TASK_CREATED, task_ref)

    def occurrences(self, automation_id: str) -> tuple[AutomationOccurrence, ...]:
        rows = self.connection.execute(
            "SELECT * FROM automation_occurrences WHERE automation_ref=? ORDER BY due_at,occurrence_id", (automation_id,)
        ).fetchall()
        return tuple(
            AutomationOccurrence(r["occurrence_id"], r["automation_ref"], r["due_at"], OccurrenceState(r["state"]), r["task_ref"])
            for r in rows
        )
