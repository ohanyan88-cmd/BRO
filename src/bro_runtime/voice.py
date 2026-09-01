"""VOICE runtime: truthful user-facing projection of canonical runtime state.

VOICE never upgrades state, certainty, authority, evidence, or completion.
It only projects what canonical owners already established.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VoiceState(StrEnum):
    PROPOSED = "PROPOSED"
    ATTEMPTED = "ATTEMPTED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    VERIFIED = "VERIFIED"
    COMPLETED = "COMPLETED"


class VoiceRejected(ValueError):
    pass


@dataclass(frozen=True)
class VoiceInput:
    task_ref: str
    task_state: str
    authority_state: str
    evidence_state: str
    effect_state: str
    completion_state: str
    uncertainty: tuple[str, ...] = ()
    blocker_ref: str | None = None
    specialist_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class VoiceProjection:
    state: VoiceState
    headline: str
    detail: str
    uncertainty: tuple[str, ...]
    blocker_ref: str | None


class VoiceRuntime:
    """Fail-closed projection layer; never a source of runtime truth."""

    @staticmethod
    def _norm(value: str) -> str:
        return str(value or "").strip().upper()

    def project(self, source: VoiceInput) -> VoiceProjection:
        if not source.task_ref.strip():
            raise VoiceRejected("task_ref is required")

        task = self._norm(source.task_state)
        auth = self._norm(source.authority_state)
        evidence = self._norm(source.evidence_state)
        effect = self._norm(source.effect_state)
        completion = self._norm(source.completion_state)

        if auth in {"DENY", "DENIED", "APPROVAL_REQUIRED"} or task == "BLOCKED":
            return VoiceProjection(
                VoiceState.BLOCKED,
                "Blocked",
                "Work cannot continue until the recorded authority or blocker condition is resolved.",
                tuple(source.uncertainty), source.blocker_ref,
            )

        if task in {"FAILED", "CANCELLED"}:
            return VoiceProjection(
                VoiceState.FAILED,
                "Failed" if task == "FAILED" else "Cancelled",
                "The task did not reach verified completion.",
                tuple(source.uncertainty), source.blocker_ref,
            )

        if completion in {"VERIFIED", "COMPLETED"} and evidence in {"VERIFIED", "SUFFICIENT"}:
            return VoiceProjection(
                VoiceState.COMPLETED,
                "Completed",
                "The recorded completion gate is satisfied by verified evidence.",
                tuple(source.uncertainty), None,
            )

        if evidence in {"VERIFIED", "SUFFICIENT"}:
            return VoiceProjection(
                VoiceState.VERIFIED,
                "Verified",
                "Evidence is verified, but the task is not recorded as completed.",
                tuple(source.uncertainty), source.blocker_ref,
            )

        if effect in {"CONFIRMED", "POSSIBLE", "UNKNOWN"}:
            detail = "An effect was attempted or observed, but completion is not verified."
            if effect == "UNKNOWN":
                detail = "An action attempt has unknown effect; retry or completion must not be implied."
            return VoiceProjection(
                VoiceState.ATTEMPTED,
                "Attempted",
                detail,
                tuple(source.uncertainty), source.blocker_ref,
            )

        if task in {"EXECUTING", "VERIFYING", "AUTHORIZING", "PLANNING", "READY"}:
            return VoiceProjection(
                VoiceState.PARTIAL,
                "In progress",
                "Work is active, but the outcome is not yet verified as complete.",
                tuple(source.uncertainty), source.blocker_ref,
            )

        return VoiceProjection(
            VoiceState.PROPOSED,
            "Proposed",
            "No verified execution outcome is recorded yet.",
            tuple(source.uncertainty), source.blocker_ref,
        )
