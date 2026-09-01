"""IMMUNE SYSTEM approval records and one-time approval consumption."""
from __future__ import annotations
import json, sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum

from .task_runtime import utc_now

class ApprovalRejected(Exception): pass
class ApprovalDecision(StrEnum):
    REQUESTED="REQUESTED"; APPROVED="APPROVED"; DENIED="DENIED"; EXPIRED="EXPIRED"; REVOKED="REVOKED"; CONSUMED="CONSUMED"; SUPERSEDED="SUPERSEDED"
class RevocationState(StrEnum): ACTIVE="ACTIVE"; REVOKED="REVOKED"; NOT_APPLICABLE="NOT_APPLICABLE"

@dataclass(frozen=True)
class Approval:
    approval_id:str; approver:str; proof_ref:str; requested_action:str; target:str; scope:tuple[str,...]; risk_class:str; consequences:tuple[str,...]; conditions:tuple[str,...]; valid_from:str; expires_at:str|None; decision:ApprovalDecision; revocation_state:RevocationState; task_ref:str; action_request_ref:str|None; audit_ref:str; step_ref:str|None=None
    def body(self):
        d=asdict(self); d["decision"]=str(self.decision); d["revocation_state"]=str(self.revocation_state); return d

class ApprovalRegistry:
    """Append-only Approval history. Consumption appends a new version; prior proof remains immutable."""
    def __init__(self, connection:sqlite3.Connection):
        self.connection=connection; self.connection.row_factory=sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS approvals(
          sequence INTEGER PRIMARY KEY AUTOINCREMENT,
          approval_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          task_ref TEXT NOT NULL,
          action_request_ref TEXT,
          decision TEXT NOT NULL,
          body TEXT NOT NULL,
          recorded_at TEXT NOT NULL,
          UNIQUE(approval_id,version));
        """)
    def record(self, approval:Approval, version:int=1):
        if version < 1: raise ApprovalRejected("approval version must be >= 1")
        try:
            with self.connection:self.connection.execute("INSERT INTO approvals(approval_id,version,task_ref,action_request_ref,decision,body,recorded_at) VALUES (?,?,?,?,?,?,?)",(approval.approval_id,version,approval.task_ref,approval.action_request_ref,str(approval.decision),json.dumps(approval.body(),sort_keys=True),utc_now()))
        except sqlite3.IntegrityError as exc: raise ApprovalRejected("Approval records are immutable per version") from exc
        return self.get(approval.approval_id,version)
    def get(self, approval_id, version=None):
        if version is None: row=self.connection.execute("SELECT * FROM approvals WHERE approval_id=? ORDER BY version DESC LIMIT 1",(approval_id,)).fetchone()
        else: row=self.connection.execute("SELECT * FROM approvals WHERE approval_id=? AND version=?",(approval_id,version)).fetchone()
        if row is None: raise ApprovalRejected(f"unknown approval: {approval_id}")
        return dict(row)
    def approved_for(self, *, task_ref, action_request_ref=None, step_ref=None, operation, target, required_scope, risk_class, now):
        rows=self.connection.execute("""
            SELECT a.* FROM approvals a
            JOIN (
              SELECT approval_id, MAX(version) AS version
              FROM approvals WHERE task_ref=? GROUP BY approval_id
            ) latest ON latest.approval_id=a.approval_id AND latest.version=a.version
            WHERE a.task_ref=? ORDER BY a.sequence DESC
        """,(task_ref,task_ref)).fetchall()
        for row in rows:
            body=json.loads(row["body"])
            if row["decision"] != "APPROVED": continue
            if body["revocation_state"] == "REVOKED": continue
            if now < body["valid_from"]: continue
            if body["expires_at"] and now >= body["expires_at"]: continue
            if body["requested_action"] != operation or body["target"] != target: continue
            if body["risk_class"] != risk_class: continue
            if not set(required_scope).issubset(set(body["scope"])): continue
            bound_action=body.get("action_request_ref"); bound_step=body.get("step_ref")
            if bound_action is not None and bound_action != action_request_ref: continue
            if bound_step is not None and bound_step != step_ref: continue
            return dict(row)
        return None
    def consume(self, approval_id, *, task_ref, action_request_ref=None):
        prior=self.get(approval_id); body=json.loads(prior["body"])
        if prior["decision"] != "APPROVED": raise ApprovalRejected("only APPROVED approval may be consumed")
        consumed=Approval(approval_id=body["approval_id"],approver=body["approver"],proof_ref=body["proof_ref"],requested_action=body["requested_action"],target=body["target"],scope=tuple(body["scope"]),risk_class=body["risk_class"],consequences=tuple(body["consequences"]),conditions=tuple(body["conditions"]),valid_from=body["valid_from"],expires_at=body["expires_at"],decision=ApprovalDecision.CONSUMED,revocation_state=RevocationState(body["revocation_state"]),task_ref=task_ref,action_request_ref=action_request_ref if action_request_ref is not None else body.get("action_request_ref"),audit_ref=body["audit_ref"],step_ref=body.get("step_ref"))
        return self.record(consumed, prior["version"]+1)
