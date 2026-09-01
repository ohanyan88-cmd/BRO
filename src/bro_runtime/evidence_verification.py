"""Trusted evidence verification boundary owned by IMMUNE SYSTEM.

Callers may submit observations, but they cannot assign canonical validity,
freshness, or verifier identity. Only a registered verifier can mint Evidence
that is eligible for completion.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import uuid

from .immune import Evidence, EvidenceFreshness, EvidenceRejected, EvidenceValidity
from .task_runtime import utc_now


@dataclass(frozen=True)
class EvidenceObservation:
    criterion: str
    evidence_type: str
    source: str
    provenance: dict
    collection_method: str
    result: object
    scope: str
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    validity: EvidenceValidity
    freshness: EvidenceFreshness
    provenance: dict
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceVerifier:
    verifier_id: str
    verify: Callable[[EvidenceObservation], VerificationResult]


class EvidenceVerificationRegistry:
    """Immutable registry of trusted verifiers that alone mint canonical Evidence."""

    def __init__(self) -> None:
        self._verifiers: dict[str, EvidenceVerifier] = {}

    def register(self, verifier: EvidenceVerifier) -> EvidenceVerifier:
        if not verifier.verifier_id.strip():
            raise EvidenceRejected("verifier_id is required")
        if verifier.verifier_id in self._verifiers:
            raise EvidenceRejected("evidence verifier identity is immutable")
        self._verifiers[verifier.verifier_id] = verifier
        return verifier

    def verify(self, verifier_id: str, observation: EvidenceObservation, *, evidence_id: str | None = None,
               collected_at: str | None = None) -> Evidence:
        verifier = self._verifiers.get(verifier_id)
        if verifier is None:
            raise EvidenceRejected("unknown evidence verifier")
        verdict = verifier.verify(observation)
        if not isinstance(verdict, VerificationResult):
            raise EvidenceRejected("trusted verifier must return VerificationResult")
        provenance = dict(observation.provenance)
        provenance.update(verdict.provenance)
        return Evidence(
            evidence_id=evidence_id or f"evidence:{uuid.uuid4()}",
            criterion=observation.criterion,
            evidence_type=observation.evidence_type,
            source=observation.source,
            provenance=provenance,
            collection_method=observation.collection_method,
            collected_at=collected_at or utc_now(),
            result=observation.result,
            scope=observation.scope,
            limitations=tuple((*observation.limitations, *verdict.limitations)),
            validity=verdict.validity,
            freshness=verdict.freshness,
            verifier=verifier.verifier_id,
        )
