import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.provider_adapters import ProviderAdapter, ProviderAdapterRegistry, ProviderHealth
from bro_runtime.provider_execution import ProviderExecutionGateway, ProviderRoute


def request(*, claimed=True, key="idem:1"):
    return ActionRequest(
        "action:1", "task:1", "write", "write", "resource:1", "prod", "crm", {}, "auth:1", "R2",
        "REVERSIBLE", key, claimed, {"ok": True}, ("readback",), "assignment:1", "BRO",
    )


class ProviderIdempotencyContractTests(unittest.TestCase):
    def test_caller_claim_is_downgraded_when_provider_does_not_guarantee_it(self):
        providers = ProviderAdapterRegistry()
        providers.register(
            ProviderAdapter("crm", "acme", "v1", ("write",), lambda _: AdapterResult({}, EffectState.NONE))
        )

        class Supervisor:
            def _execute_registered_provider(self, binding, governed_request, **kwargs):
                self.request = governed_request
                return {"ok": True}

        supervisor = Supervisor()
        gateway = ProviderExecutionGateway(supervisor, providers)
        gateway.execute(object(), request(claimed=True), route=ProviderRoute("acme", "crm", "v1"), executor="worker")
        self.assertFalse(supervisor.request.idempotency_guaranteed)

    def test_provider_contract_can_grant_retry_safety_even_if_caller_did_not_claim_it(self):
        providers = ProviderAdapterRegistry()
        providers.register(
            ProviderAdapter(
                "crm", "acme", "v1", ("write",), lambda _: AdapterResult({}, EffectState.NONE),
                ProviderHealth.HEALTHY, ("write",),
            )
        )

        class Supervisor:
            def _execute_registered_provider(self, binding, governed_request, **kwargs):
                self.request = governed_request
                return {"ok": True}

        supervisor = Supervisor()
        gateway = ProviderExecutionGateway(supervisor, providers)
        gateway.execute(object(), request(claimed=False), route=ProviderRoute("acme", "crm", "v1"), executor="worker")
        self.assertTrue(supervisor.request.idempotency_guaranteed)

    def test_idempotent_provider_requires_a_real_key(self):
        providers = ProviderAdapterRegistry()
        providers.register(
            ProviderAdapter(
                "crm", "acme", "v1", ("write",), lambda _: AdapterResult({}, EffectState.NONE),
                ProviderHealth.HEALTHY, ("write",),
            )
        )
        gateway = ProviderExecutionGateway(object(), providers)
        with self.assertRaisesRegex(ValueError, "idempotency key"):
            gateway.execute(object(), request(key=""), route=ProviderRoute("acme", "crm", "v1"), executor="worker")

    def test_provider_cannot_mark_an_undeclared_operation_idempotent(self):
        providers = ProviderAdapterRegistry()
        with self.assertRaisesRegex(ValueError, "must be declared"):
            providers.register(
                ProviderAdapter(
                    "crm", "acme", "v1", ("read",), lambda _: AdapterResult({}, EffectState.NONE),
                    ProviderHealth.HEALTHY, ("write",),
                )
            )


if __name__ == "__main__":
    unittest.main()
