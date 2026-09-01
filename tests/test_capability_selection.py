import unittest

from bro_runtime.capability_selection import CapabilitySelectionRejected, select_capability
from bro_runtime.provider_adapters import ProviderHealth
from bro_runtime.skills import Capability, CapabilityKind, CapabilityMatch, CapabilityStatus


T0 = "2026-09-01T00:00:00Z"


def match(capability_id, provider_ref, status=CapabilityStatus.ACTIVE):
    capability = Capability(
        capability_id, 1, CapabilityKind.TOOL_ADAPTER, capability_id, capability_id,
        ("write",), ("crm",), None, "artifact:out", (), ("write",), ("inspect",),
        provider_ref, f"health:{provider_ref}", status, T0,
    )
    return CapabilityMatch(capability, ("write",), ("crm",))


class CapabilitySelectionTests(unittest.TestCase):
    def test_healthy_provider_is_selected_over_degraded_provider(self):
        matches = (match("cap:degraded", "adapter:degraded"), match("cap:healthy", "adapter:healthy"))
        health = {"adapter:degraded": ProviderHealth.DEGRADED, "adapter:healthy": ProviderHealth.HEALTHY}
        selected = select_capability(matches, health.__getitem__)
        self.assertEqual(selected.capability.capability_id, "cap:healthy")

    def test_degraded_provider_is_used_when_it_is_the_best_available_route(self):
        matches = (match("cap:down", "adapter:down"), match("cap:degraded", "adapter:degraded"))
        health = {"adapter:down": ProviderHealth.UNAVAILABLE, "adapter:degraded": ProviderHealth.DEGRADED}
        selected = select_capability(matches, health.__getitem__)
        self.assertEqual(selected.capability.capability_id, "cap:degraded")

    def test_unavailable_providers_fail_closed_instead_of_being_routed(self):
        matches = (match("cap:down", "adapter:down"),)
        with self.assertRaisesRegex(CapabilitySelectionRejected, "no routable capability"):
            select_capability(matches, lambda _: ProviderHealth.UNAVAILABLE)

    def test_provider_health_never_promotes_a_degraded_capability_over_equal_healthy_status(self):
        matches = (
            match("cap:degraded-capability", "adapter:a", CapabilityStatus.DEGRADED),
            match("cap:active-capability", "adapter:b", CapabilityStatus.ACTIVE),
        )
        selected = select_capability(matches, lambda _: ProviderHealth.HEALTHY)
        self.assertEqual(selected.capability.capability_id, "cap:active-capability")


if __name__ == "__main__":
    unittest.main()
