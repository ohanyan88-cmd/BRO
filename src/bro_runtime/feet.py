"""FEET runtime: durable route, position, checkpoints, and safe continuation."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Callable

from .task_runtime import utc_now


class RouteState(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FeetRejected(ValueError):
    pass


@dataclass(frozen=True)
class RouteCheckpoint:
    route_id: str
    version: int
    task_ref: str
    plan_ref: str
    current_step_ref: str | None
    current_location: str
    next_location: str | None
    unresolved_refs: tuple[str, ...]
    authority_blocker_ref: str | None
    integrity_blocker_ref: str | None
    risk_blocker_ref: str | None
    state: RouteState
    recorded_at: str


class FeetStore:
    """Append-only FEET-owned route history. Movement never self-authorizes."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS feet_routes(
              route_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              task_ref TEXT NOT NULL,
              state TEXT NOT NULL,
              body TEXT NOT NULL,
              recorded_at TEXT NOT NULL,
              UNIQUE(route_id, version));
            """
        )

    @staticmethod
    def _encode(record: RouteCheckpoint) -> str:
        body = asdict(record)
        body["state"] = record.state.value
        body["unresolved_refs"] = list(record.unresolved_refs)
        return json.dumps(body, sort_keys=True)

    @staticmethod
    def _decode(body: str) -> RouteCheckpoint:
        data = json.loads(body)
        data["state"] = RouteState(data["state"])
        data["unresolved_refs"] = tuple(data["unresolved_refs"])
        return RouteCheckpoint(**data)

    def append(self, record: RouteCheckpoint) -> RouteCheckpoint:
        if not record.route_id.strip() or not record.task_ref.strip() or not record.plan_ref.strip():
            raise FeetRejected("route_id, task_ref and plan_ref are required")
        if record.version < 1:
            raise FeetRejected("route version must be positive")
        if record.state is RouteState.ACTIVE and (
            record.authority_blocker_ref or record.integrity_blocker_ref or record.risk_blocker_ref
        ):
            raise FeetRejected("ACTIVE movement cannot carry unresolved authority/integrity/risk blocker")
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO feet_routes(route_id,version,task_ref,state,body,recorded_at) VALUES (?,?,?,?,?,?)",
                    (record.route_id, record.version, record.task_ref, record.state.value,
                     self._encode(record), record.recorded_at),
                )
        except sqlite3.IntegrityError as exc:
            raise FeetRejected("route checkpoint version is immutable") from exc
        return record

    def latest(self, route_id: str) -> RouteCheckpoint:
        row = self.connection.execute(
            "SELECT body FROM feet_routes WHERE route_id=? ORDER BY version DESC LIMIT 1", (route_id,)
        ).fetchone()
        if row is None:
            raise FeetRejected(f"unknown route: {route_id}")
        return self._decode(row["body"])

    def move(self, route_id: str, *, current_step_ref: str | None, current_location: str,
             next_location: str | None, unresolved_refs: tuple[str, ...] = ()) -> RouteCheckpoint:
        prior = self.latest(route_id)
        if prior.state in {RouteState.COMPLETED, RouteState.CANCELLED}:
            raise FeetRejected(f"terminal route {prior.state} cannot move")
        if any((prior.authority_blocker_ref, prior.integrity_blocker_ref, prior.risk_blocker_ref)):
            raise FeetRejected("route is blocked; movement requires blocker resolution")
        record = RouteCheckpoint(
            route_id=prior.route_id, version=prior.version + 1, task_ref=prior.task_ref,
            plan_ref=prior.plan_ref, current_step_ref=current_step_ref,
            current_location=current_location, next_location=next_location,
            unresolved_refs=tuple(unresolved_refs), authority_blocker_ref=None,
            integrity_blocker_ref=None, risk_blocker_ref=None,
            state=RouteState.ACTIVE, recorded_at=utc_now(),
        )
        return self.append(record)

    def pause(self, route_id: str, *, unresolved_refs: tuple[str, ...] = ()) -> RouteCheckpoint:
        prior = self.latest(route_id)
        if prior.state in {RouteState.COMPLETED, RouteState.CANCELLED}:
            raise FeetRejected(f"terminal route {prior.state} cannot pause")
        record = RouteCheckpoint(
            **{**asdict(prior), "version": prior.version + 1, "state": RouteState.PAUSED,
               "unresolved_refs": tuple(dict.fromkeys((*prior.unresolved_refs, *unresolved_refs))),
               "recorded_at": utc_now()}
        )
        return self.append(record)

    def block(self, route_id: str, *, authority_ref: str | None = None,
              integrity_ref: str | None = None, risk_ref: str | None = None) -> RouteCheckpoint:
        prior = self.latest(route_id)
        if prior.state in {RouteState.COMPLETED, RouteState.CANCELLED}:
            raise FeetRejected(f"terminal route {prior.state} cannot block")
        if not any((authority_ref, integrity_ref, risk_ref)):
            raise FeetRejected("blocking requires a blocker reference")
        record = RouteCheckpoint(
            **{**asdict(prior), "version": prior.version + 1, "state": RouteState.BLOCKED,
               "authority_blocker_ref": authority_ref, "integrity_blocker_ref": integrity_ref,
               "risk_blocker_ref": risk_ref, "unresolved_refs": prior.unresolved_refs,
               "recorded_at": utc_now()}
        )
        return self.append(record)

    def resume(self, route_id: str, *, blocker_resolved: Callable[[str], bool]) -> RouteCheckpoint:
        prior = self.latest(route_id)
        if prior.state is not RouteState.BLOCKED:
            raise FeetRejected("only BLOCKED routes require explicit resume")
        blockers = tuple(ref for ref in (
            prior.authority_blocker_ref, prior.integrity_blocker_ref, prior.risk_blocker_ref
        ) if ref)
        if not blockers or not all(blocker_resolved(ref) for ref in blockers):
            raise FeetRejected("cannot resume until canonical blocker refs resolve")
        record = RouteCheckpoint(
            route_id=prior.route_id, version=prior.version + 1, task_ref=prior.task_ref,
            plan_ref=prior.plan_ref, current_step_ref=prior.current_step_ref,
            current_location=prior.current_location, next_location=prior.next_location,
            unresolved_refs=prior.unresolved_refs, authority_blocker_ref=None,
            integrity_blocker_ref=None, risk_blocker_ref=None,
            state=RouteState.ACTIVE, recorded_at=utc_now(),
        )
        return self.append(record)

    def complete(self, route_id: str, *, current_location: str = "COMPLETED") -> RouteCheckpoint:
        prior = self.latest(route_id)
        if prior.state is RouteState.CANCELLED:
            raise FeetRejected("CANCELLED route cannot complete")
        if prior.state is RouteState.COMPLETED:
            return prior
        if any((prior.authority_blocker_ref, prior.integrity_blocker_ref, prior.risk_blocker_ref)):
            raise FeetRejected("blocked route cannot complete")
        record = RouteCheckpoint(
            route_id=prior.route_id, version=prior.version + 1, task_ref=prior.task_ref,
            plan_ref=prior.plan_ref, current_step_ref=prior.current_step_ref,
            current_location=current_location, next_location=None, unresolved_refs=(),
            authority_blocker_ref=None, integrity_blocker_ref=None, risk_blocker_ref=None,
            state=RouteState.COMPLETED, recorded_at=utc_now(),
        )
        return self.append(record)
