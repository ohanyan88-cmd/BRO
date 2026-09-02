"""Durable production control-plane records for deployment, service health and acceptance."""
from __future__ import annotations
import json, sqlite3, uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from .acceptance_runtime import AcceptanceRun, AcceptanceVerdict
from .deployment_runtime import DeploymentResult, ReleaseState
from .task_runtime import utc_now

class ProductionControlRejected(RuntimeError): pass
class ProductionState(StrEnum): CANDIDATE='CANDIDATE'; ACTIVE='ACTIVE'; BLOCKED='BLOCKED'
@dataclass(frozen=True)
class ServiceHeartbeat:
    service_id:str; instance_id:str; revision:str; state:str; observed_at:str; evidence_ref:str
@dataclass(frozen=True)
class ProductionRelease:
    record_id:str; release_ref:str; environment:str; artifact_ref:str; source_revision:str; deployment_evidence_ref:str; acceptance_run_ref:str; state:ProductionState; created_at:str

class ProductionControlPlane:
    """Persist operational truth; never infer production readiness from deploy acknowledgement alone."""
    def __init__(self, connection: sqlite3.Connection):
        self.connection=connection; connection.row_factory=sqlite3.Row
        connection.executescript("""
        CREATE TABLE IF NOT EXISTS production_heartbeats(service_id TEXT NOT NULL,instance_id TEXT NOT NULL,revision TEXT NOT NULL,state TEXT NOT NULL,observed_at TEXT NOT NULL,evidence_ref TEXT NOT NULL,PRIMARY KEY(service_id,instance_id,observed_at));
        CREATE TABLE IF NOT EXISTS production_releases(record_id TEXT PRIMARY KEY,release_ref TEXT NOT NULL,environment TEXT NOT NULL,artifact_ref TEXT NOT NULL,source_revision TEXT NOT NULL,deployment_evidence_ref TEXT NOT NULL,acceptance_run_ref TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS production_active_environment ON production_releases(environment) WHERE state='ACTIVE';
        """)
    def heartbeat(self, *, service_id:str, instance_id:str, revision:str, state:str, evidence_ref:str, observed_at:str|None=None)->ServiceHeartbeat:
        if not all(x.strip() for x in (service_id,instance_id,revision,state,evidence_ref)): raise ProductionControlRejected('heartbeat identity, revision, state and evidence are required')
        if state not in {'HEALTHY','DEGRADED','BLOCKED'}: raise ProductionControlRejected('invalid heartbeat state')
        hb=ServiceHeartbeat(service_id,instance_id,revision,state,observed_at or utc_now(),evidence_ref)
        with self.connection:self.connection.execute('INSERT INTO production_heartbeats VALUES (?,?,?,?,?,?)',(hb.service_id,hb.instance_id,hb.revision,hb.state,hb.observed_at,hb.evidence_ref))
        return hb
    def latest_heartbeats(self, service_id:str)->tuple[ServiceHeartbeat,...]:
        rows=self.connection.execute("SELECT h.* FROM production_heartbeats h JOIN (SELECT instance_id,MAX(observed_at) observed_at FROM production_heartbeats WHERE service_id=? GROUP BY instance_id) x ON h.instance_id=x.instance_id AND h.observed_at=x.observed_at WHERE h.service_id=? ORDER BY h.instance_id",(service_id,service_id)).fetchall()
        return tuple(ServiceHeartbeat(**dict(r)) for r in rows)
    def activate(self, *, deployment:DeploymentResult, artifact_ref:str, source_revision:str, acceptance:AcceptanceRun)->ProductionRelease:
        if deployment.state is not ReleaseState.PROMOTED: raise ProductionControlRejected('deployment must be independently read-back as PROMOTED')
        if acceptance.verdict is not AcceptanceVerdict.PASS: raise ProductionControlRejected('production activation requires PASS acceptance')
        if not any(r.passed and r.assurance in {'external_system','production'} for r in acceptance.results): raise ProductionControlRejected('production activation requires passing external evidence')
        if not all(x.strip() for x in (artifact_ref,source_revision,deployment.evidence_ref)): raise ProductionControlRejected('release provenance and deployment evidence are required')
        record=ProductionRelease(f'production-release:{uuid.uuid4()}',deployment.release_ref,deployment.environment,artifact_ref,source_revision,deployment.evidence_ref,acceptance.run_id,ProductionState.ACTIVE,utc_now())
        with self.connection:
            self.connection.execute("UPDATE production_releases SET state='BLOCKED' WHERE environment=? AND state='ACTIVE'",(record.environment,))
            self.connection.execute('INSERT INTO production_releases VALUES (?,?,?,?,?,?,?,?,?)',(record.record_id,record.release_ref,record.environment,record.artifact_ref,record.source_revision,record.deployment_evidence_ref,record.acceptance_run_ref,record.state,record.created_at))
        return record
    def active(self, environment:str)->ProductionRelease:
        row=self.connection.execute("SELECT * FROM production_releases WHERE environment=? AND state='ACTIVE' ORDER BY created_at DESC LIMIT 1",(environment,)).fetchone()
        if row is None: raise ProductionControlRejected('no active production release')
        # SQLite returns the state as text; rebuild the enum so a ledger readback is the
        # same type as the record activate() returned and identity comparison stays true.
        fields=dict(row); fields['state']=ProductionState(fields['state'])
        return ProductionRelease(**fields)
