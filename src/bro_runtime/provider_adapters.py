"""Versioned provider adapter registry for real external connectors.

Adapters describe how HANDS reaches a provider. Registration and selection do
not grant authority; ActionRuntime/IMMUNE SYSTEM still govern every effect.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable

from .action_runtime import AdapterResult


class ProviderAdapterRejected(ValueError):
    pass


class ProviderHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class ProviderAdapter:
    adapter_id: str
    provider: str
    version: str
    operations: tuple[str, ...]
    invoke: Callable[[dict], AdapterResult]
    health: ProviderHealth = ProviderHealth.HEALTHY

    @property
    def ref(self) -> str:
        return f"{self.provider}:{self.adapter_id}@{self.version}"


class ProviderAdapterRegistry:
    """In-process registry for concrete, versioned provider connectors."""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str, str], ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> ProviderAdapter:
        if not adapter.adapter_id.strip() or not adapter.provider.strip() or not adapter.version.strip():
            raise ProviderAdapterRejected("adapter_id, provider and version are required")
        if not adapter.operations:
            raise ProviderAdapterRejected("provider adapter requires operations")
        key = (adapter.provider, adapter.adapter_id, adapter.version)
        if key in self._adapters:
            raise ProviderAdapterRejected("provider adapter version is immutable")
        self._adapters[key] = adapter
        return adapter

    def resolve(self, *, provider: str, adapter_id: str, version: str, operation: str) -> ProviderAdapter:
        adapter = self._adapters.get((provider, adapter_id, version))
        if adapter is None:
            raise ProviderAdapterRejected("unknown provider adapter version")
        if operation not in adapter.operations:
            raise ProviderAdapterRejected("provider adapter does not support operation")
        if adapter.health is ProviderHealth.UNAVAILABLE:
            raise ProviderAdapterRejected("provider adapter is unavailable")
        return adapter

    def dispatch(self, *, provider: str, adapter_id: str, version: str, operation: str, inputs: dict) -> AdapterResult:
        adapter = self.resolve(provider=provider, adapter_id=adapter_id, version=version, operation=operation)
        result = adapter.invoke(dict(inputs))
        if not isinstance(result, AdapterResult):
            raise ProviderAdapterRejected("provider adapter must return AdapterResult")
        return result
