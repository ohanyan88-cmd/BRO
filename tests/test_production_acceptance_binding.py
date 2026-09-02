import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.bind_production_acceptance import (
    AcceptanceBindingRejected,
    bind,
    load_acceptance_record,
    observe_active_release,
    verify,
)
from bro_runtime.production_control import ProductionControlPlane
from bro_runtime.production_host import ProductionHostConfig

REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def record(**overrides) -> dict:
    payload = {
        "source_revision": REVISION,
        "scope_digest": "c" * 64,
        "confirmed_by": "user:gev",
        "specialist_ref": "specialist:github-operations",
        "provider_ref": "github:github-issue-comment@v1:write",
        "effect_ref": "github-effect:issue-comment:1",
        "readback_ref": "github-readback:sha256:deadbeef",
        "readback_provider_ref": "github:github-issue-comment@v1:readback",
        "evidence_ref": "github-external-readback:comment:1",
        "assurance": "external_system",
    }
    payload.update(overrides)
    return payload


class AcceptanceBindingTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.release_root = self.root / "opt" / "bro"
        (self.release_root / "releases" / REVISION).mkdir(parents=True)
        (self.release_root / "releases" / OTHER_REVISION).mkdir(parents=True)
        os.symlink(self.release_root / "releases" / REVISION, self.release_root / "current")
        self.db = self.root / "runtime.sqlite3"
        self.record_path = self.root / "intelligent-acceptance.json"
        self.record_path.write_text(json.dumps(record()), encoding="utf-8")

    def config(self, revision: str = REVISION) -> ProductionHostConfig:
        return ProductionHostConfig.from_env({
            "BRO_ENVIRONMENT": "production",
            "BRO_SERVICE_ID": "bro",
            "BRO_INSTANCE_ID": "test-instance",
            "BRO_SOURCE_REVISION": revision,
            "BRO_DB_PATH": str(self.db),
            "BRO_LOCK_PATH": str(self.root / "primary.lock"),
            "BRO_HEARTBEAT_SECONDS": "10",
        })

    def heartbeat(self, *, revision: str = REVISION, state: str = "HEALTHY", age_seconds: float = 0.0):
        observed = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")
        connection = sqlite3.connect(self.db)
        try:
            ProductionControlPlane(connection).heartbeat(
                service_id="bro", instance_id="test-instance", revision=revision, state=state,
                evidence_ref=f"host-readback:sqlite:{revision}:{observed}", observed_at=observed,
            )
        finally:
            connection.close()

    # --- record validation -------------------------------------------------
    def test_record_from_a_different_revision_is_refused(self):
        self.record_path.write_text(json.dumps(record(source_revision=OTHER_REVISION)), encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceBindingRejected, "was produced on revision"):
            load_acceptance_record(self.record_path, expected_revision=REVISION)

    def test_repository_assurance_record_is_refused(self):
        self.record_path.write_text(json.dumps(record(assurance="repository")), encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceBindingRejected, "external-system assurance"):
            load_acceptance_record(self.record_path, expected_revision=REVISION)

    def test_self_attested_record_is_refused(self):
        self.record_path.write_text(
            json.dumps(record(readback_provider_ref="github:github-issue-comment@v1:write")), encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceBindingRejected, "self-attest"):
            load_acceptance_record(self.record_path, expected_revision=REVISION)

    def test_record_missing_evidence_is_refused(self):
        self.record_path.write_text(json.dumps(record(readback_ref="")), encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceBindingRejected, "missing required evidence"):
            load_acceptance_record(self.record_path, expected_revision=REVISION)

    # --- host release readback --------------------------------------------
    def test_release_link_pointing_elsewhere_is_refused(self):
        with self.assertRaisesRegex(AcceptanceBindingRejected, "is not the acceptance revision"):
            observe_active_release(self.release_root, OTHER_REVISION)

    def test_missing_release_link_is_refused(self):
        (self.release_root / "current").unlink()
        with self.assertRaisesRegex(AcceptanceBindingRejected, "no active release link"):
            observe_active_release(self.release_root, REVISION)

    # --- binding -----------------------------------------------------------
    def test_binding_writes_and_reads_back_the_deployed_revision(self):
        self.heartbeat()
        result = bind(self.config(), record_path=self.record_path, release_root=self.release_root)
        self.assertEqual(result["bound"]["source_revision"], REVISION)
        self.assertEqual(result["bound"]["state"], "ACTIVE")
        self.assertEqual(result["ledger_readback"]["source_revision"], REVISION)
        self.assertEqual(result["acceptance_run"]["verdict"], "PASS")
        assurances = {item["assurance"] for item in result["acceptance_run"]["results"] if item["passed"]}
        self.assertIn("external_system", assurances)
        readback = verify(self.config())
        self.assertTrue(readback["matches_configured_revision"])
        self.assertEqual(readback["acceptance_run_ref"], result["acceptance_run"]["run_id"])

    def test_binding_is_refused_when_the_host_heartbeat_is_stale(self):
        self.heartbeat(age_seconds=600)
        with self.assertRaisesRegex(AcceptanceBindingRejected, "not healthy"):
            bind(self.config(), record_path=self.record_path, release_root=self.release_root)

    def test_binding_is_refused_when_the_host_runs_another_revision(self):
        self.heartbeat(revision=OTHER_REVISION)
        self.record_path.write_text(json.dumps(record(source_revision=OTHER_REVISION)), encoding="utf-8")
        with self.assertRaises(AcceptanceBindingRejected):
            bind(self.config(OTHER_REVISION), record_path=self.record_path, release_root=self.release_root)

    def test_binding_is_refused_without_external_evidence(self):
        self.heartbeat()
        self.record_path.write_text(json.dumps(record(assurance="repository")), encoding="utf-8")
        with self.assertRaisesRegex(AcceptanceBindingRejected, "external-system assurance"):
            bind(self.config(), record_path=self.record_path, release_root=self.release_root)

    def test_rebinding_supersedes_the_previous_active_release(self):
        self.heartbeat()
        first = bind(self.config(), record_path=self.record_path, release_root=self.release_root)
        second = bind(self.config(), record_path=self.record_path, release_root=self.release_root)
        self.assertNotEqual(first["bound"]["record_id"], second["bound"]["record_id"])
        connection = sqlite3.connect(self.db)
        try:
            states = dict(connection.execute("SELECT record_id,state FROM production_releases").fetchall())
        finally:
            connection.close()
        self.assertEqual(states[first["bound"]["record_id"]], "BLOCKED")
        self.assertEqual(states[second["bound"]["record_id"]], "ACTIVE")


if __name__ == "__main__":
    unittest.main()
