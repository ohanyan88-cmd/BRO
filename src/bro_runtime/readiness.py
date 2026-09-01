"""Evidence-driven readiness scoring for BRO work.

Readiness is derived from explicit checks. It is never a manually asserted
percentage, and 100% is reserved for verified DONE.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class CheckState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"

@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    label: str
    weight: int
    state: CheckState
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.check_id or not self.label:
            raise ValueError("readiness check requires identity and label")
        if self.weight <= 0:
            raise ValueError("readiness check weight must be positive")
        if self.state is CheckState.PASS and not self.evidence_refs:
            raise ValueError("PASS readiness check requires evidence")

@dataclass(frozen=True)
class ReadinessReport:
    score: int
    build_score: int
    production_score: int
    verified_done: bool
    blockers: tuple[str, ...]
    missing: tuple[str, ...]

class ReadinessMeter:
    """Compute deterministic readiness from evidence-bearing checks."""

    @staticmethod
    def _score(checks: tuple[ReadinessCheck, ...]) -> int:
        if not checks:
            return 0
        total = sum(c.weight for c in checks)
        passed = sum(c.weight for c in checks if c.state is CheckState.PASS)
        return int((passed * 100) / total)

    def measure(self, *, build_checks: tuple[ReadinessCheck, ...],
                production_checks: tuple[ReadinessCheck, ...],
                completion_verified: bool) -> ReadinessReport:
        all_checks = build_checks + production_checks
        if not all_checks:
            raise ValueError("readiness requires declared checks")
        build = self._score(build_checks)
        production = self._score(production_checks)
        raw = self._score(all_checks)
        blockers = tuple(c.check_id for c in all_checks if c.state is CheckState.BLOCKED)
        missing = tuple(c.check_id for c in all_checks if c.state in {CheckState.FAIL, CheckState.UNKNOWN})
        verified_done = completion_verified and not blockers and not missing and all(c.state is CheckState.PASS for c in all_checks)
        score = 100 if verified_done else min(raw, 99)
        return ReadinessReport(score, build, production, verified_done, blockers, missing)

class RuntimeReadiness:
    """Project readiness from canonical Task/Step/FEET/IMMUNE state.

    The caller supplies no percentages or PASS assertions. Each PASS is derived
    from a durable canonical record and carries the record reference as evidence.
    """
    def __init__(self, meter: ReadinessMeter | None = None) -> None:
        self.meter = meter or ReadinessMeter()

    @staticmethod
    def _check(check_id: str, label: str, weight: int, passed: bool, evidence_ref: str | None,
               *, blocked: bool = False) -> ReadinessCheck:
        state = CheckState.BLOCKED if blocked else CheckState.PASS if passed else CheckState.UNKNOWN
        refs = (evidence_ref,) if state is CheckState.PASS and evidence_ref else ()
        return ReadinessCheck(check_id, label, weight, state, refs)

    def measure_task(self, *, task: dict, step, route, completion_manifest: dict | None) -> ReadinessReport:
        task_ref = task["task_id"]
        manifest_verified = bool(
            completion_manifest
            and completion_manifest.get("task_ref") == task_ref
            and completion_manifest.get("verdict") == "VERIFIED"
            and task.get("completion_manifest_ref") == completion_manifest.get("manifest_id")
        )
        blocked = task.get("state") == "BLOCKED" or getattr(route.state, "value", route.state) == "BLOCKED"
        build_checks = (
            self._check("task-bound", "Canonical Task is bound to plan/context", 20,
                bool(task.get("plan_ref") and task.get("context_manifest_ref")), task_ref),
            self._check("step-terminal", "Canonical Step succeeded", 25,
                getattr(step.state, "value", step.state) == "SUCCEEDED", f"{step.step_id}@{step.revision}"),
            self._check("route-terminal", "FEET route completed", 20,
                getattr(route.state, "value", route.state) == "COMPLETED", f"{route.route_id}@{route.version}", blocked=blocked),
        )
        production_checks = (
            self._check("authority", "Authority was allowed", 10,
                task.get("authority_state") == "ALLOWED", task_ref, blocked=task.get("authority_state") in {"DENIED", "APPROVAL_REQUIRED"}),
            self._check("evidence", "Completion is IMMUNE verified", 15,
                manifest_verified, completion_manifest.get("manifest_id") if completion_manifest else None),
            self._check("truthful-terminal", "Task terminal state matches verified completion", 10,
                task.get("state") == "COMPLETED" and manifest_verified, task_ref),
        )
        return self.meter.measure(build_checks=build_checks, production_checks=production_checks,
            completion_verified=manifest_verified)
