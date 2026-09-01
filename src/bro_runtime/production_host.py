"""Debian production host process for BRO.

This process establishes host-level runtime truth: durable SQLite/WAL state,
exclusive single-process ownership, periodic production heartbeats, and exact
source-revision readback. It deliberately does not claim external IAM/vault/DR
or final production graduation; those remain governed by final_delivery.py.
"""
from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .production_control import ProductionControlPlane

_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class ProductionHostRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionHostConfig:
    environment: str
    service_id: str
    instance_id: str
    source_revision: str
    db_path: str
    lock_path: str
    heartbeat_seconds: float

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "ProductionHostConfig":
        values = os.environ if env is None else env
        environment = values.get("BRO_ENVIRONMENT", "").strip()
        service_id = values.get("BRO_SERVICE_ID", "bro").strip()
        instance_id = values.get("BRO_INSTANCE_ID", "").strip()
        source_revision = values.get("BRO_SOURCE_REVISION", "").strip().lower()
        db_path = values.get("BRO_DB_PATH", "/var/lib/bro/runtime.sqlite3").strip()
        lock_path = values.get("BRO_LOCK_PATH", "/run/bro/primary.lock").strip()
        try:
            heartbeat_seconds = float(values.get("BRO_HEARTBEAT_SECONDS", "10"))
        except ValueError as exc:
            raise ProductionHostRejected("BRO_HEARTBEAT_SECONDS must be numeric") from exc
        if environment != "production":
            raise ProductionHostRejected("BRO_ENVIRONMENT must be production")
        if not service_id or not instance_id:
            raise ProductionHostRejected("BRO_SERVICE_ID and BRO_INSTANCE_ID are required")
        if not _SHA40.fullmatch(source_revision):
            raise ProductionHostRejected("BRO_SOURCE_REVISION must be an exact 40-character git SHA")
        if not db_path.startswith("/") or not lock_path.startswith("/"):
            raise ProductionHostRejected("BRO_DB_PATH and BRO_LOCK_PATH must be absolute paths")
        if heartbeat_seconds <= 0:
            raise ProductionHostRejected("BRO_HEARTBEAT_SECONDS must be positive")
        return cls(environment, service_id, instance_id, source_revision, db_path, lock_path, heartbeat_seconds)


class ExclusiveHostLock:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            handle.close()
            raise ProductionHostRejected("another BRO production host owns the host lock") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


class ProductionHost:
    def __init__(self, config: ProductionHostConfig) -> None:
        self.config = config
        Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(config.db_path, timeout=30)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.control = ProductionControlPlane(self.connection)
        self.lock = ExclusiveHostLock(config.lock_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def heartbeat(self) -> None:
        observed_at = self._now()
        self.control.heartbeat(
            service_id=self.config.service_id,
            instance_id=self.config.instance_id,
            revision=self.config.source_revision,
            state="HEALTHY",
            evidence_ref=f"host-readback:sqlite:{self.config.source_revision}:{observed_at}",
            observed_at=observed_at,
        )

    def run(self, *, should_stop=lambda: False, sleep=time.sleep) -> None:
        self.lock.acquire()
        try:
            while not should_stop():
                self.heartbeat()
                sleep(self.config.heartbeat_seconds)
        finally:
            self.lock.release()
            self.connection.close()


def read_host_status(config: ProductionHostConfig, *, now_epoch: float | None = None, max_age_seconds: float | None = None) -> dict:
    connection = sqlite3.connect(config.db_path, timeout=5)
    try:
        control = ProductionControlPlane(connection)
        heartbeats = control.latest_heartbeats(config.service_id)
    finally:
        connection.close()
    matches = [item for item in heartbeats if item.instance_id == config.instance_id]
    if not matches:
        raise ProductionHostRejected("no heartbeat exists for configured production instance")
    heartbeat = matches[-1]
    observed = datetime.fromisoformat(heartbeat.observed_at.replace("Z", "+00:00")).timestamp()
    now = time.time() if now_epoch is None else now_epoch
    threshold = max_age_seconds if max_age_seconds is not None else max(30.0, config.heartbeat_seconds * 3)
    age = max(0.0, now - observed)
    healthy = heartbeat.state == "HEALTHY" and heartbeat.revision == config.source_revision and age <= threshold
    return {
        "healthy": healthy,
        "environment": config.environment,
        "service_id": heartbeat.service_id,
        "instance_id": heartbeat.instance_id,
        "source_revision": heartbeat.revision,
        "configured_revision": config.source_revision,
        "heartbeat_state": heartbeat.state,
        "observed_at": heartbeat.observed_at,
        "age_seconds": age,
        "evidence_ref": heartbeat.evidence_ref,
        "assurance": "host_readback",
    }
