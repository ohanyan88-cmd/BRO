"""Approval-aware IMMUNE authority evaluator for governed runtime flows."""
from __future__ import annotations

import json
import sqlite3
import uuid

from .approval import ApprovalRegistry
from .immune import AuthorityDecision, AuthorityEvaluator, AuthorityVerdict, normalize_boundary_scope


class GovernedAuthorityEvaluator(AuthorityEvaluator):
    """One evaluator: base authority first, then durable Approval may resolve its gate.

    The base evaluator always runs and writes the initial decision. Only an
    APPROVAL_REQUIRED result is eligible for resolution; a DENY can never be
    upgraded by Approval. Resolution is written to the same authority_decisions
    ledger and the Approval is consumed append-only after the ALLOW decision is
    durably recorded.
    """

    def __init__(self, connection: sqlite3.Connection, approvals: ApprovalRegistry) -> None:
        super().__init__(connection)
        self.approvals = approvals

    def evaluate(self, request: dict, envelope, now: str, *, subject_ref: str | None = None) -> AuthorityVerdict:
        base = super().evaluate(request, envelope, now, subject_ref=subject_ref)
        if base.decision is not AuthorityDecision.APPROVAL_REQUIRED:
            return base

        required_scope = {
            f"operation:{request['operation']}",
            f"target:{request['target']}",
            request["task_ref"],
        }
        boundary = request.get("project_boundary")
        if boundary:
            required_scope.add(normalize_boundary_scope(boundary))

        step_ref = request.get("step_ref")
        if step_ref is None and request.get("assignment_ref"):
            row = self.connection.execute(
                "SELECT body FROM assignments WHERE assignment_id=?", (request["assignment_ref"],)
            ).fetchone()
            if row:
                step_ref = json.loads(row["body"]).get("step_ref")

        approval = self.approvals.approved_for(
            task_ref=request["task_ref"],
            action_request_ref=request.get("action_request_id"),
            step_ref=step_ref,
            operation=request["operation"],
            target=request["target"],
            required_scope=tuple(required_scope),
            risk_class=request["risk_class"],
            now=now,
        )
        if approval is None:
            return base

        verdict = AuthorityVerdict(
            AuthorityDecision.ALLOW,
            (f"approval {approval['approval_id']} satisfied the guarded authority requirement",),
            envelope.envelope_id,
            envelope.version,
            envelope.digest,
        )
        with self.connection:
            self.connection.execute(
                """INSERT INTO authority_decisions(decision_id,subject_ref,envelope_id,envelope_version,
                   envelope_digest,decision,reasons,decided_at) VALUES (?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()),
                    subject_ref or request.get("action_request_id", "unknown"),
                    envelope.envelope_id,
                    envelope.version,
                    envelope.digest,
                    str(AuthorityDecision.ALLOW),
                    json.dumps(list(verdict.reasons)),
                    now,
                ),
            )
        self.approvals.consume(
            approval["approval_id"],
            task_ref=request["task_ref"],
            action_request_ref=request.get("action_request_id"),
        )
        return verdict
