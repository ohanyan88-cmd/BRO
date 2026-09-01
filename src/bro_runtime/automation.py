"""Durable automation trigger and dispatch control owned by NERVOUS SYSTEM.

Automation decides *when* BRO should receive work, never whether an effect is
authorized. Due occurrences are durable, carry deterministic canonical Task
references, and are reconciled into the normal BRO Task path before any governed
execution begins.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable

from .task_runtime import TaskNotFound, TaskRuntime, utc_now


class AutomationRejected(ValueError):
    pass


class AutomationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class MisfirePolicy(StrEnum):
    COALESCE = "COALESCE"
    CATCH_UP = "CATCH_UP"


class OccurrenceState(StrEnum):
    CLAIMED = "CLAIMED"
    TASK_RESERVED = "TASK_RESERVED"
    TASK_CREATED = "TASK_CREATED"


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AutomationRejected("automation timestamps must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise AutomationRejected("automation timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _deterministic_task_ref(automation_ref: str, due_at: str) -> str:
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f"bro://automation/{automation_ref}/{due_at}")
    return f"task:automation:{identity}"


@dataclass(frozen=True)
class AutomationDefinition:
    automation_id: str
    project_boundary: str
    desired_outcome: str
    schedule_kind: str
    interval_seconds: int
    next_due_at: str
    misfire_policy: MisfirePolicy
    max_catch_up: int
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
    """Durably claims interval occurrences and reserves canonical BRO Task refs."""

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
                updated_at TEXT NOT NULL,
                misfire_policy TEXT NOT NULL DEFAULT 'COALESCE',
                max_catch_up INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS automation_occurrences(
                occurrence_id TEXT PRIMARY KEY,
                automation_ref TEXT NOT NULL REFERENCES automations(automation_id),
                due_at TEXT NOT NULL,
                state TEXT NOT NULL,
                task_ref TEXT,
                claimed_at TEXT NOT NULL,
                UNIQUE(automation_ref, due_at),
                UNIQUE(task_ref)
            );
            """
        )
        self._migrate()

    def _migrate(self) -> None:
        present = {row["name"] for row in self.connection.execute("PRAGMA table_info(automations)").fetchall()}
        with self.connection:
            if "misfire_policy" not in present:
                self.connection.execute("ALTER TABLE automations ADD COLUMN misfire_policy TEXT NOT NULL DEFAULT 'COALESCE'")
            if "max_catch_up" not in present:
                self.connection.execute("ALTER TABLE automations ADD COLUMN max_catch_up INTEGER NOT NULL DEFAULT 1")
            self.connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS automation_occurrence_task_ref ON automation_occurrences(task_ref) WHERE task_ref IS NOT NULL")

    def create_interval(
        self,
        *,
        automation_id: str,
        project_boundary: str,
        desired_outcome: str,
        interval_seconds: int,
        first_due_at: str,
        misfire_policy: MisfirePolicy = MisfirePolicy.COALESCE,
        max_catch_up: int = 1,
    ) -> AutomationDefinition:
        if not automation_id or not project_boundary or not desired_outcome:
            raise AutomationRejected("automation identity, boundary, and outcome are required")
        if interval_seconds < 1:
            raise AutomationRejected("interval_seconds must be positive")
        if max_catch_up < 1:
            raise AutomationRejected("max_catch_up must be positive")
        try:
            policy = MisfirePolicy(misfire_policy)
        except ValueError as exc:
            raise AutomationRejected("invalid misfire policy") from exc
        _parse_utc(first_due_at)
        now = utc_now()
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO automations(automation_id,project_boundary,desired_outcome,schedule_kind,interval_seconds,next_due_at,status,revision,created_at,updated_at,misfire_policy,max_catch_up) VALUES (?,?,?,?,?,?,'ACTIVE',1,?,?,?,?)",
                    (automation_id, project_boundary, desired_outcome, "INTERVAL", interval_seconds, first_due_at, now, now, policy, max_catch_up),
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
            row["interval_seconds"], row["next_due_at"], MisfirePolicy(row["misfire_policy"]), row["max_catch_up"],
            AutomationStatus(row["status"]), row["revision"],
        )

    def set_status(self, automation_id: str, status: AutomationStatus) -> AutomationDefinition:
        try:
            resolved = AutomationStatus(status)
        except ValueError as exc:
            raise AutomationRejected("invalid automation status") from exc
        now = utc_now()
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE automations SET status=?,revision=revision+1,updated_at=? WHERE automation_id=?",
                (resolved, now, automation_id),
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
            policy = MisfirePolicy(row["misfire_policy"])
            limit = row["max_catch_up"] if policy is MisfirePolicy.CATCH_UP else 1
            due_times: list[datetime] = []
            cursor_due = due
            while cursor_due <= instant and len(due_times) < limit:
                due_times.append(cursor_due)
                cursor_due = datetime.fromtimestamp(cursor_due.timestamp() + row["interval_seconds"], timezone.utc)
            if policy is MisfirePolicy.COALESCE:
                elapsed = int((instant - due).total_seconds() // row["interval_seconds"])
                cursor_due = datetime.fromtimestamp(due.timestamp() + ((elapsed + 1) * row["interval_seconds"]), timezone.utc)
            next_due_at = _format_utc(cursor_due)
            new_occurrences: list[AutomationOccurrence] = []
            try:
                with self.connection:
                    for occurrence_due in due_times:
                        due_at = _format_utc(occurrence_due)
                        occurrence_id = f"occurrence:{uuid.uuid4()}"
                        task_ref = _deterministic_task_ref(row["automation_id"], due_at)
                        self.connection.execute(
                            "INSERT INTO automation_occurrences VALUES (?,?,?,?,?,?)",
                            (occurrence_id, row["automation_id"], due_at, OccurrenceState.TASK_RESERVED, task_ref, utc_now()),
                        )
                        new_occurrences.append(AutomationOccurrence(occurrence_id, row["automation_id"], due_at, OccurrenceState.TASK_RESERVED, task_ref))
                    update = self.connection.execute(
                        "UPDATE automations SET next_due_at=?,revision=revision+1,updated_at=? WHERE automation_id=? AND next_due_at=? AND status='ACTIVE'",
                        (next_due_at, utc_now(), row["automation_id"], row["next_due_at"]),
                    )
                    if update.rowcount != 1:
                        raise AutomationRejected("automation changed while occurrence was being claimed")
            except sqlite3.IntegrityError:
                continue
            claimed.extend(new_occurrences)
        return tuple(claimed)

    def mark_task_created(self, occurrence_id: str, task_ref: str) -> AutomationOccurrence:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE automation_occurrences SET state=? WHERE occurrence_id=? AND task_ref=? AND state IN (?,?)",
                (OccurrenceState.TASK_CREATED, occurrence_id, task_ref, OccurrenceState.TASK_RESERVED, OccurrenceState.CLAIMED),
            )
            if cursor.rowcount != 1:
                row = self.connection.execute("SELECT * FROM automation_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
                if row is None or row["task_ref"] != task_ref or row["state"] != OccurrenceState.TASK_CREATED:
                    raise AutomationRejected("occurrence Task reservation does not match")
        return self.fetch_occurrence(occurrence_id)

    def fetch_occurrence(self, occurrence_id: str) -> AutomationOccurrence:
        row = self.connection.execute("SELECT * FROM automation_occurrences WHERE occurrence_id=?", (occurrence_id,)).fetchone()
        if row is None:
            raise AutomationRejected("occurrence does not exist")
        return AutomationOccurrence(row["occurrence_id"], row["automation_ref"], row["due_at"], OccurrenceState(row["state"]), row["task_ref"])

    def pending_occurrences(self) -> tuple[AutomationOccurrence, ...]:
        rows = self.connection.execute(
            "SELECT * FROM automation_occurrences WHERE state IN ('CLAIMED','TASK_RESERVED') ORDER BY due_at,occurrence_id"
        ).fetchall()
        return tuple(AutomationOccurrence(r["occurrence_id"], r["automation_ref"], r["due_at"], OccurrenceState(r["state"]), r["task_ref"]) for r in rows)

    def materialize_task(
        self,
        occurrence_id: str,
        task_factory: Callable[[AutomationDefinition, AutomationOccurrence], str],
    ) -> AutomationOccurrence:
        occurrence = self.fetch_occurrence(occurrence_id)
        if occurrence.state is OccurrenceState.TASK_CREATED:
            return occurrence
        definition = self.fetch(occurrence.automation_ref)
        expected_ref = occurrence.task_ref or _deterministic_task_ref(occurrence.automation_ref, occurrence.due_at)
        if occurrence.task_ref is None:
            with self.connection:
                cursor = self.connection.execute(
                    "UPDATE automation_occurrences SET state=?,task_ref=? WHERE occurrence_id=? AND task_ref IS NULL",
                    (OccurrenceState.TASK_RESERVED, expected_ref, occurrence_id),
                )
                if cursor.rowcount != 1:
                    occurrence = self.fetch_occurrence(occurrence_id)
                    expected_ref = occurrence.task_ref
            occurrence = self.fetch_occurrence(occurrence_id)
        task_ref = task_factory(definition, occurrence)
        if task_ref != expected_ref:
            raise AutomationRejected("task factory must materialize the reserved canonical Task reference")
        return self.mark_task_created(occurrence_id, task_ref)

    def occurrences(self, automation_id: str) -> tuple[AutomationOccurrence, ...]:
        rows = self.connection.execute(
            "SELECT * FROM automation_occurrences WHERE automation_ref=? ORDER BY due_at,occurrence_id", (automation_id,)
        ).fetchall()
        return tuple(AutomationOccurrence(r["occurrence_id"], r["automation_ref"], r["due_at"], OccurrenceState(r["state"]), r["task_ref"]) for r in rows)


class AutomationDispatcher:
    """NERVOUS SYSTEM bridge from durable trigger occurrence to canonical Task."""

    def __init__(self, automation: AutomationRuntime, tasks: TaskRuntime) -> None:
        self.automation = automation
        self.tasks = tasks

    def _ensure_task(self, definition: AutomationDefinition, occurrence: AutomationOccurrence) -> str:
        if not occurrence.task_ref:
            raise AutomationRejected("dispatcher requires a reserved Task reference")
        try:
            task = self.tasks.store.fetch_task(occurrence.task_ref)
        except TaskNotFound:
            task = self.tasks.create_task(
                occurrence.task_ref,
                f"automation-goal:{definition.automation_id}",
                "NERVOUS_SYSTEM",
                "automation occurrence became canonical work",
                correlation_ref=occurrence.occurrence_id,
            )
        if task["goal_ref"] != f"automation-goal:{definition.automation_id}":
            raise AutomationRejected("reserved Task reference resolves to unrelated canonical work")
        return occurrence.task_ref

    def reconcile_pending(self) -> tuple[AutomationOccurrence, ...]:
        return tuple(self.automation.materialize_task(item.occurrence_id, self._ensure_task) for item in self.automation.pending_occurrences())

    def tick(self, *, now: str) -> tuple[AutomationOccurrence, ...]:
        self.reconcile_pending()
        claimed = self.automation.claim_due(now=now)
        return tuple(self.automation.materialize_task(item.occurrence_id, self._ensure_task) for item in claimed)

    def run(self, *, now: Callable[[], str] = utc_now, sleep: Callable[[float], None] = time.sleep, poll_seconds: float = 1.0, should_stop: Callable[[], bool] = lambda: False) -> None:
        if poll_seconds <= 0:
            raise AutomationRejected("poll_seconds must be positive")
        while not should_stop():
            self.tick(now=now())
            sleep(poll_seconds)
