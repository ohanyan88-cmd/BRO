"""Durable human approval delivery and response loop.

The loop never grants authority itself. It transports an IMMUNE-owned Approval
request to a named human, durably tracks notification delivery, and records the
human's response back into the same immutable Approval history and Task binding.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from .approval import Approval, ApprovalDecision, ApprovalRegistry, ApprovalRejected, RevocationState
from .task_runtime import utc_now


class HumanLoopRejected(RuntimeError):
    pass


class InteractionState(StrEnum):
    WAITING = "WAITING"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class NotificationState(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    SENT = "SENT"


@dataclass(frozen=True)
class HumanInteraction:
    approval_id: str
    task_ref: str
    approver: str
    channel: str
    recipient: str
    state: InteractionState
    notification_state: NotificationState
    notification_revision: int


class HumanApprovalLoop:
    """Persistent approval inbox/outbox bound to canonical Approval records."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.approvals = ApprovalRegistry(connection)
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS human_approval_interactions(
                approval_id TEXT PRIMARY KEY,
                task_ref TEXT NOT NULL,
                approver TEXT NOT NULL,
                channel TEXT NOT NULL,
                recipient TEXT NOT NULL,
                response_token_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS human_approval_notifications(
                approval_id TEXT PRIMARY KEY REFERENCES human_approval_interactions(approval_id),
                state TEXT NOT NULL,
                revision INTEGER NOT NULL,
                lease_owner TEXT,
                lease_until TEXT,
                sent_at TEXT,
                updated_at TEXT NOT NULL
            );
            """
        )

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def request(self, approval: Approval, *, channel: str, recipient: str, response_token: str | None = None) -> tuple[HumanInteraction, str]:
        if approval.decision is not ApprovalDecision.REQUESTED:
            raise HumanLoopRejected("human loop only accepts REQUESTED approvals")
        if not channel.strip() or not recipient.strip():
            raise HumanLoopRejected("approval delivery channel and recipient are required")
        token = response_token or secrets.token_urlsafe(24)
        now = utc_now()
        try:
            with self.connection:
                self.approvals.record(approval)
                self.connection.execute(
                    "INSERT INTO human_approval_interactions VALUES (?,?,?,?,?,?,'WAITING',?,NULL)",
                    (approval.approval_id, approval.task_ref, approval.approver, channel, recipient, self._digest(token), now),
                )
                self.connection.execute(
                    "INSERT INTO human_approval_notifications VALUES (?,'PENDING',1,NULL,NULL,NULL,?)",
                    (approval.approval_id, now),
                )
        except (sqlite3.IntegrityError, ApprovalRejected) as exc:
            raise HumanLoopRejected("approval interaction already exists or is invalid") from exc
        return self.fetch(approval.approval_id), token

    def fetch(self, approval_id: str) -> HumanInteraction:
        row = self.connection.execute(
            "SELECT i.*,n.state AS notification_state,n.revision AS notification_revision FROM human_approval_interactions i JOIN human_approval_notifications n USING(approval_id) WHERE i.approval_id=?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise HumanLoopRejected("unknown human approval interaction")
        return HumanInteraction(row["approval_id"], row["task_ref"], row["approver"], row["channel"], row["recipient"], InteractionState(row["state"]), NotificationState(row["notification_state"]), row["notification_revision"])

    def claim_notification(self, approval_id: str, *, owner: str, lease_until: str) -> HumanInteraction:
        if not owner.strip() or not lease_until.strip():
            raise HumanLoopRejected("notification lease owner and expiry are required")
        with self.connection:
            row = self.connection.execute("SELECT state,revision FROM human_approval_notifications WHERE approval_id=?", (approval_id,)).fetchone()
            if row is None or row["state"] == NotificationState.SENT:
                raise HumanLoopRejected("notification is not claimable")
            cursor = self.connection.execute(
                "UPDATE human_approval_notifications SET state='LEASED',revision=revision+1,lease_owner=?,lease_until=?,updated_at=? WHERE approval_id=? AND revision=?",
                (owner, lease_until, utc_now(), approval_id, row["revision"]),
            )
            if cursor.rowcount != 1:
                raise HumanLoopRejected("notification changed during claim")
        return self.fetch(approval_id)

    def mark_sent(self, approval_id: str, *, owner: str) -> HumanInteraction:
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE human_approval_notifications SET state='SENT',revision=revision+1,sent_at=?,updated_at=? WHERE approval_id=? AND state='LEASED' AND lease_owner=?",
                (utc_now(), utc_now(), approval_id, owner),
            )
            if cursor.rowcount != 1:
                raise HumanLoopRejected("notification sender does not hold the delivery lease")
        return self.fetch(approval_id)

    def respond(self, approval_id: str, *, responder: str, response_token: str, decision: ApprovalDecision, proof_ref: str) -> dict:
        if decision not in {ApprovalDecision.APPROVED, ApprovalDecision.DENIED}:
            raise HumanLoopRejected("human response must APPROVE or DENY")
        row = self.connection.execute("SELECT * FROM human_approval_interactions WHERE approval_id=?", (approval_id,)).fetchone()
        if row is None or row["state"] != InteractionState.WAITING:
            raise HumanLoopRejected("approval interaction is not waiting for a response")
        if responder != row["approver"]:
            raise HumanLoopRejected("response identity does not match the named approver")
        if self._digest(response_token) != row["response_token_hash"]:
            raise HumanLoopRejected("approval response token is invalid")
        prior = self.approvals.get(approval_id)
        body = json.loads(prior["body"])
        response = Approval(
            approval_id=body["approval_id"], approver=body["approver"], proof_ref=proof_ref,
            requested_action=body["requested_action"], target=body["target"], scope=tuple(body["scope"]),
            risk_class=body["risk_class"], consequences=tuple(body["consequences"]), conditions=tuple(body["conditions"]),
            valid_from=body["valid_from"], expires_at=body["expires_at"], decision=decision,
            revocation_state=RevocationState(body["revocation_state"]), task_ref=body["task_ref"],
            action_request_ref=body.get("action_request_ref"), audit_ref=body["audit_ref"], step_ref=body.get("step_ref"),
        )
        with self.connection:
            recorded = self.approvals.record(response, prior["version"] + 1)
            self.connection.execute("UPDATE human_approval_interactions SET state='RESOLVED',resolved_at=? WHERE approval_id=? AND state='WAITING'", (utc_now(), approval_id))
        return recorded
