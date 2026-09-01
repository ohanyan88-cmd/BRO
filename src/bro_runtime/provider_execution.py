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
from .secret_runtime import SecretMediator, SecretRejected
from .supervision import FlowBinding, TaskSupervisor


@dataclass(frozen=True)
class ProviderRoute:
    provider: str
    adapter_id: str
    version: str
    secret_bindings: tuple[tuple[str, str], ...] = ()


class ProviderExecutionGateway:
    def __init__(self, supervisor: TaskSupervisor, providers: ProviderAdapterRegistry, secrets: SecretMediator | None = None) -> None:
        self.supervisor = supervisor
        self.providers = providers
        self.secrets = secrets

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
        binding_names = [name for name, _ in route.secret_bindings]
        if len(binding_names) != len(set(binding_names)):
            raise ProviderAdapterRejected("provider secret bindings contain duplicate names")
        bindings = dict(route.secret_bindings)
        if set(bindings) != set(adapter.required_secrets):
            raise ProviderAdapterRejected("provider secret bindings must exactly match its declared requirements")
        if bindings and self.secrets is None:
            raise ProviderAdapterRejected("provider requires configured secret mediation")

        def mediated_invoke(public_inputs: dict):
            # This closure is entered by ActionRuntime only after its current IMMUNE
            # verdict has authorized this exact request. Plaintext never enters the
            # request, attempt inputs, supervisor events, or persisted error text.
            try:
                runtime_inputs = dict(public_inputs)
                runtime_inputs.update({name: self.secrets.resolve(ref, adapter.adapter_id, now=now).value
                                       for name, ref in bindings.items()})
                return adapter.invoke(runtime_inputs)
            except SecretRejected:
                raise
            except TimeoutError:
                raise TimeoutError("registered provider timed out; details redacted") from None
            except Exception:
                raise ProviderAdapterRejected("registered provider invocation failed; details redacted") from None
        dispatch = getattr(self.supervisor, "_execute_registered_provider", None)
        if dispatch is None:
            raise ProviderAdapterRejected(
                "provider execution requires a governed supervisor registered-provider dispatch boundary"
            )
        return dispatch(
            binding,
            governed_request,
            executor=executor,
            interface_version=adapter.version,
            adapter=mediated_invoke,
            now=now,
        )
