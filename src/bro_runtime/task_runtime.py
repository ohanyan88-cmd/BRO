"""Durable, evidence-governed Task lifecycle owned by NERVOUS SYSTEM.

The module deliberately owns coordination state only. MIND supplies decisions,
HANDS supplies action results, IMMUNE SYSTEM supplies authority/evidence, and
FEET supplies navigation checkpoints. Their records remain references here.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TaskState(StrEnum):
    RECEIVED = "RECEIVED"
    INTERPRETING = "INTERPRETING"
    READY = "READY"
    PLANNING = "PLANNING"
    AUTHORIZING = "AUTHORIZING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED})
PRIMARY_NEXT = {
    TaskState.RECEIVED: {TaskState.INTERPRETING},
    TaskState.INTERPRETING: {TaskState.READY},
    TaskState.READY: {TaskState.PLANNING},
    TaskState.PLANNING: {TaskState.AUTHORIZING},
    TaskState.AUTHORIZING: {TaskState.EXECUTING},
    TaskState.EXECUTING: {TaskState.VERIFYING, TaskState.PLANNING},
    TaskState.VERIFYING: {TaskState.COMPLETED, TaskState.EXECUTING, TaskState.PLANNING},
}
CONTROL_FROM = {
    TaskState.BLOCKED: {TaskState.INTERPRETING, TaskState.READY, TaskState.PLANNING, TaskState.AUTHORIZING, TaskState.EXECUTING, TaskState.VERIFYING, TaskState.FAILED, TaskState.CANCELLED},
    TaskState.PAUSED: {TaskState.INTERPRETING, TaskState.READY, TaskState.PLANNING, TaskState.AUTHORIZING, TaskState.EXECUTING, TaskState.VERIFYING, TaskState.CANCELLED},
    TaskState.RECOVERING: {TaskState.EXECUTING, TaskState.VERIFYING, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED},
}


class RuntimeErrorBase(Exception):
    """Base class for explicit runtime rejections."""


class InvalidTransition(RuntimeErrorBase):
    pass


class ConcurrencyConflict(RuntimeErrorBase):
    pass


class TaskNotFound(RuntimeErrorBase):
    pass


@dataclass(frozen=True)
class CompletionEvidence:
    outcome_exists: bool
    mandatory_scope_satisfied: bool
    effects_reconciled: bool
    artifacts_usable: bool
    criteria_evidence_refs: tuple[str, ...]
    checks_passed: bool
    no_invalidating_blocker: bool
    exclusions_explicit: bool
    communication_truthful: bool

    def failures(self) -> list[str]:
        checks = {
            "outcome does not exist": self.outcome_exists,
            "mandatory scope is not satisfied": self.mandatory_scope_satisfied,
            "effects are not reconciled": self.effects_reconciled,
            "artifacts are not usable": self.artifacts_usable,
            "completion criteria lack Evidence": bool(self.criteria_evidence_refs),
            "required checks did not pass": self.checks_passed,
            "an invalidating blocker remains": self.no_invalidating_blocker,
            "partial or excluded scope is not explicit": self.exclusions_explicit,
            "communication does not reflect actual state": self.communication_truthful,
        }
        return [message for message, passed in checks.items() if not passed]


@dataclass(frozen=True)
class RecoveryAssessment:
    integrity_valid: bool
    authority_valid: bool
    external_state_inspected: bool
    effect_state: str
    context_current: bool
    approval_current: bool
    evidence_refs: tuple[str, ...] = ()
    decision_ref: str | None = None

    def next_state(self) -> TaskState:
        if not self.integrity_valid:
            return TaskState.FAILED
        if not self.external_state_inspected or self.effect_state == "UNKNOWN":
            return TaskState.BLOCKED
        if not self.authority_valid or not self.context_current or not self.approval_current:
            return TaskState.BLOCKED
        if self.effect_state == "CONFIRMED":
            return TaskState.VERIFYING
        if self.effect_state in {"NONE", "RECONCILED"}:
            return TaskState.EXECUTING
        return TaskState.BLOCKED


class SQLiteTaskStore:
    """SQLite/WAL adapter with atomic state + append-only event commits."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                goal_ref TEXT NOT NULL,
                state TEXT NOT NULL,
                prior_active_state TEXT,
                resume_checkpoint_ref TEXT,
                evidence_refs TEXT NOT NULL DEFAULT '[]',
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                termination_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS runtime_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL REFERENCES tasks(task_id),
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                reason TEXT NOT NULL,
                prior_state TEXT,
                new_state TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                correlation_ref TEXT NOT NULL,
                causal_ref TEXT,
                payload TEXT NOT NULL,
                schema_version TEXT NOT NULL
            );
            """
        )

    def fetch_task(self, task_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        task = dict(row)
        task["evidence_refs"] = json.loads(task["evidence_refs"])
        return task

    def events(self, task_id: str) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM runtime_events WHERE task_id = ? ORDER BY sequence", (task_id,)).fetchall()
        return [dict(row) for row in rows]


class TaskRuntime:
    def __init__(self, store: SQLiteTaskStore) -> None:
        self.store = store

    def create_task(self, task_id: str, goal_ref: str, actor: str, reason: str, correlation_ref: str | None = None) -> dict:
        now = utc_now()
        correlation = correlation_ref or task_id
        with self.store.connection:
            self.store.connection.execute(
                "INSERT INTO tasks(task_id, goal_ref, state, revision, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?)",
                (task_id, goal_ref, TaskState.RECEIVED, now, now),
            )
            self._append_event(task_id, "task.received", actor, reason, None, TaskState.RECEIVED, correlation, None, {})
        return self.store.fetch_task(task_id)

    def transition(
        self,
        task_id: str,
        target: TaskState,
        actor: str,
        reason: str,
        expected_revision: int,
        *,
        correlation_ref: str | None = None,
        causal_ref: str | None = None,
        resume_checkpoint_ref: str | None = None,
        completion: CompletionEvidence | None = None,
        evidence_refs: Iterable[str] = (),
        payload: dict | None = None,
    ) -> dict:
        task = self.store.fetch_task(task_id)
        source = TaskState(task["state"])
        if task["revision"] != expected_revision:
            raise ConcurrencyConflict(f"expected revision {expected_revision}, found {task['revision']}")
        self._guard_transition(source, target, task, resume_checkpoint_ref)
        refs = tuple(dict.fromkeys((*task["evidence_refs"], *evidence_refs)))
        if target is TaskState.COMPLETED:
            if completion is None:
                raise InvalidTransition("COMPLETED requires an explicit evidence assessment")
            failures = completion.failures()
            if failures:
                raise InvalidTransition("completion gate failed: " + "; ".join(failures))
            refs = tuple(dict.fromkeys((*refs, *completion.criteria_evidence_refs)))

        now = utc_now()
        prior_active = task["prior_active_state"]
        if target in {TaskState.BLOCKED, TaskState.PAUSED}:
            prior_active = source.value
        elif source in {TaskState.BLOCKED, TaskState.PAUSED}:
            prior_active = None
        termination = reason if target in TERMINAL_STATES else None
        with self.store.connection:
            cursor = self.store.connection.execute(
                """UPDATE tasks SET state = ?, prior_active_state = ?, resume_checkpoint_ref = ?,
                   evidence_refs = ?, revision = revision + 1, updated_at = ?, termination_reason = ?
                   WHERE task_id = ? AND revision = ?""",
                (target, prior_active, resume_checkpoint_ref or task["resume_checkpoint_ref"], json.dumps(refs), now, termination, task_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict("task changed during transition")
            self._append_event(task_id, f"task.{target.value.lower()}", actor, reason, source, target, correlation_ref or task_id, causal_ref, payload or {})
        return self.store.fetch_task(task_id)

    def recover(self, task_id: str, assessment: RecoveryAssessment, actor: str, reason: str, expected_revision: int) -> dict:
        task = self.store.fetch_task(task_id)
        source = TaskState(task["state"])
        if source in TERMINAL_STATES:
            raise InvalidTransition("terminal Tasks cannot recover in place")
        recovering = self.transition(task_id, TaskState.RECOVERING, actor, reason, expected_revision, payload={"command_replayed": False})
        target = assessment.next_state()
        return self.transition(
            task_id,
            target,
            actor,
            "recovery assessment reconciled durable and external state",
            recovering["revision"],
            evidence_refs=assessment.evidence_refs,
            payload={"command_replayed": False, "effect_state": assessment.effect_state, "decision_ref": assessment.decision_ref},
        )

    @staticmethod
    def _guard_transition(source: TaskState, target: TaskState, task: dict, checkpoint: str | None) -> None:
        if source in TERMINAL_STATES:
            raise InvalidTransition(f"{source} is terminal")
        if target is TaskState.RECOVERING:
            return
        allowed = set(PRIMARY_NEXT.get(source, set())) | set(CONTROL_FROM.get(source, set()))
        if source not in {TaskState.BLOCKED, TaskState.PAUSED, TaskState.RECOVERING}:
            allowed |= {TaskState.BLOCKED, TaskState.PAUSED, TaskState.FAILED, TaskState.CANCELLED}
        if target not in allowed:
            raise InvalidTransition(f"invalid transition {source} -> {target}")
        if source in {TaskState.BLOCKED, TaskState.PAUSED} and target.value != task["prior_active_state"] and target not in {TaskState.CANCELLED, TaskState.FAILED}:
            raise InvalidTransition("control state may only resume its recorded active path")
        if target is TaskState.PAUSED and not (checkpoint or task["resume_checkpoint_ref"]):
            raise InvalidTransition("PAUSED requires a resume checkpoint")

    def _append_event(self, task_id: str, event_type: str, actor: str, reason: str, prior: TaskState | None, new: TaskState, correlation: str, causal: str | None, payload: dict) -> None:
        self.store.connection.execute(
            """INSERT INTO runtime_events(event_id, task_id, event_type, actor, reason, prior_state,
               new_state, occurred_at, correlation_ref, causal_ref, payload, schema_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '0.1.0')""",
            (str(uuid.uuid4()), task_id, event_type, actor, reason, prior.value if prior else None, new.value, utc_now(), correlation, causal, json.dumps(payload, sort_keys=True)),
        )
