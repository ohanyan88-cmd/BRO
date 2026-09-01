"""IMMUNE SYSTEM-owned Approval records and validity checks."""
from __future__ import annotations
import json, sqlite3
from dataclasses import asdict, dataclass

class ApprovalRejected(ValueError): pass

@dataclass(frozen=True)
class Approval:
    approval_id:str; approver:str; proof_ref:str; requested_action:str; target:str; scope:tuple[str,...]; risk_class:str; consequences:tuple[str,...]; conditions:tuple[str,...]; valid_from:str; expires_at:str|None; decision:str; revocation_state:str; task_ref:str; action_request_ref:str; audit_ref:str; step_ref:str|None=None

class ApprovalLedger:
    def __init__(self, connection:sqlite3.Connection):
        self.connection=connection; self.connection.row_factory=sqlite3.Row
        self.connection.execute("CREATE TABLE IF NOT EXISTS approvals(approval_id TEXT PRIMARY KEY,task_ref TEXT NOT NULL,action_request_ref TEXT NOT NULL,decision TEXT NOT NULL,body TEXT NOT NULL)")
    def record(self, approval:Approval):
        if approval.decision not in {"REQUESTED","APPROVED","DENIED","EXPIRED","REVOKED","CONSUMED","SUPERSEDED"}: raise ApprovalRejected("invalid Approval decision")
        with self.connection:self.connection.execute("INSERT INTO approvals VALUES (?,?,?,?,?)",(approval.approval_id,approval.task_ref,approval.action_request_ref,approval.decision,json.dumps(asdict(approval),sort_keys=True)))
        return approval
    def get(self, approval_id:str)->Approval:
        row=self.connection.execute("SELECT body FROM approvals WHERE approval_id=?",(approval_id,)).fetchone()
        if row is None: raise ApprovalRejected(f"unknown Approval: {approval_id}")
        d=json.loads(row['body']); d['scope']=tuple(d['scope']); d['consequences']=tuple(d['consequences']); d['conditions']=tuple(d['conditions']); return Approval(**d)
    def require_current(self, approval_id:str, *, task_ref:str, action_request_ref:str, now:str)->Approval:
        a=self.get(approval_id)
        if a.task_ref!=task_ref or a.action_request_ref!=action_request_ref: raise ApprovalRejected("Approval is bound to different work")
        if a.decision!="APPROVED" or a.revocation_state=="REVOKED": raise ApprovalRejected("Approval is not active and approved")
        if now<a.valid_from or (a.expires_at and now>=a.expires_at): raise ApprovalRejected("Approval is not currently valid")
        return a
