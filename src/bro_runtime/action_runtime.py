"""HANDS-owned action lifecycle under IMMUNE SYSTEM authority.

HANDS owns the Action Request, the Action Attempt, and execution truth. It does
not decide whether an action is permitted: it submits the request to the single
`AuthorityEvaluator` in `immune.py` and records the state its verdict implies.
`AuthorityEnvelope` is re-exported here so existing HANDS-facing imports keep
working, but it is defined and owned once, by IMMUNE SYSTEM.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Callable

from .immune import AuthorityDecision, AuthorityEnvelope, AuthorityEvaluator, AuthorityRejected
from .task_runtime import utc_now

__all__ = [
    "ActionRejected", "ActionRequest", "ActionRuntime", "ActionState", "AdapterResult",
    "ApprovalRequired", "AuthorityEnvelope", "EffectState", "RetryBlocked",
]


class ActionRejected(Exception):
    pass


class RetryBlocked(ActionRejected):
    pass


class ApprovalRequired(ActionRejected):
    """Authority exists but requires an approval that has not been recorded."""


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
class ActionRequest:
    """Canonical Action Request — contracts/v0.1/action-request.schema.json.

    `assignment_ref` and `project_boundary` are optional so a direct HANDS call
    behaves exactly as before. Under supervision both are required, and a present
    `project_boundary` makes IMMUNE SYSTEM demand the matching boundary scope
    token in the envelope, so cross-boundary work fails closed.
    """

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
    assignment_ref: str | None = None
    project_boundary: str | None = None


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
        self.authority = AuthorityEvaluator(connection)
        self.connection.executescript(
            """
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
        """Hand an envelope to IMMUNE SYSTEM, which owns the registry."""
        try:
            self.authority.register(envelope)
        except AuthorityRejected as exc:
            raise ActionRejected(str(exc)) from exc

    def authority_envelope(self, envelope_id: str, version: int | None = None) -> AuthorityEnvelope:
        """Read back a registered envelope. IMMUNE SYSTEM remains its owner."""
        try:
            return self.authority.envelope(envelope_id, version)
        except AuthorityRejected as exc:
            raise ActionRejected(str(exc)) from exc

    def propose(self, request: ActionRequest) -> dict:
        with self.connection:
            self.connection.execute(
                "INSERT INTO action_requests VALUES (?, ?, ?, ?, 1, NULL)",
                (request.action_request_id, request.task_ref, json.dumps(asdict(request), sort_keys=True), ActionState.PROPOSED),
            )
        return self.get_request(request.action_request_id)

    def authorize(self, request_id: str, envelope: AuthorityEnvelope, now: str | None = None) -> dict:
        """Submit the request to IMMUNE SYSTEM and record the state its verdict implies.

        HANDS performs no authority evaluation of its own. There is one evaluator.
        """
        request = self.get_request(request_id)
        body = json.loads(request["body"])
        verdict = self.authority.evaluate(body, envelope, now or utc_now(), subject_ref=request_id)
        target_state = ActionState.AUTHORIZED if verdict.is_allowed() else ActionState.DENIED
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE action_requests SET state=?, revision=revision+1, authority_digest=? WHERE action_request_id=? AND state=?",
                (target_state, verdict.envelope_digest, request_id, ActionState.PROPOSED),
            )
            if cursor.rowcount != 1:
                raise ActionRejected("only a PROPOSED action may be authorized")
        if verdict.decision is AuthorityDecision.APPROVAL_REQUIRED:
            raise ApprovalRequired("authority requires approval: " + "; ".join(verdict.reasons))
        if not verdict.is_allowed():
            raise ActionRejected("authority denied: " + "; ".join(verdict.reasons))
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

    def requests_for_task(self, task_ref: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM action_requests WHERE task_ref=? ORDER BY rowid", (task_ref,)
        ).fetchall()
        return [dict(row) for row in rows]
