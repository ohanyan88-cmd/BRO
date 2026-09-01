"""NERVOUS SYSTEM-owned durable Step and ContextManifest records."""
from __future__ import annotations
import json, sqlite3
from dataclasses import asdict, dataclass

class ReferenceRejected(ValueError): pass

@dataclass(frozen=True)
class Step:
    step_id:str; plan_ref:str; plan_revision:int; purpose:str; dependencies:tuple[str,...]; required_capabilities:tuple[str,...]; expected_output:str; authority_class:str; verification_requirement:str; retry_policy:str; version:int=1

@dataclass(frozen=True)
class ContextEntry:
    source_ref:str; scope:str; authority:str; freshness:str; trust_state:str; sensitivity:str; inclusion_reason:str; isolation_boundary:str

@dataclass(frozen=True)
class ContextManifest:
    manifest_id:str; task_ref:str; assembled_at:str; isolation_boundary:str; entries:tuple[ContextEntry,...]; excluded_refs:tuple[str,...]; version:int=1

class ReferenceStore:
    def __init__(self, connection:sqlite3.Connection):
        self.connection=connection; self.connection.row_factory=sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS plan_steps(step_id TEXT NOT NULL,version INTEGER NOT NULL,plan_ref TEXT NOT NULL,plan_revision INTEGER NOT NULL,body TEXT NOT NULL,PRIMARY KEY(step_id,version));
        CREATE TABLE IF NOT EXISTS context_manifests(manifest_id TEXT NOT NULL,version INTEGER NOT NULL,task_ref TEXT NOT NULL,isolation_boundary TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(manifest_id,version));""")
    def put_step(self, step:Step):
        if step.step_id in step.dependencies: raise ReferenceRejected("Step cannot depend on itself")
        with self.connection:self.connection.execute("INSERT INTO plan_steps VALUES (?,?,?,?,?)",(step.step_id,step.version,step.plan_ref,step.plan_revision,json.dumps(asdict(step),sort_keys=True)))
        return step
    def put_context(self, manifest:ContextManifest):
        if any(e.isolation_boundary != manifest.isolation_boundary for e in manifest.entries): raise ReferenceRejected("Context entry crosses manifest isolation boundary")
        with self.connection:self.connection.execute("INSERT INTO context_manifests VALUES (?,?,?,?,?)",(manifest.manifest_id,manifest.version,manifest.task_ref,manifest.isolation_boundary,json.dumps(asdict(manifest),sort_keys=True)))
        return manifest
    def step(self, step_id:str):
        row=self.connection.execute("SELECT body FROM plan_steps WHERE step_id=? ORDER BY version DESC LIMIT 1",(step_id,)).fetchone()
        if row is None: raise ReferenceRejected(f"unknown Step: {step_id}")
        d=json.loads(row['body']); d['dependencies']=tuple(d['dependencies']); d['required_capabilities']=tuple(d['required_capabilities']); return Step(**d)
    def context(self, manifest_id:str):
        row=self.connection.execute("SELECT body FROM context_manifests WHERE manifest_id=? ORDER BY version DESC LIMIT 1",(manifest_id,)).fetchone()
        if row is None: raise ReferenceRejected(f"unknown ContextManifest: {manifest_id}")
        d=json.loads(row['body']); d['entries']=tuple(ContextEntry(**e) for e in d['entries']); d['excluded_refs']=tuple(d['excluded_refs']); return ContextManifest(**d)
