"""Durable NERVOUS SYSTEM assignment coordination with fenced worker leases."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class AssignmentRejected(Exception):
    pass


class StaleWorkerResult(AssignmentRejected):
    pass


class AssignmentState(StrEnum):
    READY = "READY"
    LEASED = "LEASED"
    RECOVERING = "RECOVERING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class SpecialistAssignment:
    """Canonical Specialist Assignment — contracts/v0.1/specialist-assignment.schema.json.

    `allowed_tools` holds **adapter/tool identifiers** — the same namespace as
    `ActionRequest.adapter_id` and `AuthorityEnvelope.tool_boundary`. It is the
    delegated tool grant, never a list of targets: what may be touched lives in
    `target` and the envelope's `allowed_scope`. A tool grant is a capability
    boundary, and capability never grants authority on its own.
    """

    assignment_id: str
    task_ref: str
    step_ref: str
    project_boundary: str
    required_capability: str
    context_manifest_ref: str
    expected_output_contract: str
    authority_envelope_ref: str
    allowed_tools: tuple[str, ...]
    deadline: str | None
    budget: dict
    evidence_requirements: tuple[str, ...]


@dataclass(frozen=True)
class LeaseGrant:
    lease_id: str
    assignment_id: str
    worker_id: str
    fencing_token: int
    expires_at: str
    project_boundary: str
    context_manifest_ref: str
    authority_envelope_ref: str
    allowed_tools: tuple[str, ...]


class Supervisor:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS assignments (
              assignment_id TEXT PRIMARY KEY, task_ref TEXT NOT NULL, body TEXT NOT NULL,
              state TEXT NOT NULL, fencing_token INTEGER NOT NULL DEFAULT 0,
              revision INTEGER NOT NULL DEFAULT 1, result_ref TEXT
            );
            CREATE TABLE IF NOT EXISTS worker_leases (
              lease_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
              worker_id TEXT NOT NULL, fencing_token INTEGER NOT NULL, issued_at TEXT NOT NULL,
              heartbeat_at TEXT NOT NULL, expires_at TEXT NOT NULL, status TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_lease
              ON worker_leases(assignment_id) WHERE status='ACTIVE';
            CREATE TABLE IF NOT EXISTS assignment_results (
              result_id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES assignments(assignment_id),
              lease_id TEXT NOT NULL, fencing_token INTEGER NOT NULL, result_state TEXT NOT NULL,
              output_ref TEXT, evidence_refs TEXT NOT NULL, limitations TEXT NOT NULL,
              submitted_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orchestration_events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
              assignment_id TEXT NOT NULL, event_type TEXT NOT NULL, actor TEXT NOT NULL,
              occurred_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            """
        )

    def create_assignment(self, assignment: SpecialistAssignment, actor: str, now: str) -> dict:
        if not assignment.project_boundary or not assignment.context_manifest_ref or not assignment.authority_envelope_ref:
            raise AssignmentRejected("project, context, and authority boundaries are mandatory")
        if not assignment.allowed_tools:
            raise AssignmentRejected("an assignment must grant at least one adapter; an empty tool grant executes nothing")
        with self.connection:
            self.connection.execute(
                "INSERT INTO assignments(assignment_id,task_ref,body,state) VALUES (?,?,?,?)",
                (assignment.assignment_id, assignment.task_ref, json.dumps(asdict(assignment), sort_keys=True), AssignmentState.READY),
            )
            self._event(assignment.assignment_id, "assignment.ready", actor, now, {})
        return self.get_assignment(assignment.assignment_id)

    def claim(self, assignment_id: str, worker_id: str, now: str, lease_seconds: int = 30) -> LeaseGrant:
        if lease_seconds <= 0:
            raise AssignmentRejected("lease duration must be positive")
        moment = parse_time(now)
        with self.connection:
            row = self.connection.execute("SELECT * FROM assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
            if row is None or row["state"] not in {AssignmentState.READY, AssignmentState.RECOVERING}:
                raise AssignmentRejected("assignment is not claimable")
            active = self.connection.execute("SELECT 1 FROM worker_leases WHERE assignment_id=? AND status='ACTIVE'", (assignment_id,)).fetchone()
            if active:
                raise AssignmentRejected("assignment already has an active lease")
            token = row["fencing_token"] + 1
            cursor = self.connection.execute(
                "UPDATE assignments SET state=?, fencing_token=?, revision=revision+1 WHERE assignment_id=? AND revision=?",
                (AssignmentState.LEASED, token, assignment_id, row["revision"]),
            )
            if cursor.rowcount != 1:
                raise AssignmentRejected("assignment changed during claim")
            lease_id = str(uuid.uuid4())
            expires = format_time(moment + timedelta(seconds=lease_seconds))
            self.connection.execute("INSERT INTO worker_leases VALUES (?,?,?,?,?,?,?,?)", (lease_id, assignment_id, worker_id, token, now, now, expires, "ACTIVE"))
            self._event(assignment_id, "lease.claimed", worker_id, now, {"lease_id": lease_id, "fencing_token": token})
        body = json.loads(row["body"])
        return LeaseGrant(lease_id, assignment_id, worker_id, token, expires, body["project_boundary"], body["context_manifest_ref"], body["authority_envelope_ref"], tuple(body["allowed_tools"]))

    def heartbeat(self, grant: LeaseGrant, now: str, extend_seconds: int = 30) -> LeaseGrant:
        self._validate_active(grant, now)
        expires = format_time(parse_time(now) + timedelta(seconds=extend_seconds))
        with self.connection:
            self.connection.execute("UPDATE worker_leases SET heartbeat_at=?, expires_at=? WHERE lease_id=? AND status='ACTIVE'", (now, expires, grant.lease_id))
            self._event(grant.assignment_id, "lease.heartbeat", grant.worker_id, now, {"lease_id": grant.lease_id})
        return LeaseGrant(**{**asdict(grant), "expires_at": expires})

    def expire_leases(self, now: str, actor: str = "supervisor") -> list[str]:
        expired: list[str] = []
        with self.connection:
            rows = self.connection.execute("SELECT * FROM worker_leases WHERE status='ACTIVE' AND expires_at<=?", (now,)).fetchall()
            for lease in rows:
                self.connection.execute("UPDATE worker_leases SET status='EXPIRED' WHERE lease_id=?", (lease["lease_id"],))
                self.connection.execute("UPDATE assignments SET state=?, revision=revision+1 WHERE assignment_id=? AND fencing_token=?", (AssignmentState.RECOVERING, lease["assignment_id"], lease["fencing_token"]))
                self._event(lease["assignment_id"], "lease.expired", actor, now, {"lease_id": lease["lease_id"], "fencing_token": lease["fencing_token"], "command_replayed": False})
                expired.append(lease["assignment_id"])
        return expired

    def submit_result(self, grant: LeaseGrant, result_state: AssignmentState, output_ref: str | None, evidence_refs: tuple[str, ...], limitations: tuple[str, ...], now: str) -> dict:
        if result_state not in {AssignmentState.SUCCEEDED, AssignmentState.PARTIAL, AssignmentState.FAILED}:
            raise AssignmentRejected("worker result state is invalid")
        self._validate_active(grant, now)
        if result_state is AssignmentState.SUCCEEDED and not evidence_refs:
            raise AssignmentRejected("successful result requires evidence")
        if result_state is AssignmentState.PARTIAL and not limitations:
            raise AssignmentRejected("partial result requires explicit limitations")
        result_id = str(uuid.uuid4())
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE assignments SET state=?, revision=revision+1, result_ref=? WHERE assignment_id=? AND state=? AND fencing_token=?",
                (result_state, result_id, grant.assignment_id, AssignmentState.LEASED, grant.fencing_token),
            )
            if cursor.rowcount != 1:
                raise StaleWorkerResult("fencing token no longer owns canonical assignment state")
            self.connection.execute("UPDATE worker_leases SET status='SETTLED' WHERE lease_id=?", (grant.lease_id,))
            self.connection.execute("INSERT INTO assignment_results VALUES (?,?,?,?,?,?,?,?,?)", (result_id, grant.assignment_id, grant.lease_id, grant.fencing_token, result_state, output_ref, json.dumps(evidence_refs), json.dumps(limitations), now))
            self._event(grant.assignment_id, "assignment.result", grant.worker_id, now, {"result_id": result_id, "state": result_state})
        return dict(self.connection.execute("SELECT * FROM assignment_results WHERE result_id=?", (result_id,)).fetchone())

    def get_assignment(self, assignment_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM assignments WHERE assignment_id=?", (assignment_id,)).fetchone()
        if row is None:
            raise AssignmentRejected("unknown assignment")
        return dict(row)

    def events(self, assignment_id: str) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM orchestration_events WHERE assignment_id=? ORDER BY sequence", (assignment_id,)).fetchall()]

    def assignments_for_task(self, task_ref: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM assignments WHERE task_ref=? ORDER BY rowid", (task_ref,)
        ).fetchall()
        return [dict(row) for row in rows]

    def result(self, result_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM assignment_results WHERE result_id=?", (result_id,)).fetchone()
        return dict(row) if row else None

    def validate_lease(self, grant: LeaseGrant, now: str) -> None:
        """Raise unless this grant is the current fenced owner of its assignment.

        NERVOUS SYSTEM owns leases, so this is the one place the question is
        answered. Callers outside this module use it rather than re-deriving it.
        """
        self._validate_active(grant, now)

    def _validate_active(self, grant: LeaseGrant, now: str) -> None:
        lease = self.connection.execute("SELECT * FROM worker_leases WHERE lease_id=?", (grant.lease_id,)).fetchone()
        assignment = self.connection.execute("SELECT * FROM assignments WHERE assignment_id=?", (grant.assignment_id,)).fetchone()
        if not lease or not assignment or lease["status"] != "ACTIVE" or lease["worker_id"] != grant.worker_id or lease["fencing_token"] != grant.fencing_token or assignment["fencing_token"] != grant.fencing_token:
            raise StaleWorkerResult("worker lease is stale or does not own assignment")
        if lease["expires_at"] <= now:
            raise StaleWorkerResult("worker lease expired")

    def _event(self, assignment_id: str, event_type: str, actor: str, now: str, payload: dict) -> None:
        self.connection.execute("INSERT INTO orchestration_events(event_id,assignment_id,event_type,actor,occurred_at,payload) VALUES (?,?,?,?,?,?)", (str(uuid.uuid4()), assignment_id, event_type, actor, now, json.dumps(payload, sort_keys=True)))

