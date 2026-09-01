"""Trusted evidence verification boundary owned by IMMUNE SYSTEM.

Callers may submit observations, but they cannot assign canonical validity,
freshness, or verifier identity. Only a registered verifier can mint Evidence
that is eligible for completion, and every sufficient verdict is durably
attested so the EvidenceLedger can reject forged Evidence objects.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Callable

from .immune import Evidence, EvidenceFreshness, EvidenceRejected, EvidenceValidity
from .task_runtime import utc_now


def evidence_digest(evidence: Evidence) -> str:
    encoded = json.dumps(evidence.body(), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


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
    """Trusted verifier registry plus durable attestation writer.

    The registry decides who may mint a verification verdict. The attestation
    table lets IMMUNE SYSTEM later prove that the exact Evidence body came from
    that registered verifier rather than from a caller-created dataclass.
    """

    def __init__(self, connection: sqlite3.Connection | None = None) -> None:
        self.connection = connection or sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self._verifiers: dict[str, EvidenceVerifier] = {}
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS evidence_attestations(
                 evidence_id TEXT PRIMARY KEY,
                 verifier_id TEXT NOT NULL,
                 evidence_digest TEXT NOT NULL,
                 attested_at TEXT NOT NULL
               )"""
        )

    def register(self, verifier: EvidenceVerifier) -> EvidenceVerifier:
        if not verifier.verifier_id.strip():
            raise EvidenceRejected("verifier_id is required")
        if verifier.verifier_id in self._verifiers:
            raise EvidenceRejected("evidence verifier identity is immutable")
        self._verifiers[verifier.verifier_id] = verifier
        return verifier

    def verify(
        self,
        verifier_id: str,
        observation: EvidenceObservation,
        *,
        evidence_id: str | None = None,
        collected_at: str | None = None,
    ) -> Evidence:
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
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO evidence_attestations(evidence_id,verifier_id,evidence_digest,attested_at) VALUES (?,?,?,?)",
                    (evidence.evidence_id, verifier.verifier_id, evidence_digest(evidence), utc_now()),
                )
        except sqlite3.IntegrityError as exc:
            raise EvidenceRejected("evidence attestation is immutable") from exc
        return evidence
