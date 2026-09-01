"""Native Anthropic Messages external model boundary for BRO."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AnthropicMessagesRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class AnthropicMessagesConfig:
    api_key: str
    model: str
    api_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"
    timeout_seconds: float = 60.0
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise AnthropicMessagesRejected("Anthropic API key is required")
        if not self.model.strip() or self.model.startswith("test:"):
            raise AnthropicMessagesRejected("a non-test Anthropic model is required")
        if not self.api_url.startswith("https://"):
            raise AnthropicMessagesRejected("Anthropic API URL must use HTTPS")
        if self.timeout_seconds <= 0 or self.max_tokens <= 0:
            raise AnthropicMessagesRejected("timeout_seconds and max_tokens must be positive")

    @property
    def model_ref(self) -> str:
        return f"anthropic:messages:{self.model}"


class AnthropicMessagesModel:
    def __init__(self, config: AnthropicMessagesConfig, *, transport: Callable[[str, str, dict[str, str], bytes, float], Mapping[str, Any]] | None = None) -> None:
        self.config = config
        self.transport = transport or self._http

    @staticmethod
    def _http(method: str, url: str, headers: dict[str, str], data: bytes, timeout: float) -> Mapping[str, Any]:
        req = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(req, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise AnthropicMessagesRejected(f"Anthropic API rejected request with status {exc.code}") from None
        except URLError:
            raise AnthropicMessagesRejected("Anthropic API request failed") from None
        if not isinstance(result, dict):
            raise AnthropicMessagesRejected("Anthropic API returned invalid response state")
        return result

    @staticmethod
    def _text(response: Mapping[str, Any]) -> str:
        content = response.get("content")
        if not isinstance(content, list):
            raise AnthropicMessagesRejected("Anthropic response is missing content")
        text = "".join(str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text").strip()
        if not text:
            raise AnthropicMessagesRejected("Anthropic response did not contain text")
        return text

    def json_object(self, *, instruction: str, request: str) -> dict[str, Any]:
        prompt = instruction.strip() + "\n\nReturn exactly one JSON object and no markdown fences or commentary.\n\nUser request:\n" + request.strip()
        payload = json.dumps({"model": self.config.model, "max_tokens": self.config.max_tokens, "messages": [{"role": "user", "content": prompt}]}).encode()
        response = self.transport("POST", self.config.api_url, {"x-api-key": self.config.api_key, "anthropic-version": self.config.anthropic_version, "content-type": "application/json", "accept": "application/json", "user-agent": "BRO-production-intelligence"}, payload, self.config.timeout_seconds)
        try:
            parsed = json.loads(self._text(response))
        except json.JSONDecodeError as exc:
            raise AnthropicMessagesRejected("Anthropic model did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise AnthropicMessagesRejected("Anthropic model output must be a JSON object")
        return parsed

    def interpret(self, request: str) -> dict[str, Any]:
        return self.json_object(instruction="Interpret the request for BRO. Required keys: scope (non-empty array of strings), constraints (array of strings), success_conditions (non-empty array of strings), material (boolean). Do not invent permissions or completed effects.", request=request)

    def select_specialist(self, request: str, interpreted_scope: tuple[str, ...]) -> str:
        result = self.json_object(instruction="Select exactly one specialist for BRO before execution. Required key: specialist_ref, a non-empty stable reference such as specialist:github-operations. Base the choice only on the request and interpreted scope.", request=f"{request}\nInterpreted scope: {json.dumps(list(interpreted_scope))}")
        specialist = str(result.get("specialist_ref", "")).strip()
        if not specialist:
            raise AnthropicMessagesRejected("Anthropic specialist selection was empty")
        return specialist
