"""Governed secret mediation for provider execution boundaries.

Secrets are referenced by opaque IDs in canonical requests. Plaintext values are
resolved only after authority has been granted and are scoped to the exact
adapter boundary that is about to execute. They are never written into Action
Request bodies or Action Attempt sanitized inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .action_runtime import ActionRejected, ActionRuntime, ActionState, AdapterResult


class SecretRejected(ActionRejected):
    pass


@dataclass(frozen=True)
class SecretGrant:
    secret_ref: str
    adapter_id: str
    value: str


class SecretMediator:
    def __init__(self) -> None:
        self._secrets: dict[str, tuple[str, str]] = {}

    def register(self, secret_ref: str, adapter_id: str, value: str) -> None:
        if not secret_ref or not adapter_id or not value:
            raise SecretRejected("secret registration requires ref, adapter boundary, and value")
        if secret_ref in self._secrets:
            raise SecretRejected("secret references are immutable")
        self._secrets[secret_ref] = (adapter_id, value)

    def resolve(self, secret_ref: str, adapter_id: str) -> SecretGrant:
        bound = self._secrets.get(secret_ref)
        if bound is None:
            raise SecretRejected("unknown secret reference")
        allowed_adapter, value = bound
        if adapter_id != allowed_adapter:
            raise SecretRejected("secret cannot cross its approved adapter boundary")
        return SecretGrant(secret_ref, adapter_id, value)


class GovernedSecretDispatch:
    """Inject a secret only inside an already-authorized adapter invocation."""

    def __init__(self, actions: ActionRuntime, secrets: SecretMediator) -> None:
        self.actions = actions
        self.secrets = secrets

    def dispatch(
        self,
        request_id: str,
        interface_version: str,
        secret_bindings: Mapping[str, str],
        adapter: Callable[[dict], AdapterResult],
    ) -> dict:
        request = self.actions.get_request(request_id)
        if request["state"] != ActionState.AUTHORIZED:
            raise SecretRejected("secret resolution requires AUTHORIZED action")
        import json
        body = json.loads(request["body"])
        adapter_id = body["adapter_id"]
        grants = {name: self.secrets.resolve(ref, adapter_id) for name, ref in secret_bindings.items()}

        def invoke(public_inputs: dict) -> AdapterResult:
            runtime_inputs = dict(public_inputs)
            runtime_inputs.update({name: grant.value for name, grant in grants.items()})
            return adapter(runtime_inputs)

        return self.actions.dispatch(request_id, adapter_id, interface_version, invoke)
