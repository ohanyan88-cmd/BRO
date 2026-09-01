"""Final delivery controls for the last BRO audit blocks.

This module closes repository-side seams without pretending repository tests are
production evidence. External capability, identity/vault/human channels,
remote custody/DR, and production acceptance remain externally attested facts.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Mapping


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FinalDeliveryRejected(RuntimeError):
    pass


class Assurance(StrEnum):
    REPOSITORY = "repository"
    EXTERNAL_SYSTEM = "external_system"
    PRODUCTION = "production"


@dataclass(frozen=True)
class InteractionIntent:
    request_id: str
    raw_request: str
    interpreted_scope: tuple[str, ...]
    constraints: tuple[str, ...]
    success_conditions: tuple[str, ...]
    material: bool
    model_ref: str


@dataclass(frozen=True)
class ScopeConfirmation:
    request_id: str
    scope_digest: str
    confirmed_by: str
    confirmed_at: str


@dataclass(frozen=True)
class CapabilityReceipt:
    request_id: str
    specialist_ref: str
    provider_ref: str
    effect_ref: str
    readback_ref: str
    readback_provider_ref: str
    evidence_ref: str
    assurance: Assurance


class IntelligentInteractionRuntime:
    """Natural-language intake -> explicit scope -> specialist execution -> readback.

    The runtime accepts injected model/specialist/provider boundaries so production
    callers can compose real services. It fails closed when material scope was not
    explicitly confirmed or when execution cannot be independently read back.
    """

    def __init__(
        self,
        *,
        interpreter: Callable[[str], Mapping[str, Any]],
        planner: Callable[[InteractionIntent], str],
        executor: Callable[[InteractionIntent, str], Mapping[str, str]],
        readback: Callable[[InteractionIntent, Mapping[str, str]], Mapping[str, str]],
        model_ref: str,
    ) -> None:
        if not model_ref.strip() or model_ref.startswith("test:"):
            raise FinalDeliveryRejected("a non-test model_ref is required")
        self.interpreter = interpreter
        self.planner = planner
        self.executor = executor
        self.readback = readback
        self.model_ref = model_ref
        self._intents: dict[str, InteractionIntent] = {}
        self._confirmations: dict[str, ScopeConfirmation] = {}

    @staticmethod
    def _clean(values: Any, label: str) -> tuple[str, ...]:
        result = tuple(dict.fromkeys(str(v).strip() for v in values or () if str(v).strip()))
        if not result:
            raise FinalDeliveryRejected(f"{label} must not be empty")
        return result

    @staticmethod
    def _digest(intent: InteractionIntent) -> str:
        payload = json.dumps(
            {
                "request_id": intent.request_id,
                "scope": intent.interpreted_scope,
                "constraints": intent.constraints,
                "success_conditions": intent.success_conditions,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    def interpret(self, request: str) -> InteractionIntent:
        request = request.strip()
        if not request:
            raise FinalDeliveryRejected("request must not be empty")
        parsed = dict(self.interpreter(request))
        intent = InteractionIntent(
            request_id=f"request:{uuid.uuid4()}",
            raw_request=request,
            interpreted_scope=self._clean(parsed.get("scope"), "interpreted scope"),
            constraints=tuple(dict.fromkeys(str(v).strip() for v in parsed.get("constraints", ()) if str(v).strip())),
            success_conditions=self._clean(parsed.get("success_conditions"), "success conditions"),
            material=bool(parsed.get("material", True)),
            model_ref=self.model_ref,
        )
        self._intents[intent.request_id] = intent
        return intent

    def confirm_scope(self, request_id: str, *, confirmed_by: str, scope_digest: str) -> ScopeConfirmation:
        intent = self._intents.get(request_id)
        if intent is None:
            raise FinalDeliveryRejected("unknown request")
        expected = self._digest(intent)
        if scope_digest != expected:
            raise FinalDeliveryRejected("scope digest does not match interpreted scope")
        actor = confirmed_by.strip()
        if not actor:
            raise FinalDeliveryRejected("confirmed_by must not be empty")
        confirmation = ScopeConfirmation(request_id, expected, actor, utc_now())
        self._confirmations[request_id] = confirmation
        return confirmation

    def scope_digest(self, request_id: str) -> str:
        try:
            return self._digest(self._intents[request_id])
        except KeyError as exc:
            raise FinalDeliveryRejected("unknown request") from exc

    def execute(self, request_id: str) -> CapabilityReceipt:
        intent = self._intents.get(request_id)
        if intent is None:
            raise FinalDeliveryRejected("unknown request")
        if intent.material and request_id not in self._confirmations:
            raise FinalDeliveryRejected("material interpreted scope requires explicit confirmation")
        specialist_ref = str(self.planner(intent)).strip()
        if not specialist_ref:
            raise FinalDeliveryRejected("planner did not select a specialist")
        effect = dict(self.executor(intent, specialist_ref))
        for field in ("provider_ref", "effect_ref"):
            if not str(effect.get(field, "")).strip():
                raise FinalDeliveryRejected(f"execution missing {field}")
        observation = dict(self.readback(intent, effect))
        for field in ("readback_ref", "provider_ref", "evidence_ref", "assurance"):
            if not str(observation.get(field, "")).strip():
                raise FinalDeliveryRejected(f"readback missing {field}")
        if observation["provider_ref"] == effect["provider_ref"] and observation["readback_ref"] == effect["effect_ref"]:
            raise FinalDeliveryRejected("execution result cannot self-attest as independent readback")
        assurance = Assurance(observation["assurance"])
        if assurance is Assurance.REPOSITORY:
            raise FinalDeliveryRejected("real capability execution requires external-system readback")
        return CapabilityReceipt(
            intent.request_id,
            specialist_ref,
            effect["provider_ref"],
            effect["effect_ref"],
            observation["readback_ref"],
            observation["provider_ref"],
            observation["evidence_ref"],
            assurance,
        )


@dataclass(frozen=True)
class ServiceIdentity:
    service_id: str
    instance_id: str
    identity_subject: str
    vault_backend: str
    approval_channel: str


@dataclass(frozen=True)
class PrimaryLease:
    service_id: str
    instance_id: str
    fencing_token: int
    lease_until: float


class ProductionServiceControl:
    """Durable identity and single-primary fencing for long-lived BRO instances."""

    FORBIDDEN_BACKENDS = {"memory", "in_memory", "test", "fake", "local-test"}

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        connection.row_factory = sqlite3.Row
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_instances(
              service_id TEXT NOT NULL, instance_id TEXT NOT NULL,
              identity_subject TEXT NOT NULL, vault_backend TEXT NOT NULL,
              approval_channel TEXT NOT NULL, registered_at TEXT NOT NULL,
              PRIMARY KEY(service_id,instance_id));
            CREATE TABLE IF NOT EXISTS production_primary(
              service_id TEXT PRIMARY KEY, instance_id TEXT NOT NULL,
              fencing_token INTEGER NOT NULL, lease_until REAL NOT NULL,
              updated_at TEXT NOT NULL);
            """
        )

    @classmethod
    def _external(cls, value: str, label: str) -> str:
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in cls.FORBIDDEN_BACKENDS:
            raise FinalDeliveryRejected(f"production {label} must bind an external backend")
        return cleaned

    def register_instance(
        self,
        *,
        service_id: str,
        instance_id: str,
        identity_subject: str,
        vault_backend: str,
        approval_channel: str,
    ) -> ServiceIdentity:
        identity = ServiceIdentity(
            service_id.strip(),
            instance_id.strip(),
            self._external(identity_subject, "identity"),
            self._external(vault_backend, "vault"),
            self._external(approval_channel, "human approval channel"),
        )
        if not identity.service_id or not identity.instance_id:
            raise FinalDeliveryRejected("service_id and instance_id are required")
        with self.connection:
            self.connection.execute(
                "INSERT OR REPLACE INTO production_instances VALUES (?,?,?,?,?,?)",
                (*asdict(identity).values(), utc_now()),
            )
        return identity

    def claim_primary(self, *, service_id: str, instance_id: str, now_epoch: float, lease_seconds: float = 30) -> PrimaryLease:
        if lease_seconds <= 0:
            raise FinalDeliveryRejected("lease_seconds must be positive")
        registered = self.connection.execute(
            "SELECT 1 FROM production_instances WHERE service_id=? AND instance_id=?",
            (service_id, instance_id),
        ).fetchone()
        if registered is None:
            raise FinalDeliveryRejected("instance is not registered with production identity controls")
        with self.connection:
            row = self.connection.execute("SELECT * FROM production_primary WHERE service_id=?", (service_id,)).fetchone()
            if row is not None and row["lease_until"] > now_epoch and row["instance_id"] != instance_id:
                raise FinalDeliveryRejected("another production instance owns a live primary lease")
            token = 1 if row is None else int(row["fencing_token"]) + 1
            self.connection.execute(
                "INSERT OR REPLACE INTO production_primary VALUES (?,?,?,?,?)",
                (service_id, instance_id, token, now_epoch + lease_seconds, utc_now()),
            )
        return PrimaryLease(service_id, instance_id, token, now_epoch + lease_seconds)

    def assert_fence(self, lease: PrimaryLease, *, now_epoch: float) -> None:
        row = self.connection.execute("SELECT * FROM production_primary WHERE service_id=?", (lease.service_id,)).fetchone()
        if row is None or row["instance_id"] != lease.instance_id or row["fencing_token"] != lease.fencing_token:
            raise FinalDeliveryRejected("stale production fencing token")
        if row["lease_until"] <= now_epoch:
            raise FinalDeliveryRejected("production primary lease expired")


@dataclass(frozen=True)
class CustodyReceipt:
    receipt_id: str
    object_ref: str
    digest: str
    previous_digest: str
    custody_uri: str
    assurance: Assurance
    recorded_at: str


@dataclass(frozen=True)
class DisasterRecoveryReceipt:
    backup_ref: str
    remote_uri: str
    restore_evidence_ref: str
    assurance: Assurance


class DurableTruthCustody:
    """Append-only external custody receipts plus production graduation checks."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS truth_custody(
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,receipt_id TEXT UNIQUE NOT NULL,
            object_ref TEXT NOT NULL,digest TEXT NOT NULL,previous_digest TEXT NOT NULL,
            custody_uri TEXT NOT NULL,assurance TEXT NOT NULL,recorded_at TEXT NOT NULL)"""
        )

    @staticmethod
    def _remote(uri: str) -> str:
        uri = uri.strip()
        if not uri.startswith(("https://", "s3://", "gs://", "az://")):
            raise FinalDeliveryRejected("custody/backup URI must be remote")
        return uri

    def record(self, *, object_ref: str, payload_digest: str, custody_uri: str, assurance: Assurance) -> CustodyReceipt:
        assurance = Assurance(assurance)
        if assurance is Assurance.REPOSITORY:
            raise FinalDeliveryRejected("durable truth custody requires external assurance")
        previous = self.connection.execute("SELECT digest FROM truth_custody ORDER BY sequence DESC LIMIT 1").fetchone()
        previous_digest = "GENESIS" if previous is None else previous["digest"]
        chain_digest = hashlib.sha256(f"{previous_digest}|{object_ref}|{payload_digest}|{custody_uri}".encode()).hexdigest()
        receipt = CustodyReceipt(f"custody:{uuid.uuid4()}", object_ref.strip(), chain_digest, previous_digest, self._remote(custody_uri), assurance, utc_now())
        if not receipt.object_ref or not payload_digest.strip():
            raise FinalDeliveryRejected("object_ref and payload_digest are required")
        with self.connection:
            self.connection.execute(
                "INSERT INTO truth_custody(receipt_id,object_ref,digest,previous_digest,custody_uri,assurance,recorded_at) VALUES (?,?,?,?,?,?,?)",
                (receipt.receipt_id, receipt.object_ref, receipt.digest, receipt.previous_digest, receipt.custody_uri, receipt.assurance.value, receipt.recorded_at),
            )
        return receipt

    def verify_chain(self) -> bool:
        rows = self.connection.execute("SELECT * FROM truth_custody ORDER BY sequence").fetchall()
        previous = "GENESIS"
        for row in rows:
            if row["previous_digest"] != previous:
                return False
            previous = row["digest"]
        return True

    def graduate(
        self,
        *,
        interaction: CapabilityReceipt,
        production_lease: PrimaryLease,
        service_control: ProductionServiceControl,
        now_epoch: float,
        dr: DisasterRecoveryReceipt,
        production_acceptance_ref: str,
        unresolved_contradictions: int,
    ) -> str:
        if interaction.assurance not in {Assurance.EXTERNAL_SYSTEM, Assurance.PRODUCTION}:
            raise FinalDeliveryRejected("interaction block lacks external execution assurance")
        service_control.assert_fence(production_lease, now_epoch=now_epoch)
        if Assurance(dr.assurance) is not Assurance.PRODUCTION:
            raise FinalDeliveryRejected("DR receipt must carry production assurance")
        self._remote(dr.remote_uri)
        if not dr.restore_evidence_ref.strip():
            raise FinalDeliveryRejected("DR receipt requires restore evidence")
        if not production_acceptance_ref.strip():
            raise FinalDeliveryRejected("production acceptance evidence is required")
        if unresolved_contradictions != 0:
            raise FinalDeliveryRejected("production graduation requires zero unresolved material contradictions")
        if not self.verify_chain() or self.connection.execute("SELECT COUNT(*) FROM truth_custody").fetchone()[0] == 0:
            raise FinalDeliveryRejected("external durable truth custody is required")
        return f"PRODUCTION_GRADUATED:{production_acceptance_ref}"
