"""First usable BRO interaction surface over the FINAL-1 execution path."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Mapping

from .final_delivery import IntelligentInteractionRuntime, InteractionIntent


class InteractionSurface:
    """Small stateful facade for user request -> scope confirmation -> execution.

    This deliberately delegates interpretation, confirmation, specialist selection,
    execution, and independent readback to IntelligentInteractionRuntime. The
    surface owns presentation/state only; it does not create a second execution path.
    """

    def __init__(self, runtime: IntelligentInteractionRuntime) -> None:
        self.runtime = runtime

    def submit(self, request: str) -> dict[str, Any]:
        intent = self.runtime.interpret(request)
        return self._preview(intent)

    def confirm_and_execute(
        self,
        request_id: str,
        *,
        confirmed_by: str,
        scope_digest: str,
    ) -> dict[str, Any]:
        confirmation = self.runtime.confirm_scope(
            request_id,
            confirmed_by=confirmed_by,
            scope_digest=scope_digest,
        )
        receipt = self.runtime.execute(request_id)
        return {
            "request_id": request_id,
            "scope_digest": confirmation.scope_digest,
            "confirmed_by": confirmation.confirmed_by,
            "confirmed_at": confirmation.confirmed_at,
            "specialist_ref": receipt.specialist_ref,
            "provider_ref": receipt.provider_ref,
            "effect_ref": receipt.effect_ref,
            "readback_ref": receipt.readback_ref,
            "readback_provider_ref": receipt.readback_provider_ref,
            "evidence_ref": receipt.evidence_ref,
            "assurance": receipt.assurance.value,
        }

    def _preview(self, intent: InteractionIntent) -> dict[str, Any]:
        return {
            "request_id": intent.request_id,
            "raw_request": intent.raw_request,
            "model_ref": intent.model_ref,
            "interpreted_scope": list(intent.interpreted_scope),
            "constraints": list(intent.constraints),
            "success_conditions": list(intent.success_conditions),
            "material": intent.material,
            "scope_digest": self.runtime.scope_digest(intent.request_id),
            "requires_confirmation": intent.material,
        }
