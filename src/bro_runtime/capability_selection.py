"""Health-aware capability selection without granting execution authority."""
from __future__ import annotations

from typing import Callable

from .provider_adapters import ProviderHealth
from .skills import CapabilityMatch, CapabilityStatus


class CapabilitySelectionRejected(ValueError):
    pass


_HEALTH_RANK = {
    ProviderHealth.HEALTHY: 0,
    ProviderHealth.DEGRADED: 1,
}


def select_capability(
    matches: tuple[CapabilityMatch, ...],
    health_for: Callable[[str], ProviderHealth],
) -> CapabilityMatch:
    """Choose the healthiest routable provider-backed capability deterministically.

    Health influences routing only. It never grants authority; IMMUNE still
    evaluates every eventual action independently.
    """
    candidates: list[tuple[int, int, str, CapabilityMatch]] = []
    for match in matches:
        capability = match.capability
        if not capability.provider_ref:
            continue
        health = ProviderHealth(health_for(capability.provider_ref))
        if health is ProviderHealth.UNAVAILABLE:
            continue
        capability_penalty = 0 if capability.status is CapabilityStatus.ACTIVE else 1
        candidates.append((_HEALTH_RANK[health], capability_penalty, capability.capability_id, match))
    if not candidates:
        raise CapabilitySelectionRejected("no routable capability has an available provider")
    candidates.sort(key=lambda item: item[:3])
    return candidates[0][3]
