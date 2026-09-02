#!/usr/bin/env python3
"""Bind external acceptance evidence to the exact deployed revision in the release ledger.

The repository already owned the acceptance authority: ProductionControlPlane.activate
refuses anything but an independently read-back PROMOTED deployment plus a PASS
acceptance run carrying external evidence. Nothing, however, connected the governed
intelligent-acceptance record to it, so PRODUCTION_ACCEPTED could never exist as
durable state bound to a revision. This binder is that connection and nothing more:
it creates no acceptance authority of its own and it upgrades no assurance.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bro_runtime.acceptance_runtime import AcceptanceResult, AcceptanceVerdict, ProductionAcceptanceRuntime
from bro_runtime.deployment_runtime import DeploymentObservation, DeploymentRuntime, ReleaseCandidate, ReleaseState
from bro_runtime.production_control import ProductionControlPlane
from bro_runtime.production_host import ProductionHostConfig, read_host_status

DEFAULT_RECORD = "/var/lib/bro/intelligent-acceptance.json"
DEFAULT_RELEASE_ROOT = "/opt/bro"
SHA40 = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_RECORD_FIELDS = (
    "source_revision", "scope_digest", "confirmed_by", "specialist_ref",
    "provider_ref", "effect_ref", "readback_ref", "readback_provider_ref",
    "evidence_ref", "assurance",
)
EXTERNAL_ASSURANCE = {"external_system", "production"}

HOST_CHECK = "host-exact-revision-readback"
EXTERNAL_CHECK = "external-system-governed-act-readback"


class AcceptanceBindingRejected(RuntimeError):
    pass


def load_acceptance_record(path: str | Path, *, expected_revision: str) -> dict:
    """Read governed acceptance evidence and refuse anything that is not bound to this revision."""
    if not SHA40.fullmatch(expected_revision):
        raise AcceptanceBindingRejected("expected revision must be an exact 40-character git SHA")
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise AcceptanceBindingRejected(f"acceptance record is unreadable: {exc}") from None
    except json.JSONDecodeError as exc:
        raise AcceptanceBindingRejected(f"acceptance record is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise AcceptanceBindingRejected("acceptance record must be a JSON object")
    missing = [field for field in REQUIRED_RECORD_FIELDS if not str(data.get(field, "")).strip()]
    if missing:
        raise AcceptanceBindingRejected(f"acceptance record is missing required evidence: {missing}")
    revision = str(data["source_revision"]).strip().lower()
    if revision != expected_revision:
        raise AcceptanceBindingRejected(
            f"acceptance evidence was produced on revision {revision}, not the deployed {expected_revision}"
        )
    if str(data["assurance"]).strip() not in EXTERNAL_ASSURANCE:
        raise AcceptanceBindingRejected("production acceptance requires external-system assurance")
    if str(data["provider_ref"]).strip() == str(data["readback_provider_ref"]).strip():
        raise AcceptanceBindingRejected("execution provider cannot self-attest as the independent readback")
    if str(data["readback_ref"]).strip() == str(data["effect_ref"]).strip():
        raise AcceptanceBindingRejected("readback reference cannot be the effect reference")
    return data


def observe_active_release(release_root: str | Path, revision: str) -> tuple[str, str]:
    """Read the host back: the live release link must resolve to this revision's directory."""
    root = Path(release_root)
    current = root / "current"
    expected = root / "releases" / revision
    if not current.exists():
        raise AcceptanceBindingRejected(f"no active release link at {current}")
    resolved = current.resolve()
    if resolved != expected.resolve():
        raise AcceptanceBindingRejected(f"active release {resolved} is not the acceptance revision {expected}")
    return f"release:{revision}", f"release-dir:{resolved}"


def build_deployment(*, environment: str, revision: str, release_root: str | Path, host_evidence_ref: str) -> tuple[object, str]:
    """Re-derive the deployment result from host truth; the installer already promoted it."""
    release_ref, artifact_ref = observe_active_release(release_root, revision)
    candidate = ReleaseCandidate(
        release_ref=release_ref,
        artifact_ref=artifact_ref,
        source_revision=revision,
        environment=environment,
        verification_ref=host_evidence_ref,
        state=ReleaseState.VERIFIED,
    )

    def already_promoted_by_installer(_candidate: ReleaseCandidate) -> None:
        return None

    def read_back(env: str) -> DeploymentObservation:
        live_release_ref, live_artifact_ref = observe_active_release(release_root, revision)
        return DeploymentObservation(env, live_release_ref, live_artifact_ref, host_evidence_ref)

    result = DeploymentRuntime().promote_and_verify(
        candidate, promote=already_promoted_by_installer, read_back=read_back
    )
    return result, artifact_ref


def build_acceptance_run(connection: sqlite3.Connection, *, host_status: dict, record: dict):
    """Register the two evidence-bearing checks and require real external evidence to pass."""
    runtime = ProductionAcceptanceRuntime(connection)
    runtime.register(
        HOST_CHECK,
        lambda: AcceptanceResult(
            HOST_CHECK,
            bool(host_status.get("healthy")) and host_status.get("source_revision") == host_status.get("configured_revision"),
            str(host_status.get("evidence_ref", "")),
            f"heartbeat {host_status.get('heartbeat_state')} for {host_status.get('source_revision')}",
            "production",
        ),
        assurance="production",
    )
    runtime.register(
        EXTERNAL_CHECK,
        lambda: AcceptanceResult(
            EXTERNAL_CHECK,
            True,
            str(record["evidence_ref"]),
            f"{record['readback_provider_ref']} readback {record['readback_ref']} for effect {record['effect_ref']}",
            "external_system",
        ),
        assurance="external_system",
    )
    return runtime.run(require_external=True)


def bind(config: ProductionHostConfig, *, record_path: str | Path, release_root: str | Path) -> dict:
    record = load_acceptance_record(record_path, expected_revision=config.source_revision)
    host_status = read_host_status(config)
    if not host_status.get("healthy"):
        raise AcceptanceBindingRejected("host readback is not healthy; acceptance cannot be bound")
    if host_status.get("source_revision") != config.source_revision:
        raise AcceptanceBindingRejected("host heartbeat revision does not match the configured revision")

    deployment, artifact_ref = build_deployment(
        environment=config.environment,
        revision=config.source_revision,
        release_root=release_root,
        host_evidence_ref=str(host_status["evidence_ref"]),
    )
    connection = sqlite3.connect(config.db_path, timeout=30)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        acceptance = build_acceptance_run(connection, host_status=host_status, record=record)
        if acceptance.verdict is not AcceptanceVerdict.PASS:
            failed = [item.check_id for item in acceptance.results if not item.passed]
            raise AcceptanceBindingRejected(f"acceptance run is {acceptance.verdict}; failing checks: {failed}")
        release = ProductionControlPlane(connection).activate(
            deployment=deployment,
            artifact_ref=artifact_ref,
            source_revision=config.source_revision,
            acceptance=acceptance,
        )
        active = ProductionControlPlane(connection).active(config.environment)
    finally:
        connection.close()
    if active.source_revision != config.source_revision:
        raise AcceptanceBindingRejected("ledger readback does not own the deployed revision")
    return {
        "bound": {**asdict(release), "state": release.state.value},
        "ledger_readback": {**asdict(active), "state": active.state.value},
        "acceptance_run": {
            "run_id": acceptance.run_id,
            "verdict": acceptance.verdict.value,
            "results": [asdict(item) for item in acceptance.results],
        },
        "deployment_evidence_ref": deployment.evidence_ref,
        "external_evidence_ref": record["evidence_ref"],
        "external_readback_ref": record["readback_ref"],
        "external_effect_ref": record["effect_ref"],
        "scope_confirmed_by": record["confirmed_by"],
        "source_revision": config.source_revision,
    }


def verify(config: ProductionHostConfig) -> dict:
    connection = sqlite3.connect(config.db_path, timeout=30)
    try:
        active = ProductionControlPlane(connection).active(config.environment)
    finally:
        connection.close()
    return {
        **asdict(active),
        "state": active.state.value,
        "matches_configured_revision": active.source_revision == config.source_revision,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Bind governed acceptance evidence to the deployed revision")
    parser.add_argument("--acceptance-record", default=DEFAULT_RECORD)
    parser.add_argument("--release-root", default=DEFAULT_RELEASE_ROOT)
    parser.add_argument("--verify", action="store_true", help="read the ledger back without writing")
    args = parser.parse_args()
    config = ProductionHostConfig.from_env()
    try:
        payload = verify(config) if args.verify else bind(
            config, record_path=args.acceptance_record, release_root=args.release_root
        )
    except AcceptanceBindingRejected as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
