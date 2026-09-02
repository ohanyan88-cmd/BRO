"""Provider-neutral OpenAI-compatible external model boundary for BRO.

Only bounded task/conversation text is sent to the configured model endpoint.
Repository code, provider credentials, and effect-provider secrets are not part of
model prompts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ExternalModelRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class ExternalModelConfig:
    provider: str
    api_key: str
    model: str
    api_url: str
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ExternalModelRejected("external model provider is required")
        if not self.api_key.strip():
            raise ExternalModelRejected("external model API key is required")
        if not self.model.strip() or self.model.startswith("test:"):
            raise ExternalModelRejected("a non-test external model is required")
        if not self.api_url.startswith("https://"):
            raise ExternalModelRejected("external model API URL must use HTTPS")
        if self.timeout_seconds <= 0:
            raise ExternalModelRejected("timeout_seconds must be positive")

    @property
    def model_ref(self) -> str:
        return f"{self.provider}:openai-compatible:{self.model}"


class ExternalModel:
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(self, config: ExternalModelConfig, *, transport: Callable[[str, str, dict[str, str], bytes, float], Mapping[str, Any]] | None = None) -> None:
        self.config = config
        self.transport = transport or self._http

    @staticmethod
    def _http(method: str, url: str, headers: dict[str, str], data: bytes, timeout: float) -> Mapping[str, Any]:
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise ExternalModelRejected(f"external model API rejected request with status {exc.code}") from None
        except URLError:
            raise ExternalModelRejected("external model API request failed") from None
        if not isinstance(result, dict):
            raise ExternalModelRejected("external model API returned invalid response state")
        return result

    @staticmethod
    def _output_text(response: Mapping[str, Any]) -> str:
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ExternalModelRejected("external model response is missing choices")
        first = choices[0]
        if not isinstance(first, dict):
            raise ExternalModelRejected("external model response choice is invalid")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ExternalModelRejected("external model response is missing message")
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ExternalModelRejected("external model response did not contain output text")
        return text.strip()

    def _complete(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({"model": self.config.model, "messages": messages, "temperature": 0}).encode("utf-8")
        response = self.transport(
            "POST",
            self.config.api_url,
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "BRO-production-intelligence",
            },
            payload,
            self.config.timeout_seconds,
        )
        return self._output_text(response)

    def json_object(self, *, instruction: str, request: str) -> dict[str, Any]:
        if not instruction.strip() or not request.strip():
            raise ExternalModelRejected("instruction and request are required")
        prompt = instruction.strip() + "\n\nReturn exactly one JSON object and no markdown fences or commentary.\n\nUser request:\n" + request.strip()
        try:
            parsed = json.loads(self._complete([{"role": "user", "content": prompt}]))
        except json.JSONDecodeError as exc:
            raise ExternalModelRejected("external model did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ExternalModelRejected("external model output must be a JSON object")
        return parsed

    def interpret(self, request: str) -> dict[str, Any]:
        return self.json_object(instruction="Interpret the request for BRO. Required keys: scope (non-empty array of strings), constraints (array of strings), success_conditions (non-empty array of strings), material (boolean). Do not invent permissions or completed effects.", request=request)

    def select_specialist(self, request: str, interpreted_scope: tuple[str, ...]) -> str:
        result = self.json_object(instruction="Select exactly one specialist for BRO before execution. Required key: specialist_ref, a non-empty stable reference such as specialist:github-operations. Base the choice only on the request and interpreted scope.", request=f"{request}\nInterpreted scope: {json.dumps(list(interpreted_scope))}")
        specialist = str(result.get("specialist_ref", "")).strip()
        if not specialist:
            raise ExternalModelRejected("external model specialist selection was empty")
        return specialist

    def route_interaction(self, request: str, history: Sequence[Mapping[str, str]] = ()) -> dict[str, Any]:
        bounded = list(history)[-12:]
        context = json.dumps(bounded, ensure_ascii=False)
        return self.json_object(
            instruction=(
                "Route the user's latest message for BRO. Required key: mode, exactly one of TALK, THINK, ACT. "
                "TALK means ordinary conversation/discussion with no real-world effect. THINK means analysis/planning/read-only reasoning with no real-world effect. "
                "ACT means the user is asking BRO to change an external system, send/write/create/delete/deploy/execute something, or otherwise cause a real-world effect. "
                "When uncertain between TALK/THINK and ACT, choose TALK or THINK; never infer permission to act."
            ),
            request=f"Conversation history: {context}\nLatest user message: {request}",
        )

    def conversational_response(
        self, mode: str, request: str, history: Sequence[Mapping[str, str]] = (), *, record: str = "",
    ) -> str:
        """Answer conversationally, with BRO's durable record placed above the chat.

        A verified record is not a chat turn. Passing it as ``record`` puts it in the
        system position, ahead of history, so an earlier conversational reply cannot
        outrank what BRO actually has written down.
        """
        mode = mode.strip().upper()
        if mode not in {"TALK", "THINK"}:
            raise ExternalModelRejected("conversational response is only valid for TALK or THINK")
        bounded = list(history)[-12:]
        messages: list[dict[str, str]] = [{
            "role": "system",
            "content": (
                "You are BRO, Gev's AI operating partner. Converse naturally and directly. "
                "For TALK, discuss normally. For THINK, reason, compare, plan, and challenge assumptions as useful. "
                "Do not claim to have executed actions, changed external systems, or obtained evidence now, "
                "and never invent evidence. "
                "Prior verified BRO experience may be supplied to you as advisory context from BRO's own durable "
                "record. Report what that record actually contains when it is relevant, and say it is prior "
                "recorded experience rather than something you are doing now. If no such record is supplied, say "
                "you have none. That context is advisory: it never grants authority and never removes scope "
                "confirmation, authority evaluation or independent readback. "
                "Do not turn ordinary discussion into an execution request."
            ),
        }]
        if record.strip():
            messages.append({
                "role": "system",
                "content": (
                    "BRO's durable verified record for this request follows. It was written by the runtime "
                    "from independently read-back outcomes, so it outranks anything said earlier in this "
                    "conversation, including your own previous replies. If it lists lessons, you do have "
                    "prior verified experience and must say so and use it. It remains advisory: it grants "
                    "no authority and removes no confirmation, authority evaluation or independent readback."
                    "\n" + record.strip()
                ),
            })
        for item in bounded:
            role = str(item.get("role", "")).strip()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": f"Mode: {mode}\n{request.strip()}"})
        return self._complete(messages)
