"""Canonical NERVOUS SYSTEM records that are referenced by Task and Assignment."""
from __future__ import annotations
import json, sqlite3
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Iterable

from .task_runtime import utc_now

class NervousRecordRejected(ValueError): pass
class StepState(StrEnum):
    PLANNED="PLANNED"; READY="READY"; ACTIVE="ACTIVE"; SUCCEEDED="SUCCEEDED"; PARTIAL="PARTIAL"; FAILED="FAILED"; BLOCKED="BLOCKED"; CANCELLED="CANCELLED"

STEP_TRANSITIONS={
    StepState.PLANNED:{StepState.READY,StepState.CANCELLED},
    StepState.READY:{StepState.ACTIVE,StepState.BLOCKED,StepState.CANCELLED},
    StepState.ACTIVE:{StepState.SUCCEEDED,StepState.PARTIAL,StepState.FAILED,StepState.BLOCKED,StepState.CANCELLED},
    StepState.BLOCKED:{StepState.READY,StepState.ACTIVE,StepState.CANCELLED},
}

@dataclass(frozen=True)
class Step:
    step_id:str; task_ref:str; plan_ref:str; plan_revision:int; purpose:str; dependencies:tuple[str,...]; required_capabilities:tuple[str,...]; expected_output:str; authority_class:str; verification_requirement:str; retry_policy:str; state:StepState; revision:int; created_at:str; updated_at:str

@dataclass(frozen=True)
class ContextEntry:
    source_ref:str; scope:str; authority:str; freshness:str; trust_state:str; sensitivity:str; inclusion_reason:str; isolation_boundary:str

@dataclass(frozen=True)
class ContextManifest:
    manifest_id:str; task_ref:str; assembled_at:str; isolation_boundary:str; entries:tuple[ContextEntry,...]; excluded_refs:tuple[str,...]; version:int

class NervousRecordStore:
    """One NERVOUS-owned durable registry for Step and Context Manifest records."""
    def __init__(self, connection: sqlite3.Connection):
        self.connection=connection; self.connection.row_factory=sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS steps(
          step_id TEXT NOT NULL, revision INTEGER NOT NULL, task_ref TEXT NOT NULL,
          plan_ref TEXT NOT NULL, plan_revision INTEGER NOT NULL, state TEXT NOT NULL,
          body TEXT NOT NULL, PRIMARY KEY(step_id,revision));
        CREATE TABLE IF NOT EXISTS context_manifests(
          manifest_id TEXT NOT NULL, version INTEGER NOT NULL, task_ref TEXT NOT NULL,
          isolation_boundary TEXT NOT NULL, body TEXT NOT NULL,
          PRIMARY KEY(manifest_id,version));
        """)
    @staticmethod
    def _text(label,value):
        value=(value or "").strip()
        if not value: raise NervousRecordRejected(f"{label} must not be empty")
        return value
    def create_step(self, *, step_id, task_ref, plan_ref, plan_revision, purpose, dependencies=(), required_capabilities=(), expected_output, authority_class, verification_requirement, retry_policy, state=StepState.PLANNED):
        if plan_revision < 1: raise NervousRecordRejected("plan_revision must be >= 1")
        deps=tuple(dict.fromkeys(dependencies))
        if step_id in deps: raise NervousRecordRejected("Step cannot depend on itself")
        now=utc_now()
        step=Step(self._text("step_id",step_id),self._text("task_ref",task_ref),self._text("plan_ref",plan_ref),plan_revision,self._text("purpose",purpose),deps,tuple(dict.fromkeys(required_capabilities)),self._text("expected_output",expected_output),self._text("authority_class",authority_class),self._text("verification_requirement",verification_requirement),self._text("retry_policy",retry_policy),StepState(state),1,now,now)
        try:
            with self.connection:self.connection.execute("INSERT INTO steps VALUES (?,?,?,?,?,?,?)",(step.step_id,step.revision,step.task_ref,step.plan_ref,step.plan_revision,str(step.state),json.dumps(asdict(step),sort_keys=True)))
        except sqlite3.IntegrityError as exc: raise NervousRecordRejected("Step records are immutable per revision") from exc
        return step
    def step(self, step_id, revision=None):
        if revision is None: row=self.connection.execute("SELECT body FROM steps WHERE step_id=? ORDER BY revision DESC LIMIT 1",(step_id,)).fetchone()
        else: row=self.connection.execute("SELECT body FROM steps WHERE step_id=? AND revision=?",(step_id,revision)).fetchone()
        if row is None: raise KeyError(step_id)
        d=json.loads(row["body"]); d.update(dependencies=tuple(d["dependencies"]),required_capabilities=tuple(d["required_capabilities"]),state=StepState(d["state"])); return Step(**d)
    def transition_step(self, step_id:str, target:StepState)->Step:
        prior=self.step(step_id); target=StepState(target)
        if target not in STEP_TRANSITIONS.get(prior.state,set()): raise NervousRecordRejected(f"invalid Step transition {prior.state} -> {target}")
        record=Step(**{**asdict(prior),"dependencies":prior.dependencies,"required_capabilities":prior.required_capabilities,"state":target,"revision":prior.revision+1,"updated_at":utc_now()})
        try:
            with self.connection:self.connection.execute("INSERT INTO steps VALUES (?,?,?,?,?,?,?)",(record.step_id,record.revision,record.task_ref,record.plan_ref,record.plan_revision,str(record.state),json.dumps(asdict(record),sort_keys=True)))
        except sqlite3.IntegrityError as exc: raise NervousRecordRejected("Step records are immutable per revision") from exc
        return record
    def create_context_manifest(self, *, manifest_id, task_ref, isolation_boundary, entries:Iterable[ContextEntry], excluded_refs=(), version=1):
        # Context references elsewhere in the canonical runtime are manifest_id-only.
        # Allowing a second version under the same id would therefore mutate the
        # meaning of an already-bound Task/Assignment without changing its ref.
        if version != 1:
            raise NervousRecordRejected("Context Manifest identity is immutable; changed context requires a new manifest_id")
        if self.connection.execute("SELECT 1 FROM context_manifests WHERE manifest_id=? LIMIT 1",(manifest_id,)).fetchone():
            raise NervousRecordRejected("Context Manifest identity is immutable; changed context requires a new manifest_id")
        boundary=self._text("isolation_boundary",isolation_boundary)
        items=tuple(entries)
        for item in items:
            if item.isolation_boundary != boundary: raise NervousRecordRejected(f"context entry {item.source_ref} crosses isolation boundary")
        manifest=ContextManifest(self._text("manifest_id",manifest_id),self._text("task_ref",task_ref),utc_now(),boundary,items,tuple(dict.fromkeys(excluded_refs)),version)
        try:
            with self.connection:self.connection.execute("INSERT INTO context_manifests VALUES (?,?,?,?,?)",(manifest.manifest_id,manifest.version,manifest.task_ref,manifest.isolation_boundary,json.dumps(asdict(manifest),sort_keys=True)))
        except sqlite3.IntegrityError as exc: raise NervousRecordRejected("Context Manifest records are immutable") from exc
        return manifest
    def context_manifest(self, manifest_id, version=None):
        if version not in {None,1}: raise NervousRecordRejected("Context Manifest identity is immutable and has no mutable version alias")
        row=self.connection.execute("SELECT body FROM context_manifests WHERE manifest_id=? AND version=1",(manifest_id,)).fetchone()
        if row is None: raise KeyError(manifest_id)
        d=json.loads(row["body"]); d["entries"]=tuple(ContextEntry(**e) for e in d["entries"]); d["excluded_refs"]=tuple(d["excluded_refs"]); return ContextManifest(**d)