"""Fail-closed operational acceptance runs backed by explicit evidence-bearing checks."""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Callable

from .task_runtime import utc_now


class AcceptanceRejected(RuntimeError):
    pass


class AcceptanceVerdict(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class AcceptanceResult:
    check_id: str
    passed: bool
    evidence_ref: str
    detail: str
    assurance: str


@dataclass(frozen=True)
class AcceptanceRun:
    run_id: str
    verdict: AcceptanceVerdict
    results: tuple[AcceptanceResult, ...]
    created_at: str


class ProductionAcceptanceRuntime:
    """Runs named required checks and persists their evidence without inflating assurance."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._checks: dict[str, tuple[str, Callable[[], AcceptanceResult]]] = {}
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS production_acceptance_runs(run_id TEXT PRIMARY KEY,verdict TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL)"
        )

    def register(self, check_id: str, probe: Callable[[], AcceptanceResult], *, assurance: str = "repository") -> None:
        if not check_id.strip() or assurance not in {"repository", "external_system", "production"}:
            raise AcceptanceRejected("check identity and valid assurance are required")
        if check_id in self._checks:
            raise AcceptanceRejected("acceptance check identity is immutable")
        self._checks[check_id] = (assurance, probe)

    def run(self, *, require_external: bool = False) -> AcceptanceRun:
        if not self._checks:
            raise AcceptanceRejected("production acceptance requires explicit checks")
        results: list[AcceptanceResult] = []
        for check_id in sorted(self._checks):
            assurance, probe = self._checks[check_id]
            try:
                result = probe()
            except Exception:
                result = AcceptanceResult(check_id, False, "probe:error", "acceptance probe failed; details redacted", assurance)
            if result.check_id != check_id:
                raise AcceptanceRejected("acceptance probe returned the wrong check identity")
            if result.assurance != assurance:
                raise AcceptanceRejected("acceptance probe cannot self-upgrade its assurance")
            if not result.evidence_ref.strip():
                raise AcceptanceRejected("acceptance result requires an evidence reference")
            results.append(result)
        external_present = any(item.assurance in {"external_system", "production"} and item.passed for item in results)
        passed = all(item.passed for item in results) and (external_present or not require_external)
        verdict = AcceptanceVerdict.PASS if passed else AcceptanceVerdict.BLOCKED
        run = AcceptanceRun(f"acceptance:{uuid.uuid4()}", verdict, tuple(results), utc_now())
        body = {"run_id": run.run_id, "verdict": run.verdict, "results": [asdict(item) for item in run.results], "created_at": run.created_at, "require_external": require_external}
        with self.connection:
            self.connection.execute("INSERT INTO production_acceptance_runs VALUES (?,?,?,?)", (run.run_id, run.verdict, json.dumps(body, sort_keys=True), run.created_at))
        return run

    def fetch(self, run_id: str) -> AcceptanceRun:
        row = self.connection.execute("SELECT body FROM production_acceptance_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise AcceptanceRejected("unknown acceptance run")
        body = json.loads(row["body"])
        results = tuple(AcceptanceResult(**item) for item in body["results"])
        return AcceptanceRun(body["run_id"], AcceptanceVerdict(body["verdict"]), results, body["created_at"])
