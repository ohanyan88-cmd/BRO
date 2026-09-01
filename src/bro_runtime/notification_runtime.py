"""Provider-independent durable notification delivery with idempotent receipts."""
from __future__ import annotations
import json,sqlite3,uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable
from .task_runtime import utc_now

class NotificationRejected(RuntimeError): pass
class DeliveryState(StrEnum): PENDING='PENDING'; SENT='SENT'; FAILED='FAILED'
@dataclass(frozen=True)
class Notification:
    notification_id:str; task_ref:str; channel:str; recipient:str; body:str; idempotency_key:str; state:DeliveryState
class NotificationRuntime:
    def __init__(self,connection:sqlite3.Connection):
        self.connection=connection; connection.row_factory=sqlite3.Row
        connection.execute("CREATE TABLE IF NOT EXISTS notifications(notification_id TEXT PRIMARY KEY,task_ref TEXT NOT NULL,channel TEXT NOT NULL,recipient TEXT NOT NULL,body TEXT NOT NULL,idempotency_key TEXT NOT NULL UNIQUE,state TEXT NOT NULL,receipt TEXT,last_error TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)")
    def create(self,*,task_ref:str,channel:str,recipient:str,body:str,idempotency_key:str)->Notification:
        if not all(x.strip() for x in (task_ref,channel,recipient,body,idempotency_key)): raise NotificationRejected('notification fields are required')
        now=utc_now()
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,?,?,?,?,'PENDING',NULL,NULL,?,?)",(f'notification:{uuid.uuid4()}',task_ref,channel,recipient,body,idempotency_key,now,now))
        return self.fetch(idempotency_key)
    def fetch(self,key:str)->Notification:
        row=self.connection.execute('SELECT * FROM notifications WHERE idempotency_key=?',(key,)).fetchone()
        if row is None: raise NotificationRejected('unknown notification')
        return Notification(row['notification_id'],row['task_ref'],row['channel'],row['recipient'],row['body'],row['idempotency_key'],DeliveryState(row['state']))
    def deliver(self,key:str,sender:Callable[[Notification],dict])->dict:
        item=self.fetch(key)
        row=self.connection.execute('SELECT receipt FROM notifications WHERE idempotency_key=?',(key,)).fetchone()
        if item.state is DeliveryState.SENT: return json.loads(row['receipt'])
        try: receipt=sender(item)
        except Exception as exc:
            with self.connection:self.connection.execute("UPDATE notifications SET state='FAILED',last_error=?,updated_at=? WHERE idempotency_key=?",(type(exc).__name__,utc_now(),key))
            raise NotificationRejected('notification delivery failed') from exc
        if not isinstance(receipt,dict) or not receipt.get('provider_ref'): raise NotificationRejected('sender must return provider receipt')
        with self.connection:self.connection.execute("UPDATE notifications SET state='SENT',receipt=?,last_error=NULL,updated_at=? WHERE idempotency_key=?",(json.dumps(receipt,sort_keys=True),utc_now(),key))
        return receipt
