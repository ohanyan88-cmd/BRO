import unittest

from bro_runtime.skills import Capability, CapabilityKind, CapabilityRegistry, CapabilityRejected, CapabilityStatus
from bro_runtime import SQLiteTaskStore


class CapabilityRegistryTests(unittest.TestCase):
    def setUp(self):
        self.db = SQLiteTaskStore()
        self.addCleanup(self.db.close)
        self.registry = CapabilityRegistry(self.db.connection)

    def capability(self, cid="cap:github", version=1, status=CapabilityStatus.ACTIVE):
        return Capability(
            capability_id=cid, version=version, kind=CapabilityKind.TOOL_ADAPTER,
            name="GitHub", description="repository operations", operations=("repo.read", "repo.write"),
            domains=("software",), input_contract_ref="contract:github:in", output_contract_ref="contract:github:out",
            dependency_refs=(), authority_requirements=("repo:write",), evidence_capabilities=("commit_sha",),
            provider_ref="provider:github", health_ref="health:github", status=status,
            recorded_at="2026-09-01T00:00:00Z",
        )

    def test_discovery_returns_capability_and_authority_requirements_without_granting_authority(self):
        self.registry.register(self.capability())
        matches = self.registry.discover(operations=("repo.write",), domains=("software",))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].matched_operations, ("repo.write",))
        self.assertEqual(matches[0].capability.authority_requirements, ("repo:write",))
        self.assertFalse(hasattr(matches[0], "authorized"))

    def test_latest_status_controls_discovery(self):
        self.registry.register(self.capability())
        self.registry.next_version("cap:github", status=CapabilityStatus.DISABLED)
        self.assertEqual(self.registry.discover(operations=("repo.read",)), ())

    def test_degraded_capability_remains_discoverable_but_explicit(self):
        self.registry.register(self.capability(status=CapabilityStatus.DEGRADED))
        match = self.registry.discover(operations=("repo.read",))[0]
        self.assertEqual(match.capability.status, CapabilityStatus.DEGRADED)

    def test_capability_versions_are_immutable(self):
        self.registry.register(self.capability())
        with self.assertRaisesRegex(CapabilityRejected, "immutable"):
            self.registry.register(self.capability())


if __name__ == "__main__":
    unittest.main()
