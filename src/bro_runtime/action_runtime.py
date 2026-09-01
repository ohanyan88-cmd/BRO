"""HANDS-owned action lifecycle under IMMUNE SYSTEM authority.

HANDS owns the Action Request, the Action Attempt, and execution truth. It does
not decide whether an action is permitted: it submits the request to the single
`AuthorityEvaluator` in `immune.py` and records the state its verdict implies.
"""
from __future__ import annotations
import json,sqlite3,uuid
from dataclasses import asdict,dataclass
from enum import StrEnum
from typing import Callable
from .immune import AuthorityDecision,AuthorityEnvelope,AuthorityEvaluator,AuthorityRejected
from .task_runtime import utc_now
__all__=["ActionRejected","ActionRequest","ActionRuntime","ActionState","AdapterResult","ApprovalRequired","EffectState","RetryBlocked"]
class ActionRejected(Exception): pass
class RetryBlocked(ActionRejected): pass
class ApprovalRequired(ActionRejected): pass
class ActionState(StrEnum):
    PROPOSED="PROPOSED"; AUTHORIZED="AUTHORIZED"; DISPATCHED="DISPATCHED"; RESULT_RECEIVED="RESULT_RECEIVED"; EFFECT_RECONCILED="EFFECT_RECONCILED"; VERIFIED="VERIFIED"; DENIED="DENIED"; FAILED="FAILED"; TIMED_OUT="TIMED_OUT"; EFFECT_UNKNOWN="EFFECT_UNKNOWN"; CANCELLED="CANCELLED"
class EffectState(StrEnum):
    NONE="NONE"; POSSIBLE="POSSIBLE"; CONFIRMED="CONFIRMED"; UNKNOWN="UNKNOWN"; REVERSED="REVERSED"
@dataclass(frozen=True)
class ActionRequest:
    action_request_id:str; task_ref:str; intended_effect:str; operation:str; target:str; environment:str; adapter_id:str; input_parameters:dict; authority_envelope_ref:str; risk_class:str; reversibility:str; idempotency_key:str; idempotency_guaranteed:bool; expected_result:object; verification_requirements:tuple[str,...]; assignment_ref:str|None=None; project_boundary:str|None=None
@dataclass(frozen=True)
class AdapterResult:
    result:object; effect_state:EffectState; artifact_refs:tuple[str,...]=(); observation_refs:tuple[str,...]=()
def _sanitized_adapter_error(kind:str)->str:
    return f"{kind}: adapter error details redacted"
class ActionRuntime:
    def __init__(self,connection:sqlite3.Connection)->None:
        self.connection=connection; self.connection.row_factory=sqlite3.Row; self.authority=AuthorityEvaluator(connection)
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS action_requests (action_request_id TEXT PRIMARY KEY, task_ref TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL, authority_digest TEXT);
        CREATE TABLE IF NOT EXISTS action_attempts (sequence INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL UNIQUE, action_request_id TEXT NOT NULL REFERENCES action_requests(action_request_id), executor TEXT NOT NULL, interface_version TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL, sanitized_inputs TEXT NOT NULL, status TEXT NOT NULL, result TEXT, error TEXT, effect_state TEXT NOT NULL, retry_of_ref TEXT, artifact_refs TEXT NOT NULL, observation_refs TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS action_reconciliations (sequence INTEGER PRIMARY KEY AUTOINCREMENT, reconciliation_id TEXT NOT NULL UNIQUE, attempt_id TEXT NOT NULL REFERENCES action_attempts(attempt_id), effect_state TEXT NOT NULL, evidence_ref TEXT NOT NULL, reconciled_at TEXT NOT NULL);
        """)
    def register_authority(self,envelope:AuthorityEnvelope)->None:
        try:self.authority.register(envelope)
        except AuthorityRejected as exc: raise ActionRejected(str(exc)) from exc
    def authority_envelope(self,envelope_id:str,version:int|None=None)->AuthorityEnvelope:
        try:return self.authority.envelope(envelope_id,version)
        except AuthorityRejected as exc: raise ActionRejected(str(exc)) from exc
    def propose(self,request:ActionRequest)->dict:
        with self.connection:self.connection.execute("INSERT INTO action_requests VALUES (?, ?, ?, ?, 1, NULL)",(request.action_request_id,request.task_ref,json.dumps(asdict(request),sort_keys=True),ActionState.PROPOSED))
        return self.get_request(request.action_request_id)
    def authorize(self,request_id:str,envelope:AuthorityEnvelope,now:str|None=None)->dict:
        request=self.get_request(request_id); body=json.loads(request["body"]); verdict=self.authority.evaluate(body,envelope,now or utc_now(),subject_ref=request_id); target=ActionState.AUTHORIZED if verdict.is_allowed() else ActionState.DENIED
        with self.connection:
            cursor=self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1, authority_digest=? WHERE action_request_id=? AND state=?",(target,verdict.envelope_digest,request_id,ActionState.PROPOSED))
            if cursor.rowcount!=1: raise ActionRejected("only a PROPOSED action may be authorized")
        if verdict.decision is AuthorityDecision.APPROVAL_REQUIRED: raise ApprovalRequired("authority requires approval: "+"; ".join(verdict.reasons))
        if not verdict.is_allowed(): raise ActionRejected("authority denied: "+"; ".join(verdict.reasons))
        return self.get_request(request_id)
    def dispatch(self,request_id:str,executor:str,interface_version:str,adapter:Callable[[dict],AdapterResult],*,envelope:AuthorityEnvelope|None=None,now:str|None=None)->dict:
        request=self.get_request(request_id)
        if request["state"]!=ActionState.AUTHORIZED: raise ActionRejected("dispatch requires AUTHORIZED state")
        body=json.loads(request["body"]); envelope=envelope or self.authority_envelope(body["authority_envelope_ref"]); moment=now or utc_now()
        if envelope.envelope_id!=body["authority_envelope_ref"]: raise ActionRejected("dispatch authority envelope does not match the action request")
        if request["authority_digest"]!=envelope.digest: raise ActionRejected("dispatch authority envelope differs from the authorized decision")
        # Approval may have been durably consumed by GovernedAuthorityEvaluator at
        # authorization. JIT dispatch revalidates the immutable grant constraints
        # and temporal/revocation state without replaying that one-time approval.
        failures=AuthorityEvaluator._failures(body,envelope,moment)
        if failures:
            with self.connection:self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=? AND state=?",(ActionState.DENIED,request_id,ActionState.AUTHORIZED))
            raise ActionRejected("dispatch authority denied: "+"; ".join(failures))
        prior=self.latest_attempt(request_id); prior_effect=self.effective_effect(prior) if prior else None
        if prior and prior_effect==EffectState.UNKNOWN and not body["idempotency_guaranteed"]: raise RetryBlocked("UNKNOWN effect must be reconciled before retry")
        if prior and prior_effect==EffectState.CONFIRMED: raise RetryBlocked("confirmed effect cannot be dispatched again")
        with self.connection:self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?",(ActionState.DISPATCHED,request_id))
        started=utc_now(); result=None; error=None; artifacts=(); observations=(); retry_ref=prior["attempt_id"] if prior else None
        try:
            response=adapter(dict(body["input_parameters"]))
            if not isinstance(response,AdapterResult): raise ActionRejected("adapter must return AdapterResult")
            result=response.result; effect=response.effect_state; artifacts=response.artifact_refs; observations=response.observation_refs; status="SUCCEEDED"; state=ActionState.RESULT_RECEIVED
        except TimeoutError:error,effect,status,state=_sanitized_adapter_error("TimeoutError"),EffectState.UNKNOWN,"TIMED_OUT",ActionState.EFFECT_UNKNOWN
        except Exception:error,effect,status,state=_sanitized_adapter_error("AdapterFailure"),EffectState.POSSIBLE,"FAILED",ActionState.FAILED
        attempt_id=str(uuid.uuid4())
        with self.connection:
            self.connection.execute("INSERT INTO action_attempts(attempt_id,action_request_id,executor,interface_version,started_at,ended_at,sanitized_inputs,status,result,error,effect_state,retry_of_ref,artifact_refs,observation_refs) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(attempt_id,request_id,executor,interface_version,started,utc_now(),json.dumps(body["input_parameters"],sort_keys=True),status,json.dumps(result),error,effect,retry_ref,json.dumps(artifacts),json.dumps(observations)))
            self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?",(state,request_id))
        return self.latest_attempt(request_id)
    def reconcile(self,request_id:str,effect_state:EffectState,evidence_ref:str)->dict:
        if effect_state is EffectState.UNKNOWN: raise ActionRejected("reconciliation must resolve UNKNOWN")
        attempt=self.latest_attempt(request_id)
        if not attempt: raise ActionRejected("no attempt to reconcile")
        with self.connection:
            self.connection.execute("INSERT INTO action_reconciliations(reconciliation_id,attempt_id,effect_state,evidence_ref,reconciled_at) VALUES (?,?,?,?,?)",(str(uuid.uuid4()),attempt["attempt_id"],effect_state,evidence_ref,utc_now()))
            self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?",(ActionState.EFFECT_RECONCILED,request_id))
        return self.latest_attempt(request_id)
    def prepare_retry(self,request_id:str)->dict:
        request=self.get_request(request_id); attempt=self.latest_attempt(request_id); body=json.loads(request["body"])
        if not attempt: raise RetryBlocked("no attempt exists")
        effective=self.effective_effect(attempt)
        if effective==EffectState.UNKNOWN and not body["idempotency_guaranteed"]: raise RetryBlocked("UNKNOWN effect must be reconciled before retry")
        if effective==EffectState.CONFIRMED: raise RetryBlocked("confirmed effect cannot be retried")
        with self.connection:self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?",(ActionState.AUTHORIZED,request_id))
        return self.get_request(request_id)
    def get_request(self,request_id:str)->dict:
        row=self.connection.execute("SELECT * FROM action_requests WHERE action_request_id=?",(request_id,)).fetchone()
        if row is None: raise ActionRejected("unknown action request")
        return dict(row)
    def latest_attempt(self,request_id:str)->dict|None:
        row=self.connection.execute("SELECT * FROM action_attempts WHERE action_request_id=? ORDER BY sequence DESC LIMIT 1",(request_id,)).fetchone(); return dict(row) if row else None
    def effective_effect(self,attempt:dict)->EffectState:
        row=self.connection.execute("SELECT effect_state FROM action_reconciliations WHERE attempt_id=? ORDER BY sequence DESC LIMIT 1",(attempt["attempt_id"],)).fetchone(); return EffectState(row["effect_state"] if row else attempt["effect_state"])
    def requests_for_task(self,task_ref:str)->list[dict]:
        rows=self.connection.execute("SELECT * FROM action_requests WHERE task_ref=? ORDER BY rowid",(task_ref,)).fetchall(); return [dict(row) for row in rows]