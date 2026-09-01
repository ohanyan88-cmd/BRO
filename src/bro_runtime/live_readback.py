"""Live provider read-back for reconciling HANDS effects against external truth.

Canonical read-back resolves a registered, versioned provider read operation.
Arbitrary callable read-back is disabled by default and exists only as an
explicit lower-level compatibility hook; production source must use registered
providers so caller-controlled write output cannot impersonate reality.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .action_runtime import ActionRejected, ActionRuntime, AdapterResult, EffectState
from .provider_adapters import ProviderAdapterRegistry, ProviderAdapterRejected
from .secret_runtime import SecretMediator


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
    """Reconcile an attempted effect from a fresh provider read, never write output."""

    def __init__(
        self,
        actions: ActionRuntime,
        providers: ProviderAdapterRegistry | None = None,
        *,
        allow_legacy_callable: bool = False,
        secrets: SecretMediator | None = None,
    ) -> None:
        self.actions = actions
        self.providers = providers
        self.allow_legacy_callable = allow_legacy_callable
        self.secrets = secrets

    def observe_from_provider(
        self,
        *,
        provider: str,
        adapter_id: str,
        version: str,
        operation: str,
        resource_ref: str,
        inputs: dict,
        secret_bindings: dict[str, str] | None = None,
    ) -> ExternalObservation:
        if self.providers is None:
            raise LiveReadbackRejected("registered provider read-back is not configured")
        try:
            adapter = self.providers.resolve(
                provider=provider,
                adapter_id=adapter_id,
                version=version,
                operation=operation,
            )
        except ProviderAdapterRejected as exc:
            raise LiveReadbackRejected(str(exc)) from exc
        bindings = secret_bindings or {}
        if set(bindings) != set(adapter.required_secrets):
            raise LiveReadbackRejected("provider read-back secret bindings must match declared requirements")
        if bindings and self.secrets is None:
            raise LiveReadbackRejected("provider read-back requires configured secret mediation")
        runtime_inputs = dict(inputs)
        if self.secrets:
            runtime_inputs.update({name: self.secrets.resolve(ref, adapter.adapter_id).value for name, ref in bindings.items()})
        result = adapter.invoke(runtime_inputs)
        if not isinstance(result, AdapterResult):
            raise LiveReadbackRejected("provider read-back must return AdapterResult")
        if result.effect_state is not EffectState.NONE:
            raise LiveReadbackRejected("provider read-back operation must be observational and effect-free")
        if not result.observation_refs:
            raise LiveReadbackRejected("provider read-back requires an observation reference")
        if not resource_ref.strip():
            raise LiveReadbackRejected("provider read-back requires a resource reference")
        return ExternalObservation(
            provider_ref=adapter.ref,
            resource_ref=resource_ref,
            observed_state=result.result,
            evidence_ref=result.observation_refs[0],
        )

    def reconcile_from_provider_state(
        self,
        request_id: str,
        *,
        provider: str,
        adapter_id: str,
        version: str,
        operation: str,
        resource_ref: str,
        inputs: dict,
        expected: Callable[[object], bool],
        secret_bindings: dict[str, str] | None = None,
    ) -> ExternalObservation:
        if self.actions.latest_attempt(request_id) is None:
            raise LiveReadbackRejected("live read-back requires an action attempt")
        observation = self.observe_from_provider(
            provider=provider,
            adapter_id=adapter_id,
            version=version,
            operation=operation,
            resource_ref=resource_ref,
            inputs=inputs,
            secret_bindings=secret_bindings,
        )
        effect = EffectState.CONFIRMED if expected(observation.observed_state) else EffectState.NONE
        self.actions.reconcile(request_id, effect, observation.evidence_ref)
        return observation

    def reconcile_from_external_state(
        self,
        request_id: str,
        *,
        read: Callable[[], ExternalObservation],
        expected: Callable[[object], bool],
    ) -> ExternalObservation:
        """Explicit legacy/test hook; disabled unless the caller opts in."""
        if not self.allow_legacy_callable:
            raise LiveReadbackRejected(
                "arbitrary callable read-back is disabled; use a registered provider read"
            )
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
