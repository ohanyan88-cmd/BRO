import unittest

from bro_runtime.action_runtime import AdapterResult, EffectState
from bro_runtime.provider_adapters import ProviderAdapter, ProviderAdapterRegistry, ProviderAdapterRejected, ProviderHealth


class ProviderAdapterRegistryTests(unittest.TestCase):
    def test_real_adapter_registry_routes_versioned_providers(self):
        calls=[]
        registry=ProviderAdapterRegistry()
        registry.register(ProviderAdapter(
            adapter_id="crm", provider="acme", version="v1", operations=("customer.create",),
            invoke=lambda inputs: calls.append(inputs) or AdapterResult({"customer_id":"C-1"},EffectState.CONFIRMED,("artifact:C-1",),("observation:C-1",)),
        ))
        result=registry.dispatch(provider="acme",adapter_id="crm",version="v1",operation="customer.create",inputs={"name":"Gev"})
        self.assertEqual(calls,[{"name":"Gev"}])
        self.assertEqual(result.result,{"customer_id":"C-1"})
        self.assertEqual(result.effect_state,EffectState.CONFIRMED)

    def test_version_and_operation_are_explicit_and_fail_closed(self):
        registry=ProviderAdapterRegistry()
        registry.register(ProviderAdapter("crm","acme","v2",("customer.read",),lambda _: AdapterResult({},EffectState.NONE)))
        with self.assertRaisesRegex(ProviderAdapterRejected,"unknown"):
            registry.resolve(provider="acme",adapter_id="crm",version="v1",operation="customer.read")
        with self.assertRaisesRegex(ProviderAdapterRejected,"support"):
            registry.resolve(provider="acme",adapter_id="crm",version="v2",operation="customer.delete")

    def test_unavailable_provider_cannot_be_selected(self):
        registry=ProviderAdapterRegistry()
        registry.register(ProviderAdapter("crm","acme","v1",("customer.read",),lambda _: AdapterResult({},EffectState.NONE),ProviderHealth.UNAVAILABLE))
        with self.assertRaisesRegex(ProviderAdapterRejected,"unavailable"):
            registry.resolve(provider="acme",adapter_id="crm",version="v1",operation="customer.read")


if __name__=="__main__": unittest.main()
