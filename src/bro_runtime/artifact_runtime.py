"""Canonical HANDS-owned Artifact runtime records.

HANDS records produced artifacts and their immutable revisions. Verification is
never self-issued: a VERIFIED artifact revision must cite sufficient IMMUNE-owned
Evidence from the same project/task scope.
"""
from __future__ import annotations
import json, sqlite3, uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from .immune import EvidenceFreshness, EvidenceValidity, evidence_scope
from .task_runtime import utc_now

class ArtifactRejected(ValueError): pass

class ArtifactState(StrEnum):
    PRODUCED="PRODUCED"
    VERIFIED="VERIFIED"
    REJECTED="REJECTED"

@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id:str
    task_ref:str
    assignment_ref:str
    project_boundary:str
    artifact_type:str
    location_ref:str
    expected_contract_ref:str|None
    integrity_ref:str|None
    state:ArtifactState
    evidence_ref:str|None
    revision:int
    recorded_at:str

class ArtifactStore:
    """Append-only HANDS artifact registry with IMMUNE evidence binding."""
    def __init__(self,connection:sqlite3.Connection)->None:
        self.connection=connection; self.connection.row_factory=sqlite3.Row
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS artifacts(
          artifact_id TEXT NOT NULL, revision INTEGER NOT NULL, task_ref TEXT NOT NULL,
          assignment_ref TEXT NOT NULL, project_boundary TEXT NOT NULL, state TEXT NOT NULL,
          body TEXT NOT NULL, PRIMARY KEY(artifact_id,revision));
        """)
    @staticmethod
    def _text(label,value):
        value=(value or "").strip()
        if not value: raise ArtifactRejected(f"{label} must not be empty")
        return value
    def produce(self,*,artifact_id:str,task_ref:str,assignment_ref:str,project_boundary:str,
                artifact_type:str,location_ref:str,expected_contract_ref:str|None=None,
                integrity_ref:str|None=None)->ArtifactRecord:
        record=ArtifactRecord(self._text("artifact_id",artifact_id),self._text("task_ref",task_ref),
            self._text("assignment_ref",assignment_ref),self._text("project_boundary",project_boundary),
            self._text("artifact_type",artifact_type),self._text("location_ref",location_ref),
            expected_contract_ref,integrity_ref,ArtifactState.PRODUCED,None,1,utc_now())
        try:
            with self.connection:self.connection.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)",
                (record.artifact_id,record.revision,record.task_ref,record.assignment_ref,record.project_boundary,
                 str(record.state),json.dumps(asdict(record),sort_keys=True)))
        except sqlite3.IntegrityError as exc: raise ArtifactRejected("Artifact revisions are immutable") from exc
        return record
    def get(self,artifact_id:str,revision:int|None=None)->ArtifactRecord:
        if revision is None:
            row=self.connection.execute("SELECT body FROM artifacts WHERE artifact_id=? ORDER BY revision DESC LIMIT 1",(artifact_id,)).fetchone()
        else:
            row=self.connection.execute("SELECT body FROM artifacts WHERE artifact_id=? AND revision=?",(artifact_id,revision)).fetchone()
        if row is None: raise ArtifactRejected(f"unknown Artifact {artifact_id}")
        body=json.loads(row["body"]); body["state"]=ArtifactState(body["state"]); return ArtifactRecord(**body)
    def verify(self,artifact_id:str,evidence_ref:str)->ArtifactRecord:
        prior=self.get(artifact_id)
        if prior.state is not ArtifactState.PRODUCED: raise ArtifactRejected("only a PRODUCED Artifact may become VERIFIED")
        row=self.connection.execute("SELECT evidence_id,scope,validity,freshness FROM evidence WHERE evidence_id=?",(evidence_ref,)).fetchone()
        if row is None: raise ArtifactRejected("Artifact verification requires canonical IMMUNE Evidence")
        expected_scope=evidence_scope(prior.project_boundary,prior.task_ref)
        if row["scope"]!=expected_scope: raise ArtifactRejected("Artifact Evidence crosses the project/task boundary")
        if row["validity"]!=EvidenceValidity.VALID or row["freshness"] not in {EvidenceFreshness.CURRENT,EvidenceFreshness.AGING}:
            raise ArtifactRejected("Artifact Evidence is not sufficient")
        record=ArtifactRecord(**{**asdict(prior),"state":ArtifactState.VERIFIED,"evidence_ref":evidence_ref,
            "revision":prior.revision+1,"recorded_at":utc_now()})
        with self.connection:self.connection.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)",
            (record.artifact_id,record.revision,record.task_ref,record.assignment_ref,record.project_boundary,
             str(record.state),json.dumps(asdict(record),sort_keys=True)))
        return record
    def reject(self,artifact_id:str,evidence_ref:str|None=None)->ArtifactRecord:
        prior=self.get(artifact_id)
        if prior.state is not ArtifactState.PRODUCED: raise ArtifactRejected("only a PRODUCED Artifact may be rejected")
        record=ArtifactRecord(**{**asdict(prior),"state":ArtifactState.REJECTED,"evidence_ref":evidence_ref,
            "revision":prior.revision+1,"recorded_at":utc_now()})
        with self.connection:self.connection.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)",
            (record.artifact_id,record.revision,record.task_ref,record.assignment_ref,record.project_boundary,
             str(record.state),json.dumps(asdict(record),sort_keys=True)))
        return record
