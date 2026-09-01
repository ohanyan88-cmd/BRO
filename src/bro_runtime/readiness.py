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
        # 100 is a semantic claim: only IMMUNE-verified completion may unlock it.
        score = 100 if verified_done else min(raw, 99)
        return ReadinessReport(score, build, production, verified_done, blockers, missing)
