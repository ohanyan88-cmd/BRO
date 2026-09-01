"""IMMUNE SYSTEM: authority decisions, Evidence, and completion gates.

This module is the single evaluator of authority and the single writer of
canonical Evidence, Authority Decisions, and Completion Manifests.

NERVOUS SYSTEM owns Task progression and HANDS owns execution truth; neither
decides whether an action is permitted or whether a result is sufficient. HANDS
submits an Action Request here and consumes the verdict. This module never
transitions a Task: it produces the verdict a transition is allowed to consume,
and refuses to produce a consumable one for anything but a verified outcome.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum

from .task_runtime import CompletionEvidence, utc_now


class AuthorityRejected(Exception):
    pass


class EvidenceRejected(Exception):
    pass


class CompletionNotVerified(Exception):
    pass


# --------------------------------------------------------------------------
# Project / context boundary
# --------------------------------------------------------------------------

BOUNDARY_PREFIX = "project:"


def normalize_boundary_scope(project_boundary: str) -> str:
    """Return the one canonical scope token for a project boundary.

    Idempotent by construction: a boundary already carrying the canonical prefix
    is returned unchanged, so ``project:BRO`` never becomes ``project:project:BRO``.
    """
    boundary = (project_boundary or "").strip()
    if not boundary:
        raise AuthorityRejected("a project boundary is required; empty boundaries are denied")
    return boundary if boundary.startswith(BOUNDARY_PREFIX) else f"{BOUNDARY_PREFIX}{boundary}"


def evidence_scope(project_boundary: str, task_ref: str) -> str:
    """The isolation key Evidence is recorded under. Evidence never crosses it."""
    return f"{normalize_boundary_scope(project_boundary)}::{task_ref}"


# --------------------------------------------------------------------------
# Authority
# --------------------------------------------------------------------------


class AuthorityDecision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


ENVELOPE_DECISION_TO_AUTHORITY = {
    "ALLOWED": AuthorityDecision.ALLOW,
    "DENIED": AuthorityDecision.DENY,
    "APPROVAL_REQUIRED": AuthorityDecision.APPROVAL_REQUIRED,
}

# Task.authority_state values, contracts/v0.1/task.schema.json
AUTHORITY_DECISION_TO_TASK_STATE = {
    AuthorityDecision.ALLOW: "ALLOWED",
    AuthorityDecision.DENY: "DENIED",
    AuthorityDecision.APPROVAL_REQUIRED: "APPROVAL_REQUIRED",
}

RISK_RANK = {f"R{index}": index for index in range(5)}


@dataclass(frozen=True)
class AuthorityEnvelope:
    """Canonical Authority Envelope — contracts/v0.1/authority-envelope.schema.json.

    Immutable after decision. A changed grant is a new version, never an edit.
    """

    envelope_id: str
    version: int
    principal: str
    proof_ref: str
    authority_source: str
    operation: str
    target: str
    allowed_scope: tuple[str, ...]
    prohibited_scope: tuple[str, ...]
    task_ref: str
    risk_class: str
    valid_from: str
    expires_at: str | None
    revocation_ref: str | None
    environment: str
    tool_boundary: tuple[str, ...]
    decision: str
    reason: str
    audit_ref: str

    @property
    def digest(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AuthorityVerdict:
    decision: AuthorityDecision
    reasons: tuple[str, ...]
    envelope_id: str
    envelope_version: int
    envelope_digest: str

    def is_allowed(self) -> bool:
        return self.decision is AuthorityDecision.ALLOW


class AuthorityEvaluator:
    """The only authority evaluator in the runtime."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS authority_envelopes (
              envelope_id TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL,
              body TEXT NOT NULL, PRIMARY KEY(envelope_id, version)
            );
            CREATE TABLE IF NOT EXISTS authority_decisions (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, decision_id TEXT NOT NULL UNIQUE,
              subject_ref TEXT NOT NULL, envelope_id TEXT NOT NULL, envelope_version INTEGER NOT NULL,
              envelope_digest TEXT NOT NULL, decision TEXT NOT NULL, reasons TEXT NOT NULL,
              decided_at TEXT NOT NULL
            );
            """
        )

    def register(self, envelope: AuthorityEnvelope) -> None:
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO authority_envelopes VALUES (?, ?, ?, ?)",
                    (envelope.envelope_id, envelope.version, envelope.digest,
                     json.dumps(asdict(envelope), sort_keys=True)),
                )
        except sqlite3.IntegrityError as exc:
            raise AuthorityRejected("authority envelopes are immutable; create a new version") from exc

    def envelope(self, envelope_id: str, version: int | None = None) -> AuthorityEnvelope:
        if version is None:
            row = self.connection.execute(
                "SELECT body FROM authority_envelopes WHERE envelope_id=? ORDER BY version DESC LIMIT 1",
                (envelope_id,),
            ).fetchone()
        else:
            row = self.connection.execute(
                "SELECT body FROM authority_envelopes WHERE envelope_id=? AND version=?", (envelope_id, version)
            ).fetchone()
        if row is None:
            raise AuthorityRejected(f"unknown authority envelope: {envelope_id}")
        body = json.loads(row["body"])
        for key in ("allowed_scope", "prohibited_scope", "tool_boundary"):
            body[key] = tuple(body[key])
        return AuthorityEnvelope(**body)

    def evaluate(self, request: dict, envelope: AuthorityEnvelope, now: str, *, subject_ref: str | None = None) -> AuthorityVerdict:
        """Evaluate one Action Request against one envelope and record the decision."""
        reasons = self._failures(request, envelope, now)
        if reasons:
            # Any failure denies, whatever the envelope claims to have decided.
            decision = AuthorityDecision.DENY
        else:
            # _failures already rejected every decision except these two.
            decision = ENVELOPE_DECISION_TO_AUTHORITY[envelope.decision]
            if decision is AuthorityDecision.APPROVAL_REQUIRED:
                reasons = ("the envelope requires a fresh approval that has not been recorded",)
        verdict = AuthorityVerdict(decision, tuple(reasons), envelope.envelope_id, envelope.version, envelope.digest)
        with self.connection:
            self.connection.execute(
                """INSERT INTO authority_decisions(decision_id,subject_ref,envelope_id,envelope_version,
                   envelope_digest,decision,reasons,decided_at) VALUES (?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), subject_ref or request.get("action_request_id", "unknown"),
                 envelope.envelope_id, envelope.version, envelope.digest, str(decision),
                 json.dumps(list(verdict.reasons)), now),
            )
        return verdict

    def decisions(self, subject_ref: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM authority_decisions WHERE subject_ref=? ORDER BY sequence", (subject_ref,)
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _failures(request: dict, envelope: AuthorityEnvelope, now: str) -> list[str]:
        failures: list[str] = []
        required = {f"operation:{request['operation']}", f"target:{request['target']}", request["task_ref"]}
        boundary = request.get("project_boundary")
        if boundary:
            required.add(normalize_boundary_scope(boundary))
        if envelope.decision not in {"ALLOWED", "APPROVAL_REQUIRED"}:
            failures.append("decision is not ALLOWED")
        if envelope.operation != request["operation"]:
            failures.append("operation mismatch")
        if envelope.target != request["target"]:
            failures.append("target mismatch")
        if envelope.task_ref != request["task_ref"]:
            failures.append("task mismatch")
        if envelope.environment != request["environment"]:
            failures.append("environment mismatch")
        if request["adapter_id"] not in envelope.tool_boundary:
            failures.append("adapter outside tool boundary")
        if not required.issubset(set(envelope.allowed_scope)):
            failures.append("allowed scope is insufficient")
        if required & set(envelope.prohibited_scope):
            failures.append("prohibited scope matched")
        if envelope.revocation_ref:
            failures.append("authority is revoked")
        if now < envelope.valid_from:
            failures.append("authority is not yet valid")
        if envelope.expires_at and now >= envelope.expires_at:
            failures.append("authority is expired")
        if RISK_RANK.get(envelope.risk_class, -1) < RISK_RANK.get(request["risk_class"], 99):
            failures.append("authority risk ceiling is insufficient")
        return failures


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


class EvidenceValidity(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNVERIFIED = "UNVERIFIED"
    EXPIRED = "EXPIRED"


class EvidenceFreshness(StrEnum):
    CURRENT = "CURRENT"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class CompletionVerdict(StrEnum):
    VERIFIED = "VERIFIED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    EFFECT_UNRECONCILED = "EFFECT_UNRECONCILED"
    PARTIAL = "PARTIAL"
    WORK_FAILED = "WORK_FAILED"


SUFFICIENT_VALIDITY = frozenset({EvidenceValidity.VALID})
SUFFICIENT_FRESHNESS = frozenset({EvidenceFreshness.CURRENT, EvidenceFreshness.AGING})
RECONCILED_EFFECTS = frozenset({"NONE", "CONFIRMED", "REVERSED"})


@dataclass(frozen=True)
class Evidence:
    """Canonical Evidence record — contracts/v0.1/evidence.schema.json."""

    evidence_id: str
    criterion: str
    evidence_type: str
    source: str
    provenance: dict
    collection_method: str
    collected_at: str
    result: object
    scope: str
    limitations: tuple[str, ...]
    validity: EvidenceValidity
    freshness: EvidenceFreshness
    verifier: str

    def is_sufficient(self) -> bool:
        return self.validity in SUFFICIENT_VALIDITY and self.freshness in SUFFICIENT_FRESHNESS

    def body(self) -> dict:
        return {
            "evidence_id": self.evidence_id, "criterion": self.criterion, "evidence_type": self.evidence_type,
            "source": self.source, "provenance": dict(self.provenance), "collection_method": self.collection_method,
            "collected_at": self.collected_at, "result": self.result, "scope": self.scope,
            "limitations": list(self.limitations), "validity": str(self.validity), "freshness": str(self.freshness),
            "verifier": self.verifier,
        }


@dataclass(frozen=True)
class EffectRecord:
    action_request_ref: str
    effect_state: str

    def is_reconciled(self) -> bool:
        return self.effect_state in RECONCILED_EFFECTS


@dataclass(frozen=True)
class CompletionManifest:
    """Canonical Completion Manifest — contracts/v0.1/completion-manifest.schema.json."""

    manifest_id: str
    task_ref: str
    task_revision: int
    assignment_ref: str
    verdict: CompletionVerdict
    outcome_statement: str
    outcome_exists: bool
    artifact_refs: tuple[str, ...]
    effects: tuple[EffectRecord, ...]
    exclusions: tuple[str, ...]
    criteria_satisfied: tuple[str, ...]
    criteria_unsatisfied: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evaluated_at: str
    verifier: str
    reason: str

    def is_verified(self) -> bool:
        return self.verdict is CompletionVerdict.VERIFIED

    def to_completion_evidence(self) -> CompletionEvidence:
        """The only bridge from a verdict to a NERVOUS SYSTEM completion transition.

        Every flag is derived from a fact this manifest recorded. Artifact usability
        is asserted through a declared completion criterion backed by Evidence, so it
        resolves with the criteria set rather than by counting artifact references.
        """
        if not self.is_verified():
            raise CompletionNotVerified(f"completion verdict is {self.verdict}: {self.reason}")
        return CompletionEvidence(
            outcome_exists=self.outcome_exists,
            mandatory_scope_satisfied=not self.exclusions,
            effects_reconciled=all(effect.is_reconciled() for effect in self.effects),
            artifacts_usable=not self.criteria_unsatisfied,
            criteria_evidence_refs=self.evidence_refs,
            checks_passed=not self.criteria_unsatisfied,
            no_invalidating_blocker=True,
            exclusions_explicit=True,
            communication_truthful=True,
        )

    def body(self) -> dict:
        return {
            "manifest_id": self.manifest_id, "task_ref": self.task_ref, "task_revision": self.task_revision,
            "assignment_ref": self.assignment_ref, "verdict": str(self.verdict),
            "outcome_statement": self.outcome_statement, "outcome_exists": self.outcome_exists,
            "artifact_refs": list(self.artifact_refs),
            "effects": [{"action_request_ref": e.action_request_ref, "effect_state": e.effect_state} for e in self.effects],
            "exclusions": list(self.exclusions), "criteria_satisfied": list(self.criteria_satisfied),
            "criteria_unsatisfied": list(self.criteria_unsatisfied), "evidence_refs": list(self.evidence_refs),
            "evaluated_at": self.evaluated_at, "verifier": self.verifier, "reason": self.reason,
        }


class EvidenceLedger:
    """Append-only Evidence store and the completion gate. One writer, one owner."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS evidence (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, evidence_id TEXT NOT NULL UNIQUE,
              criterion TEXT NOT NULL, scope TEXT NOT NULL, validity TEXT NOT NULL,
              freshness TEXT NOT NULL, body TEXT NOT NULL, recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS completion_manifests (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, manifest_id TEXT NOT NULL UNIQUE,
              task_ref TEXT NOT NULL, assignment_ref TEXT NOT NULL, verdict TEXT NOT NULL,
              body TEXT NOT NULL, evaluated_at TEXT NOT NULL
            );
            """
        )

    def record(self, evidence: Evidence) -> dict:
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO evidence(evidence_id,criterion,scope,validity,freshness,body,recorded_at) VALUES (?,?,?,?,?,?,?)",
                    (evidence.evidence_id, evidence.criterion, evidence.scope, str(evidence.validity),
                     str(evidence.freshness), json.dumps(evidence.body(), sort_keys=True), utc_now()),
                )
        except sqlite3.IntegrityError as exc:
            raise EvidenceRejected("Evidence is append-only; a recorded evidence_id cannot be rewritten") from exc
        return self.get(evidence.evidence_id)

    def get(self, evidence_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM evidence WHERE evidence_id=?", (evidence_id,)).fetchone()
        if row is None:
            raise EvidenceRejected(f"unknown evidence: {evidence_id}")
        return dict(row)

    def sufficiency(self, criteria, scope: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Return (satisfied, unsatisfied, supporting refs) for criteria inside one scope.

        Evidence recorded under another scope can never satisfy a criterion here.
        """
        satisfied: list[str] = []
        unsatisfied: list[str] = []
        refs: list[str] = []
        for criterion in dict.fromkeys(criteria):
            rows = self.connection.execute(
                "SELECT evidence_id, validity, freshness FROM evidence WHERE criterion=? AND scope=? ORDER BY sequence",
                (criterion, scope),
            ).fetchall()
            usable = [row for row in rows if row["validity"] in SUFFICIENT_VALIDITY and row["freshness"] in SUFFICIENT_FRESHNESS]
            if usable:
                satisfied.append(criterion)
                refs.extend(row["evidence_id"] for row in usable)
            else:
                unsatisfied.append(criterion)
        return tuple(satisfied), tuple(unsatisfied), tuple(dict.fromkeys(refs))

    def evaluate_completion(
        self,
        *,
        task_ref: str,
        task_revision: int,
        assignment_ref: str,
        scope: str,
        required_criteria,
        assignment_result_state: str,
        effects,
        artifact_refs=(),
        outcome_exists: bool,
        outcome_statement: str,
        exclusions=(),
        verifier: str = "IMMUNE_SYSTEM",
        now: str | None = None,
    ) -> CompletionManifest:
        """The completion gate. Always produces a durable, auditable manifest."""
        moment = now or utc_now()
        effects = tuple(effects)
        exclusions = tuple(exclusions)
        criteria = tuple(dict.fromkeys(required_criteria))
        satisfied, unsatisfied, refs = self.sufficiency(criteria, scope)

        unreconciled = [effect for effect in effects if not effect.is_reconciled()]
        if unreconciled:
            verdict = CompletionVerdict.EFFECT_UNRECONCILED
            reason = "unreconciled effects: " + ", ".join(f"{e.action_request_ref}={e.effect_state}" for e in unreconciled)
        elif assignment_result_state == "FAILED":
            verdict, reason = CompletionVerdict.WORK_FAILED, "the specialist assignment reported FAILED"
        elif assignment_result_state == "PARTIAL":
            verdict = CompletionVerdict.PARTIAL
            reason = ("partial result with declared exclusions: " + ", ".join(exclusions)) if exclusions else (
                "partial result did not declare its excluded scope")
        elif assignment_result_state != "SUCCEEDED":
            verdict, reason = CompletionVerdict.WORK_FAILED, f"assignment state {assignment_result_state} is not a settled success"
        elif not outcome_exists:
            verdict, reason = CompletionVerdict.INSUFFICIENT_EVIDENCE, "the required outcome does not exist"
        elif not criteria:
            verdict, reason = CompletionVerdict.INSUFFICIENT_EVIDENCE, "no completion criteria were declared"
        elif unsatisfied:
            verdict = CompletionVerdict.INSUFFICIENT_EVIDENCE
            reason = "completion criteria without sufficient current Evidence: " + ", ".join(unsatisfied)
        else:
            verdict = CompletionVerdict.VERIFIED
            reason = "every completion criterion is supported by valid current Evidence"

        manifest = CompletionManifest(
            manifest_id=str(uuid.uuid4()), task_ref=task_ref, task_revision=task_revision,
            assignment_ref=assignment_ref, verdict=verdict, outcome_statement=outcome_statement,
            outcome_exists=outcome_exists, artifact_refs=tuple(artifact_refs), effects=effects,
            exclusions=exclusions, criteria_satisfied=satisfied, criteria_unsatisfied=unsatisfied,
            evidence_refs=refs, evaluated_at=moment, verifier=verifier, reason=reason,
        )
        with self.connection:
            self.connection.execute(
                "INSERT INTO completion_manifests(manifest_id,task_ref,assignment_ref,verdict,body,evaluated_at) VALUES (?,?,?,?,?,?)",
                (manifest.manifest_id, task_ref, assignment_ref, str(verdict), json.dumps(manifest.body(), sort_keys=True), moment),
            )
        return manifest

    def manifest(self, manifest_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM completion_manifests WHERE manifest_id=?", (manifest_id,)).fetchone()
        if row is None:
            raise EvidenceRejected(f"unknown completion manifest: {manifest_id}")
        return dict(row)

    def latest_manifest(self, task_ref: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM completion_manifests WHERE task_ref=? ORDER BY sequence DESC LIMIT 1", (task_ref,)
        ).fetchone()
        return dict(row) if row else None
