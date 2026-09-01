"""Governed deployment promotion with mandatory external read-back verification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable


class DeploymentRejected(Exception):
    pass


class ReleaseState(StrEnum):
    VERIFIED = "VERIFIED"
    PROMOTING = "PROMOTING"
    PROMOTED = "PROMOTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ReleaseCandidate:
    release_ref: str
    artifact_ref: str
    source_revision: str
    environment: str
    verification_ref: str
    state: ReleaseState = ReleaseState.VERIFIED


@dataclass(frozen=True)
class DeploymentObservation:
    environment: str
    active_release_ref: str
    active_artifact_ref: str
    evidence_ref: str


@dataclass(frozen=True)
class DeploymentResult:
    release_ref: str
    environment: str
    state: ReleaseState
    evidence_ref: str


class DeploymentRuntime:
    """Promote only verified candidates and trust read-back, not deploy acknowledgement."""

    def promote_and_verify(
        self,
        candidate: ReleaseCandidate,
        *,
        promote: Callable[[ReleaseCandidate], object],
        read_back: Callable[[str], DeploymentObservation],
    ) -> DeploymentResult:
        if candidate.state is not ReleaseState.VERIFIED:
            raise DeploymentRejected("only a VERIFIED release candidate may be promoted")
        if not candidate.verification_ref.strip():
            raise DeploymentRejected("verified release requires verification evidence")

        promote(candidate)
        observation = read_back(candidate.environment)
        if not isinstance(observation, DeploymentObservation):
            raise DeploymentRejected("deployment verification requires DeploymentObservation")
        if observation.environment != candidate.environment:
            raise DeploymentRejected("deployment read-back environment mismatch")
        if observation.active_release_ref != candidate.release_ref:
            raise DeploymentRejected("deployment read-back did not confirm the promoted release")
        if observation.active_artifact_ref != candidate.artifact_ref:
            raise DeploymentRejected("deployment read-back artifact mismatch")
        if not observation.evidence_ref.strip():
            raise DeploymentRejected("deployment read-back requires evidence")

        return DeploymentResult(candidate.release_ref, candidate.environment, ReleaseState.PROMOTED, observation.evidence_ref)
