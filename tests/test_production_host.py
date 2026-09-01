from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from bro_runtime.production_host import ProductionHost, ProductionHostConfig, ProductionHostRejected, read_host_status


class ProductionHostTests(unittest.TestCase):
    def _env(self, root: str) -> dict[str, str]:
        return {
            "BRO_ENVIRONMENT": "production",
            "BRO_SERVICE_ID": "bro",
            "BRO_INSTANCE_ID": "node-1",
            "BRO_SOURCE_REVISION": "a" * 40,
            "BRO_DB_PATH": f"{root}/runtime.sqlite3",
            "BRO_LOCK_PATH": f"{root}/primary.lock",
            "BRO_HEARTBEAT_SECONDS": "5",
        }

    def test_config_fails_closed_on_non_production_or_floating_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = self._env(tmp)
            env["BRO_ENVIRONMENT"] = "dev"
            with self.assertRaises(ProductionHostRejected):
                ProductionHostConfig.from_env(env)
            env = self._env(tmp)
            env["BRO_SOURCE_REVISION"] = "main"
            with self.assertRaises(ProductionHostRejected):
                ProductionHostConfig.from_env(env)

    def test_heartbeat_readback_is_bound_to_exact_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ProductionHostConfig.from_env(self._env(tmp))
            host = ProductionHost(config)
            host.heartbeat()
            status = read_host_status(config, max_age_seconds=30)
            self.assertTrue(status["healthy"])
            self.assertEqual(status["source_revision"], "a" * 40)
            self.assertEqual(status["assurance"], "host_readback")
            host.connection.close()

    def test_stale_heartbeat_fails_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = ProductionHostConfig.from_env(self._env(tmp))
            host = ProductionHost(config)
            host.control.heartbeat(
                service_id=config.service_id,
                instance_id=config.instance_id,
                revision=config.source_revision,
                state="HEALTHY",
                evidence_ref="host-readback:test",
                observed_at="2026-01-01T00:00:00Z",
            )
            host.connection.close()
            status = read_host_status(config, now_epoch=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc).timestamp(), max_age_seconds=10)
            self.assertFalse(status["healthy"])


if __name__ == "__main__":
    unittest.main()
