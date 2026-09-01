"""Durable, evidence-governed Task lifecycle owned by NERVOUS SYSTEM.

The module deliberately owns coordination state only. MIND supplies decisions,
HANDS supplies action results, IMMUNE SYSTEM supplies authority/evidence, and
FEET supplies navigation checkpoints. Their records remain references here.
"""
from __future__ import annotations
import json, sqlite3, uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path

def utc_now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

class TaskState(StrEnum):
    RECEIVED="RECEIVED"; INTERPRETING="INTERPRETING"; READY="READY"; PLANNING="PLANNING"; AUTHORIZING="AUTHORIZING"; EXECUTING="EXECUTING"; VERIFYING="VERIFYING"; BLOCKED="BLOCKED"; PAUSED="PAUSED"; RECOVERING="RECOVERING"; COMPLETED="COMPLETED"; FAILED="FAILED"; CANCELLED="CANCELLED"
TERMINAL_STATES=frozenset({TaskState.COMPLETED,TaskState.FAILED,TaskState.CANCELLED})
PRIMARY_NEXT={TaskState.RECEIVED:{TaskState.INTERPRETING},TaskState.INTERPRETING:{TaskState.READY},TaskState.READY:{TaskState.PLANNING},TaskState.PLANNING:{TaskState.AUTHORIZING},TaskState.AUTHORIZING:{TaskState.EXECUTING},TaskState.EXECUTING:{TaskState.VERIFYING,TaskState.PLANNING},TaskState.VERIFYING:{TaskState.COMPLETED,TaskState.EXECUTING,TaskState.PLANNING}}
CONTROL_FROM={TaskState.BLOCKED:{TaskState.INTERPRETING,TaskState.READY,TaskState.PLANNING,TaskState.AUTHORIZING,TaskState.EXECUTING,TaskState.VERIFYING,TaskState.FAILED,TaskState.CANCELLED},TaskState.PAUSED:{TaskState.INTERPRETING,TaskState.READY,TaskState.PLANNING,TaskState.AUTHORIZING,TaskState.EXECUTING,TaskState.VERIFYING,TaskState.CANCELLED},TaskState.RECOVERING:{TaskState.EXECUTING,TaskState.VERIFYING,TaskState.BLOCKED,TaskState.FAILED,TaskState.CANCELLED}}
CANONICAL_TASK_COLUMNS={"accountable_identity":"accountable_identity TEXT NOT NULL DEFAULT 'BRO'","plan_ref":"plan_ref TEXT","plan_revision":"plan_revision INTEGER","active_step_ref":"active_step_ref TEXT","blocker_ref":"blocker_ref TEXT","context_manifest_ref":"context_manifest_ref TEXT","authority_state":"authority_state TEXT NOT NULL DEFAULT 'UNASSESSED'","approval_refs":"approval_refs TEXT NOT NULL DEFAULT '[]'","artifact_refs":"artifact_refs TEXT NOT NULL DEFAULT '[]'","excluded_scope":"excluded_scope TEXT NOT NULL DEFAULT '[]'","completion_manifest_ref":"completion_manifest_ref TEXT"}
JSON_TASK_COLUMNS=("evidence_refs","artifact_refs","approval_refs","excluded_scope")
AUTHORITY_STATES=frozenset({"UNASSESSED","ALLOWED","APPROVAL_REQUIRED","DENIED","EXPIRED","REVOKED"})
_UNSET=object()

class RuntimeErrorBase(Exception): pass
class InvalidTransition(RuntimeErrorBase): pass
class TaskContractViolation(RuntimeErrorBase): pass
class ConcurrencyConflict(RuntimeErrorBase): pass
class TaskNotFound(RuntimeErrorBase): pass

@dataclass(frozen=True)
class CompletionEvidence:
    outcome_exists:bool; mandatory_scope_satisfied:bool; effects_reconciled:bool; artifacts_usable:bool; criteria_evidence_refs:tuple[str,...]; checks_passed:bool; no_invalidating_blocker:bool; exclusions_explicit:bool; communication_truthful:bool
    def failures(self):
        checks={"outcome does not exist":self.outcome_exists,"mandatory scope is not satisfied":self.mandatory_scope_satisfied,"effects are not reconciled":self.effects_reconciled,"artifacts are not usable":self.artifacts_usable,"completion criteria lack Evidence":bool(self.criteria_evidence_refs),"required checks did not pass":self.checks_passed,"an invalidating blocker remains":self.no_invalidating_blocker,"partial or excluded scope is not explicit":self.exclusions_explicit,"communication does not reflect actual state":self.communication_truthful}
        return [m for m,p in checks.items() if not p]

@dataclass(frozen=True)
class RecoveryAssessment:
    integrity_valid:bool; authority_valid:bool; external_state_inspected:bool; effect_state:str; context_current:bool; approval_current:bool; evidence_refs:tuple[str,...]=(); decision_ref:str|None=None
    def next_state(self):
        if not self.integrity_valid:return TaskState.FAILED
        if not self.external_state_inspected or self.effect_state=="UNKNOWN":return TaskState.BLOCKED
        if not self.authority_valid or not self.context_current or not self.approval_current:return TaskState.BLOCKED
        if self.effect_state=="CONFIRMED":return TaskState.VERIFYING
        if self.effect_state in {"NONE","RECONCILED"}:return TaskState.EXECUTING
        return TaskState.BLOCKED

class SQLiteTaskStore:
    def __init__(self,path:str|Path=":memory:"):
        self.connection=sqlite3.connect(str(path)); self.connection.row_factory=sqlite3.Row; self.connection.execute("PRAGMA foreign_keys = ON"); self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript("""CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY,goal_ref TEXT NOT NULL,state TEXT NOT NULL,prior_active_state TEXT,resume_checkpoint_ref TEXT,evidence_refs TEXT NOT NULL DEFAULT '[]',revision INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,termination_reason TEXT);CREATE TABLE IF NOT EXISTS runtime_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,task_id TEXT NOT NULL REFERENCES tasks(task_id),event_type TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,prior_state TEXT,new_state TEXT NOT NULL,occurred_at TEXT NOT NULL,correlation_ref TEXT NOT NULL,causal_ref TEXT,payload TEXT NOT NULL,schema_version TEXT NOT NULL);"""); self._migrate()
    def _migrate(self):
        present={r["name"] for r in self.connection.execute("PRAGMA table_info(tasks)").fetchall()}
        with self.connection:
            for c,ddl in CANONICAL_TASK_COLUMNS.items():
                if c not in present:self.connection.execute(f"ALTER TABLE tasks ADD COLUMN {ddl}")
    def fetch_task(self,task_id):
        row=self.connection.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone()
        if row is None:raise TaskNotFound(task_id)
        task=dict(row)
        for c in JSON_TASK_COLUMNS:task[c]=json.loads(task[c])
        return task
    def canonical_task(self,task_id):
        task=self.fetch_task(task_id); unbound=[f for f in ("plan_ref","plan_revision","context_manifest_ref") if not task[f]]
        if unbound:raise TaskContractViolation(f"{task_id} cannot be projected as a canonical Task; unbound references: {', '.join(unbound)}")
        if task["state"]==TaskState.COMPLETED and not task["completion_manifest_ref"]:raise TaskContractViolation(f"{task_id} is COMPLETED without completion_manifest_ref")
        return {"task_id":task["task_id"],"goal_ref":task["goal_ref"],"accountable_identity":task["accountable_identity"],"state":task["state"],"plan_ref":task["plan_ref"],"plan_revision":task["plan_revision"],"active_step_ref":task["active_step_ref"],"blocker_ref":task["blocker_ref"],"context_manifest_ref":task["context_manifest_ref"],"authority_state":task["authority_state"],"approval_refs":task["approval_refs"],"evidence_refs":task["evidence_refs"],"artifact_refs":task["artifact_refs"],"completion_manifest_ref":task["completion_manifest_ref"],"created_at":task["created_at"],"updated_at":task["updated_at"],"revision":task["revision"],"termination_reason":task["termination_reason"],"excluded_scope":task["excluded_scope"]}
    def events(self,task_id):return [dict(r) for r in self.connection.execute("SELECT * FROM runtime_events WHERE task_id=? ORDER BY sequence",(task_id,)).fetchall()]
    def close(self):self.connection.close()

class TaskRuntime:
    def __init__(self,store):self.store=store
    def create_task(self,task_id,goal_ref,actor,reason,correlation_ref=None,*,accountable_identity="BRO"):
        now=utc_now(); correlation=correlation_ref or task_id
        with self.store.connection:
            self.store.connection.execute("INSERT INTO tasks(task_id,goal_ref,state,revision,created_at,updated_at,accountable_identity,authority_state) VALUES (?,?,?,1,?,?,?,'UNASSESSED')",(task_id,goal_ref,TaskState.RECEIVED,now,now,accountable_identity)); self._append_event(task_id,"task.received",actor,reason,None,TaskState.RECEIVED,correlation,None,{})
        return self.store.fetch_task(task_id)
    def record_event(self,task_id,event_type,actor,reason,*,correlation_ref=None,causal_ref=None,payload=None):
        task=self.store.fetch_task(task_id); state=TaskState(task["state"])
        with self.store.connection:return self._append_event(task_id,event_type,actor,reason,None,state,correlation_ref or task_id,causal_ref,payload or {})
    def _require_verified_completion_manifest(self,task_id,manifest_ref):
        table=self.store.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='completion_manifests'").fetchone()
        if table is None:raise InvalidTransition("COMPLETED requires a canonical IMMUNE completion manifest")
        row=self.store.connection.execute("SELECT task_ref,verdict FROM completion_manifests WHERE manifest_id=?",(manifest_ref,)).fetchone()
        if row is None:raise InvalidTransition("completion_manifest_ref does not resolve to canonical IMMUNE state")
        if row["task_ref"]!=task_id or row["verdict"]!="VERIFIED":raise InvalidTransition("completion_manifest_ref is not this Task's VERIFIED manifest")
    def transition(self,task_id,target,actor,reason,expected_revision,*,correlation_ref=None,causal_ref=None,resume_checkpoint_ref=None,completion=None,evidence_refs=(),payload=None,plan_ref=None,plan_revision=None,context_manifest_ref=None,authority_state=None,active_step_ref=None,blocker_ref=_UNSET,artifact_refs=(),approval_refs=(),excluded_scope=(),completion_manifest_ref=None):
        task=self.store.fetch_task(task_id); source=TaskState(task["state"])
        if task["revision"]!=expected_revision:raise ConcurrencyConflict(f"expected revision {expected_revision}, found {task['revision']}")
        self._guard_transition(source,target,task,resume_checkpoint_ref)
        if authority_state is not None and authority_state not in AUTHORITY_STATES:raise InvalidTransition(f"unknown authority state {authority_state!r}")
        refs=tuple(dict.fromkeys((*task["evidence_refs"],*evidence_refs))); artifacts=tuple(dict.fromkeys((*task["artifact_refs"],*artifact_refs))); approvals=tuple(dict.fromkeys((*task["approval_refs"],*approval_refs))); exclusions=tuple(dict.fromkeys((*task["excluded_scope"],*excluded_scope)))
        payload=payload or {}; manifest_ref=completion_manifest_ref or (payload.get("manifest_id") if target is TaskState.COMPLETED else None) or task["completion_manifest_ref"]
        if target is TaskState.COMPLETED:
            if completion is None:raise InvalidTransition("COMPLETED requires an explicit evidence assessment")
            failures=completion.failures()
            if failures:raise InvalidTransition("completion gate failed: "+"; ".join(failures))
            if not manifest_ref:raise InvalidTransition("COMPLETED requires completion_manifest_ref")
            self._require_verified_completion_manifest(task_id,manifest_ref)
            refs=tuple(dict.fromkeys((*refs,*completion.criteria_evidence_refs)))
        now=utc_now(); prior_active=task["prior_active_state"]
        if target in {TaskState.BLOCKED,TaskState.PAUSED}:prior_active=source.value
        elif source in {TaskState.BLOCKED,TaskState.PAUSED}:prior_active=None
        termination=reason if target in TERMINAL_STATES else None; next_blocker=task["blocker_ref"] if blocker_ref is _UNSET else blocker_ref
        with self.store.connection:
            cursor=self.store.connection.execute("""UPDATE tasks SET state=?,prior_active_state=?,resume_checkpoint_ref=?,evidence_refs=?,artifact_refs=?,approval_refs=?,excluded_scope=?,plan_ref=?,plan_revision=?,context_manifest_ref=?,authority_state=?,active_step_ref=?,blocker_ref=?,completion_manifest_ref=?,revision=revision+1,updated_at=?,termination_reason=? WHERE task_id=? AND revision=?""",(target,prior_active,resume_checkpoint_ref or task["resume_checkpoint_ref"],json.dumps(refs),json.dumps(artifacts),json.dumps(approvals),json.dumps(exclusions),plan_ref if plan_ref is not None else task["plan_ref"],plan_revision if plan_revision is not None else task["plan_revision"],context_manifest_ref if context_manifest_ref is not None else task["context_manifest_ref"],authority_state if authority_state is not None else task["authority_state"],active_step_ref if active_step_ref is not None else task["active_step_ref"],next_blocker,manifest_ref,now,termination,task_id,expected_revision))
            if cursor.rowcount!=1:raise ConcurrencyConflict("task changed during transition")
            self._append_event(task_id,f"task.{target.value.lower()}",actor,reason,source,target,correlation_ref or task_id,causal_ref,payload)
        return self.store.fetch_task(task_id)
    def recover(self,task_id,assessment,actor,reason,expected_revision):
        task=self.store.fetch_task(task_id); source=TaskState(task["state"])
        if source in TERMINAL_STATES:raise InvalidTransition("terminal Tasks cannot recover in place")
        recovering=self.transition(task_id,TaskState.RECOVERING,actor,reason,expected_revision,payload={"command_replayed":False}); target=assessment.next_state()
        return self.transition(task_id,target,actor,"recovery assessment reconciled durable and external state",recovering["revision"],evidence_refs=assessment.evidence_refs,payload={"command_replayed":False,"effect_state":assessment.effect_state,"decision_ref":assessment.decision_ref})
    @staticmethod
    def _guard_transition(source,target,task,checkpoint):
        if source in TERMINAL_STATES:raise InvalidTransition(f"{source} is terminal")
        if target is TaskState.RECOVERING:return
        allowed=set(PRIMARY_NEXT.get(source,set()))|set(CONTROL_FROM.get(source,set()))
        if source not in {TaskState.BLOCKED,TaskState.PAUSED,TaskState.RECOVERING}:allowed|={TaskState.BLOCKED,TaskState.PAUSED,TaskState.FAILED,TaskState.CANCELLED}
        if target not in allowed:raise InvalidTransition(f"invalid transition {source} -> {target}")
        if source in {TaskState.BLOCKED,TaskState.PAUSED} and target.value!=task["prior_active_state"] and target not in {TaskState.CANCELLED,TaskState.FAILED}:raise InvalidTransition("control state may only resume its recorded active path")
        if target is TaskState.PAUSED and not (checkpoint or task["resume_checkpoint_ref"]):raise InvalidTransition("PAUSED requires a resume checkpoint")
    def _append_event(self,task_id,event_type,actor,reason,prior,new,correlation,causal,payload):
        event_id=str(uuid.uuid4()); self.store.connection.execute("INSERT INTO runtime_events(event_id,task_id,event_type,actor,reason,prior_state,new_state,occurred_at,correlation_ref,causal_ref,payload,schema_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,'0.1.0')",(event_id,task_id,event_type,actor,reason,prior.value if prior else None,new.value,utc_now(),correlation,causal,json.dumps(payload,sort_keys=True))); return event_id
