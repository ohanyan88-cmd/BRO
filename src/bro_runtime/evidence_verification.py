"""Trusted evidence verification boundary owned by IMMUNE SYSTEM.

Callers may submit observations, but they cannot assign canonical validity,
freshness, or verifier identity. Only a registered verifier can mint Evidence
that is eligible for canonical reconciliation, settlement, or completion.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable
import uuid
import weakref

from .immune import Evidence, EvidenceFreshness, EvidenceRejected, EvidenceValidity
from .task_runtime import utc_now


# Process-local object attestation remains useful for preventing caller-cloned
# Evidence from crossing a live write boundary, but trust is also bound to the
# exact EvidenceVerificationRegistry that minted it. This prevents another
# registry in the same process from creating Evidence accepted by the canonical
# kernel's supervisor. Persisted ledger truth is durable history; fresh canonical
# writes after restart must be re-verified by the active kernel registry.
_ATTESTATIONS: dict[int, tuple[weakref.ReferenceType[Evidence], object]] = {}


def _attest(evidence: Evidence, registry_marker: object) -> Evidence:
    evidence_id = id(evidence)

    def cleanup(ref):
        current = _ATTESTATIONS.get(evidence_id)
        if current is not None and current[0] is ref:
            _ATTESTATIONS.pop(evidence_id, None)

    ref = weakref.ref(evidence, cleanup)
    _ATTESTATIONS[evidence_id] = (ref, registry_marker)
    return evidence


def is_trusted_evidence(evidence: object) -> bool:
    """Compatibility introspection: was this exact object minted by any verifier registry?"""
    if not isinstance(evidence, Evidence):
        return False
    attestation = _ATTESTATIONS.get(id(evidence))
    return bool(attestation and attestation[0]() is evidence)


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
        self._trust_marker = object()

    def register(self, verifier: EvidenceVerifier) -> EvidenceVerifier:
        if not verifier.verifier_id.strip():
            raise EvidenceRejected("verifier_id is required")
        if verifier.verifier_id in self._verifiers:
            raise EvidenceRejected("evidence verifier identity is immutable")
        self._verifiers[verifier.verifier_id] = verifier
        return verifier

    def is_trusted(self, evidence: object) -> bool:
        """Return whether this exact Evidence object was minted by this registry."""
        if not isinstance(evidence, Evidence):
            return False
        attestation = _ATTESTATIONS.get(id(evidence))
        return bool(
            attestation
            and attestation[0]() is evidence
            and attestation[1] is self._trust_marker
        )

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
        evidence = Evidence(
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
        return _attest(evidence, self._trust_marker)
