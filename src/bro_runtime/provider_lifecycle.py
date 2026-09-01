"""Durable provider connection health and outage circuit state."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass,replace
from enum import StrEnum
from .task_runtime import utc_now
from .provider_adapters import ProviderAdapter
class ProviderConnectionState(StrEnum): HEALTHY='HEALTHY'; DEGRADED='DEGRADED'; UNAVAILABLE='UNAVAILABLE'
class ProviderLifecycleRejected(RuntimeError):pass
@dataclass(frozen=True)
class ProviderLifecycle:
    provider:str; adapter_id:str; version:str; state:ProviderConnectionState; consecutive_failures:int; last_error_kind:str|None; updated_at:str
class ProviderLifecycleStore:
    def __init__(self,connection:sqlite3.Connection,failure_threshold:int=3):
        if failure_threshold<1:raise ProviderLifecycleRejected('failure_threshold must be positive')
        self.connection=connection; self.failure_threshold=failure_threshold; connection.row_factory=sqlite3.Row
        connection.execute("CREATE TABLE IF NOT EXISTS provider_lifecycle(provider TEXT NOT NULL,adapter_id TEXT NOT NULL,version TEXT NOT NULL,state TEXT NOT NULL,consecutive_failures INTEGER NOT NULL,last_error_kind TEXT,updated_at TEXT NOT NULL,PRIMARY KEY(provider,adapter_id,version))")
    def register(self,provider:str,adapter_id:str,version:str)->ProviderLifecycle:
        if not all((provider,adapter_id,version)):raise ProviderLifecycleRejected('provider route identity is required')
        with self.connection:self.connection.execute("INSERT OR IGNORE INTO provider_lifecycle VALUES (?,?,?,'HEALTHY',0,NULL,?)",(provider,adapter_id,version,utc_now()))
        return self.fetch(provider,adapter_id,version)
    def fetch(self,provider,adapter_id,version)->ProviderLifecycle:
        row=self.connection.execute("SELECT * FROM provider_lifecycle WHERE provider=? AND adapter_id=? AND version=?",(provider,adapter_id,version)).fetchone()
        if row is None:raise ProviderLifecycleRejected('provider route is not registered')
        return ProviderLifecycle(row['provider'],row['adapter_id'],row['version'],ProviderConnectionState(row['state']),row['consecutive_failures'],row['last_error_kind'],row['updated_at'])
    def assert_available(self,provider,adapter_id,version)->None:
        if self.fetch(provider,adapter_id,version).state is ProviderConnectionState.UNAVAILABLE:raise ProviderLifecycleRejected('provider route is unavailable')
    def success(self,provider,adapter_id,version)->ProviderLifecycle:
        with self.connection:self.connection.execute("UPDATE provider_lifecycle SET state='HEALTHY',consecutive_failures=0,last_error_kind=NULL,updated_at=? WHERE provider=? AND adapter_id=? AND version=?",(utc_now(),provider,adapter_id,version))
        return self.fetch(provider,adapter_id,version)
    def failure(self,provider,adapter_id,version,error_kind:str)->ProviderLifecycle:
        current=self.fetch(provider,adapter_id,version); failures=current.consecutive_failures+1; state='UNAVAILABLE' if failures>=self.failure_threshold else 'DEGRADED'
        with self.connection:self.connection.execute("UPDATE provider_lifecycle SET state=?,consecutive_failures=?,last_error_kind=?,updated_at=? WHERE provider=? AND adapter_id=? AND version=?",(state,failures,error_kind,utc_now(),provider,adapter_id,version))
        return self.fetch(provider,adapter_id,version)
    def guard(self,adapter:ProviderAdapter)->ProviderAdapter:
        self.register(adapter.provider,adapter.adapter_id,adapter.version)
        def invoke(inputs):
            self.assert_available(adapter.provider,adapter.adapter_id,adapter.version)
            try: result=adapter.invoke(inputs)
            except Exception as exc:
                self.failure(adapter.provider,adapter.adapter_id,adapter.version,type(exc).__name__);raise
            self.success(adapter.provider,adapter.adapter_id,adapter.version);return result
        return replace(adapter,invoke=invoke)
