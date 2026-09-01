"""Operational observability and SQLite safety controls for BRO runtime state."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .task_runtime import utc_now


class OperationsRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeHealth:
    state: str
    task_counts: tuple[tuple[str, int], ...]
    queue_counts: tuple[tuple[str, int], ...]
    provider_counts: tuple[tuple[str, int], ...]
    waiting_approvals: int
    integrity_ok: bool
    observed_at: str


@dataclass(frozen=True)
class BackupReceipt:
    path: str
    sha256: str
    integrity_ok: bool
    created_at: str


class RuntimeOperations:
    """Read-only health projection plus verified SQLite backup boundary."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS runtime_operations_events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT NOT NULL,detail TEXT NOT NULL,recorded_at TEXT NOT NULL)"
        )

    def _table_exists(self, name: str) -> bool:
        return self.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _counts(self, table: str, column: str) -> tuple[tuple[str, int], ...]:
        if not self._table_exists(table):
            return ()
        rows = self.connection.execute(f"SELECT {column} AS state,COUNT(*) AS count FROM {table} GROUP BY {column} ORDER BY {column}").fetchall()
        return tuple((str(row["state"]), int(row["count"])) for row in rows)

    def integrity_check(self) -> bool:
        rows = self.connection.execute("PRAGMA integrity_check").fetchall()
        return bool(rows) and all(str(row[0]).lower() == "ok" for row in rows)

    def health(self) -> RuntimeHealth:
        task_counts = self._counts("tasks", "state")
        queue_counts = self._counts("service_work_queue", "state")
        provider_counts = self._counts("provider_lifecycle", "state")
        waiting_approvals = 0
        if self._table_exists("human_approval_interactions"):
            waiting_approvals = int(self.connection.execute("SELECT COUNT(*) FROM human_approval_interactions WHERE state='WAITING'").fetchone()[0])
        integrity = self.integrity_check()
        providers = dict(provider_counts)
        queue = dict(queue_counts)
        state = "HEALTHY"
        if not integrity or providers.get("UNAVAILABLE", 0) or queue.get("FAILED", 0):
            state = "BLOCKED"
        elif providers.get("DEGRADED", 0) or waiting_approvals or queue.get("BLOCKED", 0):
            state = "DEGRADED"
        return RuntimeHealth(state, task_counts, queue_counts, provider_counts, waiting_approvals, integrity, utc_now())

    def task_audit(self, task_ref: str) -> tuple[dict, ...]:
        if not self._table_exists("runtime_events"):
            return ()
        rows = self.connection.execute("SELECT * FROM runtime_events WHERE task_id=? ORDER BY sequence", (task_ref,)).fetchall()
        return tuple(dict(row) for row in rows)

    def backup(self, path: str | Path) -> BackupReceipt:
        target = Path(path)
        if not str(target):
            raise OperationsRejected("backup path is required")
        target.parent.mkdir(parents=True, exist_ok=True)
        destination = sqlite3.connect(str(target))
        try:
            self.connection.backup(destination)
            rows = destination.execute("PRAGMA integrity_check").fetchall()
            integrity = bool(rows) and all(str(row[0]).lower() == "ok" for row in rows)
        finally:
            destination.close()
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        receipt = BackupReceipt(str(target), digest, integrity, utc_now())
        if not integrity:
            raise OperationsRejected("backup integrity verification failed")
        with self.connection:
            self.connection.execute(
                "INSERT INTO runtime_operations_events(event_type,detail,recorded_at) VALUES ('backup.verified',?,?)",
                (json.dumps({"path": receipt.path, "sha256": receipt.sha256}, sort_keys=True), receipt.created_at),
            )
        return receipt
