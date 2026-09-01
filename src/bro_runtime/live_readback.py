"""Live provider read-back for reconciling HANDS effects against external truth."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .action_runtime import ActionRejected, ActionRuntime, EffectState


class LiveReadbackRejected(ActionRejected):
    pass


@dataclass(frozen=True)
class ExternalObservation:
    """A current observation returned by the provider's read interface."""

    provider_ref: str
    resource_ref: str
    observed_state: object
    evidence_ref: str


class LiveReadbackRuntime:
    """Reconcile an attempted effect from a fresh provider read, never from write output."""

    def __init__(self, actions: ActionRuntime) -> None:
        self.actions = actions

    def reconcile_from_external_state(
        self,
        request_id: str,
        *,
        read: Callable[[], ExternalObservation],
        expected: Callable[[object], bool],
    ) -> ExternalObservation:
        attempt = self.actions.latest_attempt(request_id)
        if attempt is None:
            raise LiveReadbackRejected("live read-back requires an action attempt")
        observation = read()
        if not isinstance(observation, ExternalObservation):
            raise LiveReadbackRejected("provider read-back must return ExternalObservation")
        if not observation.provider_ref.strip() or not observation.resource_ref.strip() or not observation.evidence_ref.strip():
            raise LiveReadbackRejected("provider, resource and evidence references are required")
        effect = EffectState.CONFIRMED if expected(observation.observed_state) else EffectState.NONE
        self.actions.reconcile(request_id, effect, observation.evidence_ref)
        return observation
