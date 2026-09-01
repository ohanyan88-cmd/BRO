"""Canonical provider execution gateway.

Production execution resolves a concrete versioned provider adapter before
HANDS dispatch. Callers choose provider identity/version, never an arbitrary
callable. IMMUNE authority is still evaluated by TaskSupervisor/ActionRuntime.
Retry safety is accepted only when the immutable provider contract declares the
operation idempotent; the ActionRequest cannot grant itself that property.
"""
from __future__ import annotations
from dataclasses import dataclass

from .action_runtime import ActionRequest
from .provider_adapters import ProviderAdapterRegistry, ProviderAdapterRejected
from .supervision import FlowBinding, TaskSupervisor


@dataclass(frozen=True)
class ProviderRoute:
    provider: str
    adapter_id: str
    version: str


class ProviderExecutionGateway:
    def __init__(self, supervisor: TaskSupervisor, providers: ProviderAdapterRegistry) -> None:
        self.supervisor = supervisor
        self.providers = providers

    def execute(
        self,
        binding: FlowBinding,
        request: ActionRequest,
        *,
        route: ProviderRoute,
        executor: str,
        now: str | None = None,
    ) -> dict:
        if request.adapter_id != route.adapter_id:
            raise ProviderAdapterRejected("action adapter_id does not match the selected provider route")
        adapter = self.providers.resolve(
            provider=route.provider,
            adapter_id=route.adapter_id,
            version=route.version,
            operation=request.operation,
        )
        if request.idempotency_guaranteed and not adapter.guarantees_idempotency(request.operation):
            raise ProviderAdapterRejected(
                "action cannot claim idempotency unless the selected provider contract guarantees it"
            )
        return self.supervisor.execute(
            binding,
            request,
            executor=executor,
            interface_version=adapter.version,
            adapter=adapter.invoke,
            now=now,
        )
