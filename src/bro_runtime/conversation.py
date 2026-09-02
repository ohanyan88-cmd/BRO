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
    already-governed InteractionSurface. Optional durable hooks can restore/persist
    conversation and record evidenced outcomes without creating a second action path.
    Learning-hook failure never changes the truth of an already completed action.
    """

    def __init__(
        self,
        *,
        action_surface: InteractionSurface,
        router: Callable[[str, Sequence[ConversationMessage]], Mapping[str, Any]],
        responder: Callable[[InteractionMode, str, Sequence[ConversationMessage]], str],
        initial_history: Sequence[Mapping[str, str]] = (),
        message_recorder: Callable[[str, str, str], None] | None = None,
        outcome_recorder: Callable[[str, bool, Mapping[str, Any] | None, str], None] | None = None,
    ) -> None:
        self.action_surface = action_surface
        self.router = router
        self.responder = responder
        self.message_recorder = message_recorder
        self.outcome_recorder = outcome_recorder
        self._history: list[ConversationMessage] = []
        self._pending_actions: dict[str, str] = {}
        self._learning_errors: list[str] = []
        for item in initial_history:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                self._history.append(ConversationMessage(role, content))

    @property
    def history(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._history)

    @property
    def learning_errors(self) -> tuple[str, ...]:
        return tuple(self._learning_errors)

    def _remember(self, role: str, content: str, mode: str) -> None:
        self._history.append(ConversationMessage(role, content))
        if self.message_recorder is not None:
            self.message_recorder(role, content, mode)

    def _record_outcome(self, request: str, success: bool, receipt: Mapping[str, Any] | None, error_ref: str) -> None:
        if not request or self.outcome_recorder is None:
            return
        try:
            self.outcome_recorder(request, success, receipt, error_ref)
        except Exception as exc:
            self._learning_errors.append(f"{type(exc).__name__}:{exc}")

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
            self._pending_actions[preview["request_id"]] = request
            self._remember("user", request, mode.value)
            return {"mode": mode.value, "action": preview, "requires_confirmation": preview["requires_confirmation"]}

        reply = str(self.responder(mode, request, self.history)).strip()
        if not reply:
            raise ConversationRejected("conversational responder returned an empty reply")
        self._remember("user", request, mode.value)
        self._remember("assistant", reply, mode.value)
        return {"mode": mode.value, "response": reply, "requires_confirmation": False}

    def confirm_and_execute(self, request_id: str, *, confirmed_by: str, scope_digest: str) -> dict[str, Any]:
        request = self._pending_actions.get(request_id, "")
        try:
            receipt = self.action_surface.confirm_and_execute(
                request_id,
                confirmed_by=confirmed_by,
                scope_digest=scope_digest,
            )
        except Exception as exc:
            self._record_outcome(request, False, None, f"{type(exc).__name__}:{exc}")
            raise
        finally:
            self._pending_actions.pop(request_id, None)
        self._record_outcome(request, True, receipt, "")
        self._remember("assistant", f"Executed governed action: {receipt['effect_ref']}", InteractionMode.ACT.value)
        return receipt
