"""HANDS-owned action lifecycle with fail-closed IMMUNE SYSTEM control."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Callable

from .task_runtime import utc_now


class ActionRejected(Exception):
    pass


class RetryBlocked(ActionRejected):
    pass


class ActionState(StrEnum):
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    DISPATCHED = "DISPATCHED"
    RESULT_RECEIVED = "RESULT_RECEIVED"
    EFFECT_RECONCILED = "EFFECT_RECONCILED"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"
    EFFECT_UNKNOWN = "EFFECT_UNKNOWN"
    CANCELLED = "CANCELLED"


class EffectState(StrEnum):
    NONE = "NONE"
    POSSIBLE = "POSSIBLE"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    REVERSED = "REVERSED"


@dataclass(frozen=True)
class AuthorityEnvelope:
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
class ActionRequest:
    action_request_id: str
    task_ref: str
    intended_effect: str
    operation: str
    target: str
    environment: str
    adapter_id: str
    input_parameters: dict
    authority_envelope_ref: str
    risk_class: str
    reversibility: str
    idempotency_key: str
    idempotency_guaranteed: bool
    expected_result: object
    verification_requirements: tuple[str, ...]


@dataclass(frozen=True)
class AdapterResult:
    result: object
    effect_state: EffectState
    artifact_refs: tuple[str, ...] = ()
    observation_refs: tuple[str, ...] = ()


class ActionRuntime:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS authority_envelopes (
              envelope_id TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL,
              body TEXT NOT NULL, PRIMARY KEY(envelope_id, version)
            );
            CREATE TABLE IF NOT EXISTS action_requests (
              action_request_id TEXT PRIMARY KEY, task_ref TEXT NOT NULL, body TEXT NOT NULL,
              state TEXT NOT NULL, revision INTEGER NOT NULL, authority_digest TEXT
            );
            CREATE TABLE IF NOT EXISTS action_attempts (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT NOT NULL UNIQUE,
              action_request_id TEXT NOT NULL REFERENCES action_requests(action_request_id),
              executor TEXT NOT NULL, interface_version TEXT NOT NULL, started_at TEXT NOT NULL,
              ended_at TEXT NOT NULL, sanitized_inputs TEXT NOT NULL, status TEXT NOT NULL,
              result TEXT, error TEXT, effect_state TEXT NOT NULL, retry_of_ref TEXT,
              artifact_refs TEXT NOT NULL, observation_refs TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS action_reconciliations (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, reconciliation_id TEXT NOT NULL UNIQUE,
              attempt_id TEXT NOT NULL REFERENCES action_attempts(attempt_id), effect_state TEXT NOT NULL,
              evidence_ref TEXT NOT NULL, reconciled_at TEXT NOT NULL
            );
            """
        )

    def register_authority(self, envelope: AuthorityEnvelope) -> None:
        body = json.dumps(asdict(envelope), sort_keys=True)
        try:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO authority_envelopes VALUES (?, ?, ?, ?)",
                    (envelope.envelope_id, envelope.version, envelope.digest, body),
                )
        except sqlite3.IntegrityError as exc:
            raise ActionRejected("authority envelopes are immutable; create a new version") from exc

    def propose(self, request: ActionRequest) -> dict:
        with self.connection:
            self.connection.execute(
                "INSERT INTO action_requests VALUES (?, ?, ?, ?, 1, NULL)",
                (request.action_request_id, request.task_ref, json.dumps(asdict(request), sort_keys=True), ActionState.PROPOSED),
            )
        return self.get_request(request.action_request_id)

    def authorize(self, request_id: str, envelope: AuthorityEnvelope, now: str | None = None) -> dict:
        request = self.get_request(request_id)
        body = json.loads(request["body"])
        reasons = self._authority_failures(body, envelope, now or utc_now())
        target_state = ActionState.DENIED if reasons else ActionState.AUTHORIZED
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE action_requests SET state=?, revision=revision+1, authority_digest=? WHERE action_request_id=? AND state=?",
                (target_state, envelope.digest, request_id, ActionState.PROPOSED),
            )
            if cursor.rowcount != 1:
                raise ActionRejected("only a PROPOSED action may be authorized")
        if reasons:
            raise ActionRejected("authority denied: " + "; ".join(reasons))
        return self.get_request(request_id)

    def dispatch(self, request_id: str, executor: str, interface_version: str, adapter: Callable[[dict], AdapterResult]) -> dict:
        request = self.get_request(request_id)
        if request["state"] != ActionState.AUTHORIZED:
            raise ActionRejected("dispatch requires AUTHORIZED state")
        body = json.loads(request["body"])
        prior = self.latest_attempt(request_id)
        prior_effect = self.effective_effect(prior) if prior else None
        if prior and prior_effect == EffectState.UNKNOWN and not body["idempotency_guaranteed"]:
            raise RetryBlocked("UNKNOWN effect must be reconciled before retry")
        if prior and prior_effect == EffectState.CONFIRMED:
            raise RetryBlocked("confirmed effect cannot be dispatched again")
        with self.connection:
            self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?", (ActionState.DISPATCHED, request_id))
        started = utc_now()
        result = None
        error = None
        artifacts: tuple[str, ...] = ()
        observations: tuple[str, ...] = ()
        retry_ref = prior["attempt_id"] if prior else None
        try:
            response = adapter(dict(body["input_parameters"]))
            result = response.result
            effect = response.effect_state
            artifacts, observations = response.artifact_refs, response.observation_refs
            status = "SUCCEEDED"
            state = ActionState.RESULT_RECEIVED
        except TimeoutError as exc:
            error, effect, status, state = str(exc), EffectState.UNKNOWN, "TIMED_OUT", ActionState.EFFECT_UNKNOWN
        except Exception as exc:  # adapter failures become execution truth, not swallowed success
            error, effect, status, state = str(exc), EffectState.POSSIBLE, "FAILED", ActionState.FAILED
        attempt_id = str(uuid.uuid4())
        with self.connection:
            self.connection.execute(
                """INSERT INTO action_attempts(attempt_id,action_request_id,executor,interface_version,started_at,ended_at,sanitized_inputs,status,result,error,effect_state,retry_of_ref,artifact_refs,observation_refs)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (attempt_id, request_id, executor, interface_version, started, utc_now(), json.dumps(body["input_parameters"], sort_keys=True), status, json.dumps(result), error, effect, retry_ref, json.dumps(artifacts), json.dumps(observations)),
            )
            self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?", (state, request_id))
        return self.latest_attempt(request_id)

    def reconcile(self, request_id: str, effect_state: EffectState, evidence_ref: str) -> dict:
        if effect_state is EffectState.UNKNOWN:
            raise ActionRejected("reconciliation must resolve UNKNOWN")
        attempt = self.latest_attempt(request_id)
        if not attempt:
            raise ActionRejected("no attempt to reconcile")
        with self.connection:
            self.connection.execute("INSERT INTO action_reconciliations(reconciliation_id,attempt_id,effect_state,evidence_ref,reconciled_at) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), attempt["attempt_id"], effect_state, evidence_ref, utc_now()))
            self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?", (ActionState.EFFECT_RECONCILED, request_id))
        return self.latest_attempt(request_id)

    def prepare_retry(self, request_id: str) -> dict:
        request = self.get_request(request_id)
        attempt = self.latest_attempt(request_id)
        body = json.loads(request["body"])
        if not attempt:
            raise RetryBlocked("no attempt exists")
        effective = self.effective_effect(attempt)
        if effective == EffectState.UNKNOWN and not body["idempotency_guaranteed"]:
            raise RetryBlocked("UNKNOWN effect must be reconciled before retry")
        if effective == EffectState.CONFIRMED:
            raise RetryBlocked("confirmed effect cannot be retried")
        with self.connection:
            self.connection.execute("UPDATE action_requests SET state=?, revision=revision+1 WHERE action_request_id=?", (ActionState.AUTHORIZED, request_id))
        return self.get_request(request_id)

    def get_request(self, request_id: str) -> dict:
        row = self.connection.execute("SELECT * FROM action_requests WHERE action_request_id=?", (request_id,)).fetchone()
        if row is None:
            raise ActionRejected("unknown action request")
        return dict(row)

    def latest_attempt(self, request_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM action_attempts WHERE action_request_id=? ORDER BY sequence DESC LIMIT 1", (request_id,)).fetchone()
        return dict(row) if row else None

    def effective_effect(self, attempt: dict) -> EffectState:
        row = self.connection.execute("SELECT effect_state FROM action_reconciliations WHERE attempt_id=? ORDER BY sequence DESC LIMIT 1", (attempt["attempt_id"],)).fetchone()
        return EffectState(row["effect_state"] if row else attempt["effect_state"])

    @staticmethod
    def _authority_failures(request: dict, envelope: AuthorityEnvelope, now: str) -> list[str]:
        failures: list[str] = []
        required = {f"operation:{request['operation']}", f"target:{request['target']}", request["task_ref"]}
        if envelope.decision != "ALLOWED": failures.append("decision is not ALLOWED")
        if envelope.operation != request["operation"]: failures.append("operation mismatch")
        if envelope.target != request["target"]: failures.append("target mismatch")
        if envelope.task_ref != request["task_ref"]: failures.append("task mismatch")
        if envelope.environment != request["environment"]: failures.append("environment mismatch")
        if request["adapter_id"] not in envelope.tool_boundary: failures.append("adapter outside tool boundary")
        if not required.issubset(set(envelope.allowed_scope)): failures.append("allowed scope is insufficient")
        if required & set(envelope.prohibited_scope): failures.append("prohibited scope matched")
        if envelope.revocation_ref: failures.append("authority is revoked")
        if now < envelope.valid_from: failures.append("authority is not yet valid")
        if envelope.expires_at and now >= envelope.expires_at: failures.append("authority is expired")
        risk_rank = {f"R{i}": i for i in range(5)}
        if risk_rank.get(envelope.risk_class, -1) < risk_rank.get(request["risk_class"], 99): failures.append("authority risk ceiling is insufficient")
        return failures
