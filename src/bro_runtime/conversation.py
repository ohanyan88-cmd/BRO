"""Conversational routing in front of BRO's existing governed action path."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Mapping, Sequence

from .interaction_surface import InteractionSurface


class ConversationRejected(RuntimeError):
    pass


class InteractionMode(StrEnum):
    TALK = "TALK"
    THINK = "THINK"
    ACT = "ACT"


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    content: str


class ConversationalInteractionSurface:
    """Route natural language to TALK, THINK, or the existing governed ACT path.

    TALK and THINK are non-effecting conversational modes. ACT delegates to the
    already-governed InteractionSurface, preserving explicit confirmation,
    specialist selection, provider execution, and independent readback.
    """

    def __init__(
        self,
        *,
        action_surface: InteractionSurface,
        router: Callable[[str, Sequence[ConversationMessage]], Mapping[str, Any]],
        responder: Callable[[InteractionMode, str, Sequence[ConversationMessage]], str],
    ) -> None:
        self.action_surface = action_surface
        self.router = router
        self.responder = responder
        self._history: list[ConversationMessage] = []

    @property
    def history(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._history)

    def submit(self, request: str) -> dict[str, Any]:
        request = request.strip()
        if not request:
            raise ConversationRejected("request must not be empty")
        routed = dict(self.router(request, self.history))
        try:
            mode = InteractionMode(str(routed.get("mode", "")).strip().upper())
        except ValueError as exc:
            raise ConversationRejected("router must return TALK, THINK, or ACT") from exc

        if mode is InteractionMode.ACT:
            preview = self.action_surface.submit(request)
            self._history.append(ConversationMessage("user", request))
            return {"mode": mode.value, "action": preview, "requires_confirmation": preview["requires_confirmation"]}

        reply = str(self.responder(mode, request, self.history)).strip()
        if not reply:
            raise ConversationRejected("conversational responder returned an empty reply")
        self._history.extend((ConversationMessage("user", request), ConversationMessage("assistant", reply)))
        return {"mode": mode.value, "response": reply, "requires_confirmation": False}

    def confirm_and_execute(self, request_id: str, *, confirmed_by: str, scope_digest: str) -> dict[str, Any]:
        receipt = self.action_surface.confirm_and_execute(
            request_id,
            confirmed_by=confirmed_by,
            scope_digest=scope_digest,
        )
        self._history.append(ConversationMessage("assistant", f"Executed governed action: {receipt['effect_ref']}"))
        return receipt
