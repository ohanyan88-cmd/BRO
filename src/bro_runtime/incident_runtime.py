"""Durable operational incidents with acknowledgement and recovery evidence."""
from __future__ import annotations
import sqlite3,uuid
from dataclasses import dataclass
from enum import StrEnum
from .task_runtime import utc_now
class IncidentRejected(RuntimeError): pass
class IncidentState(StrEnum): OPEN='OPEN'; ACKNOWLEDGED='ACKNOWLEDGED'; RESOLVED='RESOLVED'
@dataclass(frozen=True)
class Incident:
    incident_id:str; source_ref:str; severity:str; summary:str; state:IncidentState; owner:str|None; recovery_evidence_ref:str|None
class IncidentRuntime:
    def __init__(self,connection:sqlite3.Connection):
        self.connection=connection; connection.row_factory=sqlite3.Row
        connection.execute("CREATE TABLE IF NOT EXISTS incidents(incident_id TEXT PRIMARY KEY,source_ref TEXT NOT NULL,severity TEXT NOT NULL,summary TEXT NOT NULL,state TEXT NOT NULL,owner TEXT,recovery_evidence_ref TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,resolved_at TEXT)")
    def _get(self,i):
        r=self.connection.execute('SELECT * FROM incidents WHERE incident_id=?',(i,)).fetchone()
        if r is None: raise IncidentRejected('unknown incident')
        return Incident(r['incident_id'],r['source_ref'],r['severity'],r['summary'],IncidentState(r['state']),r['owner'],r['recovery_evidence_ref'])
    def open(self,*,source_ref:str,severity:str,summary:str)->Incident:
        if severity not in {'P1','P2','P3','P4'}: raise IncidentRejected('invalid severity')
        now=utc_now(); i=f'incident:{uuid.uuid4()}'
        with self.connection:self.connection.execute("INSERT INTO incidents VALUES (?,?,?,?,'OPEN',NULL,NULL,?,?,NULL)",(i,source_ref,severity,summary,now,now))
        return self._get(i)
    def acknowledge(self,incident_id:str,*,owner:str)->Incident:
        if not owner.strip(): raise IncidentRejected('owner required')
        with self.connection:
            c=self.connection.execute("UPDATE incidents SET state='ACKNOWLEDGED',owner=?,updated_at=? WHERE incident_id=? AND state='OPEN'",(owner,utc_now(),incident_id))
            if c.rowcount!=1: raise IncidentRejected('incident is not open')
        return self._get(incident_id)
    def resolve(self,incident_id:str,*,owner:str,recovery_evidence_ref:str)->Incident:
        if not recovery_evidence_ref.strip(): raise IncidentRejected('recovery evidence required')
        now=utc_now()
        with self.connection:
            c=self.connection.execute("UPDATE incidents SET state='RESOLVED',recovery_evidence_ref=?,updated_at=?,resolved_at=? WHERE incident_id=? AND state='ACKNOWLEDGED' AND owner=?",(recovery_evidence_ref,now,now,incident_id,owner))
            if c.rowcount!=1: raise IncidentRejected('only owning responder may resolve acknowledged incident')
        return self._get(incident_id)
