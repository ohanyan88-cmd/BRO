"""Canonical provider execution gateway.

Production execution resolves a concrete versioned provider adapter before
HANDS dispatch. Callers choose provider identity/version, never an arbitrary
callable. IMMUNE authority is still evaluated by TaskSupervisor/ActionRuntime.
Retry safety is derived from the immutable provider contract; the caller's
`idempotency_guaranteed` value is never trusted as a source of authority.
"""
from __future__ import annotations
from dataclasses import dataclass, replace

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
        guaranteed = adapter.guarantees_idempotency(request.operation)
        if guaranteed and not request.idempotency_key.strip():
            raise ProviderAdapterRejected("idempotent provider execution requires an idempotency key")
        governed_request = replace(request, idempotency_guaranteed=guaranteed)
        return self.supervisor.execute(
            binding,
            governed_request,
            executor=executor,
            interface_version=adapter.version,
            adapter=adapter.invoke,
            now=now,
        )
