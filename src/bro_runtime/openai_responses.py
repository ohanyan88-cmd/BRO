"""Production OpenAI Responses API boundary for BRO intelligent execution.

This module is deliberately small and dependency-free. It turns natural-language
requests into strict JSON records through a declared external model boundary. It
never treats repository tests or locally fabricated output as model evidence.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OpenAIResponsesRejected(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    api_key: str
    model: str
    api_url: str = "https://api.openai.com/v1/responses"
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise OpenAIResponsesRejected("OpenAI API key is required")
        if not self.model.strip() or self.model.startswith("test:"):
            raise OpenAIResponsesRejected("a non-test OpenAI model is required")
        if not self.api_url.startswith("https://"):
            raise OpenAIResponsesRejected("OpenAI API URL must use HTTPS")
        if self.timeout_seconds <= 0:
            raise OpenAIResponsesRejected("timeout_seconds must be positive")

    @property
    def model_ref(self) -> str:
        return f"openai:responses:{self.model}"


class OpenAIResponsesModel:
    """Minimal Responses API client with fail-closed JSON extraction."""

    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        transport: Callable[[str, str, dict[str, str], bytes, float], Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or self._http

    @staticmethod
    def _http(method: str, url: str, headers: dict[str, str], data: bytes, timeout: float) -> Mapping[str, Any]:
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise OpenAIResponsesRejected(f"OpenAI API rejected request with status {exc.code}") from None
        except URLError:
            raise OpenAIResponsesRejected("OpenAI API request failed") from None
        if not isinstance(result, dict):
            raise OpenAIResponsesRejected("OpenAI API returned invalid response state")
        return result

    @staticmethod
    def _output_text(response: Mapping[str, Any]) -> str:
        chunks: list[str] = []
        output = response.get("output")
        if not isinstance(output, list):
            raise OpenAIResponsesRejected("OpenAI response is missing output items")
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and part.get("type") == "output_text":
                    text = part.get("text")
                    if isinstance(text, str) and text:
                        chunks.append(text)
        text = "".join(chunks).strip()
        if not text:
            raise OpenAIResponsesRejected("OpenAI response did not contain output text")
        return text

    def json_object(self, *, instruction: str, request: str) -> dict[str, Any]:
        if not instruction.strip() or not request.strip():
            raise OpenAIResponsesRejected("instruction and request are required")
        prompt = (
            instruction.strip()
            + "\n\nReturn exactly one JSON object and no markdown fences or commentary."
            + "\n\nUser request:\n"
            + request.strip()
        )
        payload = json.dumps({"model": self.config.model, "input": prompt}).encode("utf-8")
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
        text = self._output_text(response)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OpenAIResponsesRejected("OpenAI model did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OpenAIResponsesRejected("OpenAI model output must be a JSON object")
        return parsed

    def interpret(self, request: str) -> dict[str, Any]:
        result = self.json_object(
            instruction=(
                "Interpret the request for BRO. Required keys: scope (non-empty array of strings), "
                "constraints (array of strings), success_conditions (non-empty array of strings), "
                "material (boolean). Do not invent permissions or completed effects."
            ),
            request=request,
        )
        return result

    def select_specialist(self, request: str, interpreted_scope: tuple[str, ...]) -> str:
        result = self.json_object(
            instruction=(
                "Select exactly one specialist for BRO before execution. Required key: specialist_ref, "
                "a non-empty stable reference such as specialist:github-operations. Base the choice only "
                "on the request and interpreted scope."
            ),
            request=f"{request}\nInterpreted scope: {json.dumps(list(interpreted_scope))}",
        )
        specialist = str(result.get("specialist_ref", "")).strip()
        if not specialist:
            raise OpenAIResponsesRejected("OpenAI specialist selection was empty")
        return specialist
