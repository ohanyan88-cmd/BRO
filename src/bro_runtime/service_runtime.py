"""Persistent scheduler/worker runtime for canonical BRO Tasks.

The service owns wake-up, durable queueing, leases and restart recovery. It does
not grant authority: work is handed to a governed processor which must use the
canonical MIND/IMMUNE/HANDS/evidence path and returns only a terminal/blocker
outcome for the same Task reference.
"""
from __future__ import annotations
import sqlite3,time,uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from .automation import AutomationDispatcher
from .task_runtime import TaskState,utc_now

class ServiceRejected(RuntimeError): pass
class WorkState(StrEnum): READY="READY"; LEASED="LEASED"; DONE="DONE"; BLOCKED="BLOCKED"; FAILED="FAILED"
@dataclass(frozen=True)
class WorkItem:
    work_id:str; task_ref:str; state:WorkState; available_at:str; lease_owner:str|None; lease_until:float|None; attempt:int; revision:int

class SQLiteWorkQueue:
    def __init__(self,connection:sqlite3.Connection):
        self.connection=connection; connection.row_factory=sqlite3.Row
        connection.executescript("""CREATE TABLE IF NOT EXISTS service_work(work_id TEXT PRIMARY KEY,task_ref TEXT NOT NULL UNIQUE,state TEXT NOT NULL,available_at TEXT NOT NULL,lease_owner TEXT,lease_until REAL,attempt INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 1,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);CREATE INDEX IF NOT EXISTS service_work_ready ON service_work(state,available_at);""")
    def _item(self,row): return WorkItem(row['work_id'],row['task_ref'],WorkState(row['state']),row['available_at'],row['lease_owner'],row['lease_until'],row['attempt'],row['revision'])
    def enqueue(self,task_ref:str,*,available_at:str|None=None)->WorkItem:
        now=utc_now(); due=available_at or now
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO service_work(work_id,task_ref,state,available_at,created_at,updated_at) VALUES (?,?, 'READY',?,?,?)",(f'work:{uuid.uuid4()}',task_ref,due,now,now))
        return self.fetch(task_ref)
    def fetch(self,task_ref:str)->WorkItem:
        row=self.connection.execute("SELECT * FROM service_work WHERE task_ref=?",(task_ref,)).fetchone()
        if row is None: raise ServiceRejected('work item does not exist')
        return self._item(row)
    def recover_expired(self,*,now_epoch:float)->int:
        with self.connection:
            cur=self.connection.execute("UPDATE service_work SET state='READY',lease_owner=NULL,lease_until=NULL,revision=revision+1,updated_at=? WHERE state='LEASED' AND lease_until<=?",(utc_now(),now_epoch))
        return cur.rowcount
    def claim(self,worker_id:str,*,now_epoch:float,lease_seconds:float=30)->WorkItem|None:
        if lease_seconds<=0: raise ServiceRejected('lease_seconds must be positive')
        self.recover_expired(now_epoch=now_epoch)
        with self.connection:
            row=self.connection.execute("SELECT * FROM service_work WHERE state='READY' AND available_at<=? ORDER BY available_at,work_id LIMIT 1",(utc_now(),)).fetchone()
            if row is None:return None
            cur=self.connection.execute("UPDATE service_work SET state='LEASED',lease_owner=?,lease_until=?,attempt=attempt+1,revision=revision+1,updated_at=? WHERE work_id=? AND revision=? AND state='READY'",(worker_id,now_epoch+lease_seconds,utc_now(),row['work_id'],row['revision']))
            if cur.rowcount!=1:return None
        return self.fetch(row['task_ref'])
    def settle(self,item:WorkItem,state:WorkState,*,error:str|None=None)->WorkItem:
        if state not in {WorkState.DONE,WorkState.BLOCKED,WorkState.FAILED}: raise ServiceRejected('invalid settled state')
        with self.connection:
            cur=self.connection.execute("UPDATE service_work SET state=?,lease_owner=NULL,lease_until=NULL,last_error=?,revision=revision+1,updated_at=? WHERE work_id=? AND revision=? AND state='LEASED'",(state,error,utc_now(),item.work_id,item.revision))
            if cur.rowcount!=1: raise ServiceRejected('stale or unleased work item')
        return self.fetch(item.task_ref)

class BROServiceRuntime:
    """Long-lived composition of automation dispatch, durable queue and workers."""
    def __init__(self,dispatcher:AutomationDispatcher,queue:SQLiteWorkQueue,processor:Callable[[str],TaskState]): self.dispatcher=dispatcher; self.queue=queue; self.processor=processor
    def tick(self,*,now:str,worker_id:str='bro-worker',now_epoch:float|None=None,lease_seconds:float=30)->WorkItem|None:
        for occurrence in self.dispatcher.tick(now=now):
            if occurrence.task_ref:self.queue.enqueue(occurrence.task_ref)
        epoch=time.time() if now_epoch is None else now_epoch
        item=self.queue.claim(worker_id,now_epoch=epoch,lease_seconds=lease_seconds)
        if item is None:return None
        try: outcome=TaskState(self.processor(item.task_ref))
        except Exception as exc:
            return self.queue.settle(item,WorkState.FAILED,error=type(exc).__name__)
        if outcome is TaskState.BLOCKED:return self.queue.settle(item,WorkState.BLOCKED)
        if outcome in {TaskState.COMPLETED,TaskState.CANCELLED}:return self.queue.settle(item,WorkState.DONE)
        if outcome is TaskState.FAILED:return self.queue.settle(item,WorkState.FAILED)
        raise ServiceRejected('governed processor must run the Task to a terminal state or blocker')
    def run(self,*,now:Callable[[],str]=utc_now,sleep:Callable[[float],None]=time.sleep,should_stop:Callable[[],bool]=lambda:False,poll_seconds:float=1.0,worker_id:str='bro-worker')->None:
        if poll_seconds<=0:raise ServiceRejected('poll_seconds must be positive')
        while not should_stop(): self.tick(now=now(),worker_id=worker_id); sleep(poll_seconds)
