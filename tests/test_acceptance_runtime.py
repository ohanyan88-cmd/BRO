import sqlite3
import unittest

from bro_runtime.acceptance_runtime import AcceptanceResult, AcceptanceVerdict, ProductionAcceptanceRuntime


class ProductionAcceptanceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.runtime = ProductionAcceptanceRuntime(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_external_requirement_blocks_repository_only_acceptance(self):
        self.runtime.register(
            "runtime.integrity",
            lambda: AcceptanceResult("runtime.integrity", True, "sqlite:integrity:ok", "database integrity verified", "repository"),
            assurance="repository",
        )
        run = self.runtime.run(require_external=True)
        self.assertEqual(run.verdict, AcceptanceVerdict.BLOCKED)
        self.assertEqual(self.runtime.fetch(run.run_id).verdict, AcceptanceVerdict.BLOCKED)

    def test_all_required_checks_with_external_evidence_pass(self):
        self.runtime.register(
            "runtime.integrity",
            lambda: AcceptanceResult("runtime.integrity", True, "sqlite:integrity:ok", "database integrity verified", "repository"),
            assurance="repository",
        )
        self.runtime.register(
            "provider.external-readback",
            lambda: AcceptanceResult("provider.external-readback", True, "github:readback:sha256:abc", "external state matched", "external_system"),
            assurance="external_system",
        )
        run = self.runtime.run(require_external=True)
        self.assertEqual(run.verdict, AcceptanceVerdict.PASS)
        self.assertEqual(len(run.results), 2)

    def test_probe_cannot_self_upgrade_assurance(self):
        self.runtime.register(
            "truth.boundary",
            lambda: AcceptanceResult("truth.boundary", True, "fake:evidence", "claims external without registration", "production"),
            assurance="repository",
        )
        with self.assertRaises(Exception):
            self.runtime.run()


if __name__ == "__main__":
    unittest.main()
