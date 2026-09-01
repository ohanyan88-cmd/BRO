"""Verified restore drills for BRO SQLite runtime state."""
from __future__ import annotations
import hashlib,sqlite3
from dataclasses import dataclass
from pathlib import Path
from .task_runtime import utc_now

class RestoreRejected(RuntimeError): pass
@dataclass(frozen=True)
class RestoreReceipt:
    source_path:str; source_sha256:str; integrity_ok:bool; restored_tables:tuple[str,...]; created_at:str

class RestoreRuntime:
    """Restores a backup into an isolated database and verifies integrity before promotion."""
    def verify(self,path:str|Path)->RestoreReceipt:
        source=Path(path)
        if not source.is_file(): raise RestoreRejected('backup does not exist')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        connection=sqlite3.connect(str(source))
        try:
            rows=connection.execute('PRAGMA integrity_check').fetchall()
            ok=bool(rows) and all(str(row[0]).lower()=='ok' for row in rows)
            tables=tuple(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        finally: connection.close()
        if not ok: raise RestoreRejected('backup integrity verification failed')
        if not tables: raise RestoreRejected('backup contains no runtime tables')
        return RestoreReceipt(str(source),digest,True,tables,utc_now())
    def drill(self,path:str|Path, target:str|Path)->RestoreReceipt:
        receipt=self.verify(path); destination=Path(target); destination.parent.mkdir(parents=True,exist_ok=True)
        if destination.exists(): destination.unlink()
        source=sqlite3.connect(str(path)); restored=sqlite3.connect(str(destination))
        try: source.backup(restored)
        finally: source.close(); restored.close()
        drilled=self.verify(destination)
        if drilled.source_sha256 != receipt.source_sha256: raise RestoreRejected('restore drill digest mismatch')
        return RestoreReceipt(receipt.source_path,receipt.source_sha256,True,drilled.restored_tables,utc_now())
