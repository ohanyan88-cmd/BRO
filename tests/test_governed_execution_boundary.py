import unittest

from bro_runtime.action_runtime import ActionRequest, AdapterResult, EffectState
from bro_runtime.governed_supervision import GovernedTaskSupervisor
from bro_runtime.mind import SQLiteMindStore
from bro_runtime.provider_adapters import ProviderAdapter, ProviderAdapterRegistry
from bro_runtime.provider_execution import ProviderExecutionGateway, ProviderRoute
from bro_runtime.supervision import BoundaryViolation
from bro_runtime.task_runtime import SQLiteTaskStore


class GovernedExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tasks = SQLiteTaskStore()
        self.mind = SQLiteMindStore()
        self.addCleanup(self.tasks.close)
        self.addCleanup(self.mind.close)
        self.supervisor = GovernedTaskSupervisor(self.tasks, mind_store=self.mind)

    def test_canonical_supervisor_rejects_raw_callable_execution(self):
        with self.assertRaisesRegex(BoundaryViolation, "raw execution is disabled"):
            self.supervisor.execute(
                object(),
                object(),
                executor="worker",
                interface_version="v1",
                adapter=lambda _: AdapterResult({}, EffectState.NONE),
            )

    def test_provider_gateway_uses_internal_registered_dispatch_hook(self):
        providers = ProviderAdapterRegistry()
        providers.register(
            ProviderAdapter(
                "crm",
                "acme",
                "v1",
                ("write",),
                lambda _: AdapterResult({"ok": True}, EffectState.CONFIRMED),
            )
        )
        gateway = ProviderExecutionGateway(self.supervisor, providers)
        calls = []

        def governed_dispatch(binding, request, **kwargs):
            calls.append((binding, request, kwargs))
            return {"ok": True}

        self.supervisor._execute_registered_provider = governed_dispatch
        request = ActionRequest(
            "action:1", "task:1", "write", "write", "crm:1", "prod", "crm", {}, "auth:1", "R2",
            "REVERSIBLE", "idem:1", True, {"ok": True}, ("readback",), "assignment:1", "BRO",
        )
        binding = object()
        result = gateway.execute(
            binding,
            request,
            route=ProviderRoute("acme", "crm", "v1"),
            executor="worker",
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][0], binding)
        self.assertEqual(calls[0][1].adapter_id, "crm")
        self.assertEqual(calls[0][2]["interface_version"], "v1")


if __name__ == "__main__":
    unittest.main()
