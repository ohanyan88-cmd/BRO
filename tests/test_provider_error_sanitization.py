import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.provider_adapters import ProviderAdapter, ProviderAdapterRegistry, ProviderAdapterRejected, ProviderHealth
from bro_runtime.provider_execution import ProviderExecutionGateway, ProviderRoute
from bro_runtime.secret_runtime import SecretMediator


def request():
    return ActionRequest(
        "action:error", "task:error", "write", "write", "resource:1", "prod", "crm", {},
        "auth:error", "R2", "REVERSIBLE", "idem:error", True, {"ok": True}, ("readback",),
        "assignment:error", "BRO",
    )


class InvokingSupervisor:
    def _execute_registered_provider(self, binding, governed_request, *, adapter, **kwargs):
        return adapter(dict(governed_request.input_parameters))


class ProviderErrorSanitizationTests(unittest.TestCase):
    def setUp(self):
        self.secret = "SUPER-SECRET-TOKEN"
        self.secrets = SecretMediator()
        self.secrets.register("secret:crm", "crm", self.secret)

    def gateway(self, invoke):
        providers = ProviderAdapterRegistry()
        providers.register(
            ProviderAdapter(
                "crm", "acme", "v1", ("write",), invoke,
                ProviderHealth.HEALTHY, ("write",), ("token",),
            )
        )
        return ProviderExecutionGateway(InvokingSupervisor(), providers, self.secrets)

    def route(self):
        return ProviderRoute("acme", "crm", "v1", (("token", "secret:crm"),))

    def test_generic_provider_exception_never_exposes_mediated_secret(self):
        def invoke(inputs):
            raise RuntimeError(f"SDK echoed token={inputs['token']}")

        with self.assertRaisesRegex(ProviderAdapterRejected, "details redacted") as raised:
            self.gateway(invoke).execute(object(), request(), route=self.route(), executor="worker")
        self.assertNotIn(self.secret, str(raised.exception))
        self.assertNotIsInstance(raised.exception.__cause__, RuntimeError)

    def test_provider_timeout_preserves_unknown_effect_signal_without_raw_details(self):
        def invoke(inputs):
            raise TimeoutError(f"timeout while using token={inputs['token']}")

        with self.assertRaisesRegex(TimeoutError, "details redacted") as raised:
            self.gateway(invoke).execute(object(), request(), route=self.route(), executor="worker")
        self.assertNotIn(self.secret, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_successful_provider_result_is_unchanged(self):
        seen = {}
        def invoke(inputs):
            seen.update(inputs)
            return AdapterResult({"ok": True}, EffectState.CONFIRMED)

        result = self.gateway(invoke).execute(object(), request(), route=self.route(), executor="worker")
        self.assertEqual(result.effect_state, EffectState.CONFIRMED)
        self.assertEqual(seen["token"], self.secret)


if __name__ == "__main__":
    unittest.main()
