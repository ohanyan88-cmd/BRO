"""Durable cognition records owned only by MIND."""
from __future__ import annotations
import json, sqlite3, uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

def utc_now(): return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

class KnowledgeState(StrEnum):
    CONFIRMED="CONFIRMED"; DERIVED="DERIVED"; UNVERIFIED="UNVERIFIED"; UNKNOWN="UNKNOWN"; CONFLICTED="CONFLICTED"
class MindRejected(ValueError): pass

@dataclass(frozen=True)
class Goal:
    goal_id:str; intent_ref:str; desired_outcome:str; interpreted_scope:tuple[str,...]; constraints:tuple[str,...]; assumptions:tuple[str,...]; uncertainty:KnowledgeState; success_conditions:tuple[str,...]; non_goals:tuple[str,...]; authority_basis:str; materiality:str; risk_class:str; created_at:str; version:int
@dataclass(frozen=True)
class Decision:
    decision_id:str; goal_ref:str; question:str; conclusion:Any; rationale:str; evidence_refs:tuple[str,...]; assumptions:tuple[str,...]; alternatives:tuple[Any,...]; authority_basis:str; uncertainty:KnowledgeState; reversibility:str; decided_at:str; version:int
@dataclass(frozen=True)
class Plan:
    plan_id:str; goal_ref:str; decision_ref:str; revision:int; step_refs:tuple[str,...]; checkpoints:tuple[str,...]; recovery_options:tuple[str,...]; completion_path:tuple[str,...]; reason:str; supersedes:str|None; created_at:str

class SQLiteMindStore:
    """Append-only version history for MIND-owned canonical records."""
    def __init__(self,path:str|Path=":memory:"):
        self.connection=sqlite3.connect(str(path)); self.connection.row_factory=sqlite3.Row; self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS mind_goals(goal_id TEXT NOT NULL,version INTEGER NOT NULL,record TEXT NOT NULL,PRIMARY KEY(goal_id,version));
        CREATE TABLE IF NOT EXISTS mind_decisions(decision_id TEXT NOT NULL,version INTEGER NOT NULL,goal_ref TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(decision_id,version));
        CREATE TABLE IF NOT EXISTS mind_plans(plan_id TEXT NOT NULL,revision INTEGER NOT NULL,goal_ref TEXT NOT NULL,record TEXT NOT NULL,PRIMARY KEY(plan_id,revision));""")
    def close(self): self.connection.close()
    @staticmethod
    def _dump(v): return json.dumps(asdict(v),separators=(",",":"),sort_keys=True)
    def put_goal(self,v):
        with self.connection:self.connection.execute("INSERT INTO mind_goals VALUES (?,?,?)",(v.goal_id,v.version,self._dump(v)))
    def put_decision(self,v):
        with self.connection:self.connection.execute("INSERT INTO mind_decisions VALUES (?,?,?,?)",(v.decision_id,v.version,v.goal_ref,self._dump(v)))
    def put_plan(self,v):
        with self.connection:self.connection.execute("INSERT INTO mind_plans VALUES (?,?,?,?)",(v.plan_id,v.revision,v.goal_ref,self._dump(v)))
    def _row(self,table,keycol,key,vercol,version):
        if version is None:return self.connection.execute(f"SELECT record FROM {table} WHERE {keycol}=? ORDER BY {vercol} DESC LIMIT 1",(key,)).fetchone()
        return self.connection.execute(f"SELECT record FROM {table} WHERE {keycol}=? AND {vercol}=?",(key,version)).fetchone()
    def goal(self,key,version=None):
        r=self._row("mind_goals","goal_id",key,"version",version)
        if r is None:raise KeyError(key)
        d=json.loads(r["record"]); d.update(interpreted_scope=tuple(d["interpreted_scope"]),constraints=tuple(d["constraints"]),assumptions=tuple(d["assumptions"]),success_conditions=tuple(d["success_conditions"]),non_goals=tuple(d["non_goals"]),uncertainty=KnowledgeState(d["uncertainty"])); return Goal(**d)
    def decision(self,key,version=None):
        r=self._row("mind_decisions","decision_id",key,"version",version)
        if r is None:raise KeyError(key)
        d=json.loads(r["record"]); d.update(evidence_refs=tuple(d["evidence_refs"]),assumptions=tuple(d["assumptions"]),alternatives=tuple(d["alternatives"]),uncertainty=KnowledgeState(d["uncertainty"])); return Decision(**d)
    def plan(self,key,revision=None):
        r=self._row("mind_plans","plan_id",key,"revision",revision)
        if r is None:raise KeyError(key)
        d=json.loads(r["record"]); d.update(step_refs=tuple(d["step_refs"]),checkpoints=tuple(d["checkpoints"]),recovery_options=tuple(d["recovery_options"]),completion_path=tuple(d["completion_path"])); return Plan(**d)

class MindRuntime:
    def __init__(self,store):self.store=store
    @staticmethod
    def _text(label,value):
        value=value.strip()
        if not value:raise MindRejected(f"{label} must not be empty")
        return value
    @staticmethod
    def _refs(step_refs):
        refs=tuple(dict.fromkeys(x.strip() for x in step_refs if x and x.strip()))
        if not refs:raise MindRejected("Plan requires at least one Step reference")
        return refs
    def form_goal(self,*,intent_ref,desired_outcome,interpreted_scope,success_conditions,authority_basis,materiality,risk_class,constraints=(),assumptions=(),uncertainty=KnowledgeState.UNVERIFIED,non_goals=(),goal_id=None):
        success=tuple(dict.fromkeys(x.strip() for x in success_conditions if x.strip()))
        if not success:raise MindRejected("Goal requires at least one success condition")
        g=Goal(goal_id or f"goal:{uuid.uuid4()}",self._text("intent_ref",intent_ref),self._text("desired_outcome",desired_outcome),tuple(dict.fromkeys(interpreted_scope)),tuple(dict.fromkeys(constraints)),tuple(dict.fromkeys(assumptions)),KnowledgeState(uncertainty),success,tuple(dict.fromkeys(non_goals)),self._text("authority_basis",authority_basis),self._text("materiality",materiality),self._text("risk_class",risk_class),utc_now(),1); self.store.put_goal(g); return g
    def decide(self,*,goal_ref,question,conclusion,rationale,authority_basis,uncertainty,reversibility,evidence_refs=(),assumptions=(),alternatives=(),decision_id=None):
        if reversibility not in {"REVERSIBLE","PARTIALLY_REVERSIBLE","DIFFICULT","IRREVERSIBLE","UNKNOWN"}:raise MindRejected(f"invalid reversibility {reversibility!r}")
        d=Decision(decision_id or f"decision:{uuid.uuid4()}",self._text("goal_ref",goal_ref),self._text("question",question),conclusion,self._text("rationale",rationale),tuple(dict.fromkeys(evidence_refs)),tuple(dict.fromkeys(assumptions)),tuple(alternatives),self._text("authority_basis",authority_basis),KnowledgeState(uncertainty),reversibility,utc_now(),1); self.store.put_decision(d); return d
    def plan(self,*,goal_ref,decision_ref,step_refs,checkpoints,recovery_options,completion_path,reason,plan_id=None):
        p=Plan(plan_id or f"plan:{uuid.uuid4()}",self._text("goal_ref",goal_ref),self._text("decision_ref",decision_ref),1,self._refs(step_refs),tuple(dict.fromkeys(checkpoints)),tuple(dict.fromkeys(recovery_options)),tuple(dict.fromkeys(completion_path)),self._text("reason",reason),None,utc_now()); self.store.put_plan(p); return p
    def replan(self,plan_id,*,step_refs,reason,decision_ref=None,checkpoints=None,recovery_options=None,completion_path=None):
        old=self.store.plan(plan_id); p=Plan(old.plan_id,old.goal_ref,decision_ref or old.decision_ref,old.revision+1,self._refs(step_refs),old.checkpoints if checkpoints is None else tuple(dict.fromkeys(checkpoints)),old.recovery_options if recovery_options is None else tuple(dict.fromkeys(recovery_options)),old.completion_path if completion_path is None else tuple(dict.fromkeys(completion_path)),self._text("reason",reason),f"{old.plan_id}@{old.revision}",utc_now()); self.store.put_plan(p); return p
