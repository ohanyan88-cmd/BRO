"""Provider-neutral OpenAI-compatible external model boundary for BRO.

Only bounded task/conversation text is sent to the configured model endpoint.
Repository code, provider credentials, and effect-provider secrets are not part of
model prompts.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ExternalModelRejected(RuntimeError):
    pass


class TransientExternalModelError(ExternalModelRejected):
    """A failure worth one more try: throttling, a gateway hiccup, a dropped connection.

    It stays an ExternalModelRejected, so a caller that does not care about the
    distinction keeps failing exactly as before once the attempts are spent.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


# Statuses where trying again can succeed. A 4xx that is not throttling is a
# configuration or authorisation fact, and retrying it only hides it.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class ExternalModelConfig:
    provider: str
    api_key: str
    model: str
    api_url: str
    timeout_seconds: float = 60.0
    # Without an explicit output budget the endpoint truncates a long answer and the
    # caller sees malformed JSON instead of the real cause.
    max_output_tokens: int = 2048
    # Bounded on purpose. A brief throttle is worth riding out; an exhausted quota is a
    # wall, and a client that keeps knocking turns a clear failure into a long hang.
    max_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    max_retry_wait_seconds: float = 10.0

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
        if self.max_output_tokens <= 0:
            raise ExternalModelRejected("max_output_tokens must be positive")
        if self.max_attempts < 1:
            raise ExternalModelRejected("max_attempts must be at least 1")
        if self.retry_backoff_seconds < 0 or self.max_retry_wait_seconds < 0:
            raise ExternalModelRejected("retry waits must not be negative")

    @property
    def model_ref(self) -> str:
        return f"{self.provider}:openai-compatible:{self.model}"


class ExternalModel:
    """Minimal OpenAI-compatible chat-completions client."""

    def __init__(
        self, config: ExternalModelConfig,
        *,
        transport: Callable[[str, str, dict[str, str], bytes, float], Mapping[str, Any]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.transport = transport or self._http
        self.sleep = sleep

    @staticmethod
    def _http(method: str, url: str, headers: dict[str, str], data: bytes, timeout: float) -> Mapping[str, Any]:
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.load(response)
        except HTTPError as exc:
            ExternalModel._classify(exc)
        except URLError:
            raise TransientExternalModelError("external model API request failed") from None
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
        # A truncated answer is a different failure from a malformed one, and saying so
        # is the difference between fixing the output budget and hunting a parser bug.
        if str(first.get("finish_reason", "")).strip() == "length":
            raise ExternalModelRejected("external model response was truncated before it finished")
        message = first.get("message")
        if not isinstance(message, dict):
            raise ExternalModelRejected("external model response is missing message")
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise ExternalModelRejected("external model response did not contain output text")
        return text.strip()

    @staticmethod
    def _classify(exc: HTTPError) -> None:
        """Decide once whether a status is worth another attempt. Always raises."""
        message = f"external model API rejected request with status {exc.code}"
        if exc.code in RETRYABLE_STATUSES:
            raise TransientExternalModelError(message, retry_after=ExternalModel._retry_after(exc)) from None
        raise ExternalModelRejected(message) from None

    @staticmethod
    def _retry_after(exc: HTTPError) -> float | None:
        try:
            value = float((exc.headers or {}).get("retry-after", ""))
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def _wait_before(self, attempt: int, failure: TransientExternalModelError) -> float:
        requested = failure.retry_after
        backoff = self.config.retry_backoff_seconds * (2 ** (attempt - 1))
        chosen = backoff if requested is None else max(requested, 0.0)
        return min(chosen, self.config.max_retry_wait_seconds)

    def _with_retries(self, call: Callable[[], Any]) -> Any:
        """Try a bounded number of times, then fail with how many attempts were spent.

        Shared by every provider: whether the boundary is an HTTP endpoint or a local
        CLI, "worth one more try" and "give up and say how many" mean the same thing.
        """
        last: TransientExternalModelError | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                return call()
            except TransientExternalModelError as exc:
                last = exc
                if attempt == self.config.max_attempts:
                    break
                self.sleep(self._wait_before(attempt, exc))
        raise ExternalModelRejected(
            f"{last} (gave up after {self.config.max_attempts} attempt"
            f"{'s' if self.config.max_attempts != 1 else ''})"
        ) from None

    def _send(self, method: str, url: str, headers: dict[str, str], data: bytes) -> Mapping[str, Any]:
        return self._with_retries(
            lambda: self.transport(method, url, headers, data, self.config.timeout_seconds)
        )

    def _complete(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({
            "model": self.config.model, "messages": messages, "temperature": 0,
            "max_tokens": self.config.max_output_tokens,
        }).encode("utf-8")
        response = self._send(
            "POST",
            self.config.api_url,
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "BRO-production-intelligence",
            },
            payload,
        )
        return self._output_text(response)

    @staticmethod
    def _unfenced(text: str) -> str:
        """Unwrap one markdown code fence, and nothing else.

        Asked for bare JSON, the model sometimes returns a complete and correct object
        inside a ```json fence. That is a wrapper, not malformed output, and the fix
        belongs here rather than in every caller. This deliberately unwraps only a
        response that is entirely one fenced block: it never scans prose for braces,
        so a reply that merely mentions JSON is still rejected.
        """
        cleaned = text.strip()
        if not cleaned.startswith("```") or not cleaned.endswith("```"):
            return cleaned
        body = cleaned[3:-3]
        newline = body.find("\n")
        if newline == -1:
            return cleaned
        language = body[:newline].strip()
        if language and not language.isalnum():
            return cleaned
        return body[newline + 1:].strip()

    def json_object(self, *, instruction: str, request: str) -> dict[str, Any]:
        if not instruction.strip() or not request.strip():
            raise ExternalModelRejected("instruction and request are required")
        prompt = instruction.strip() + "\n\nReturn exactly one JSON object and no markdown fences or commentary.\n\nUser request:\n" + request.strip()
        try:
            parsed = json.loads(self._unfenced(self._complete([{"role": "user", "content": prompt}])))
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
                "Route the user's latest message for BRO. Required key: mode, exactly one of TALK, THINK, STUDY, ACT. "
                "TALK means ordinary conversation/discussion with no real-world effect. THINK means analysis/planning/read-only reasoning with no real-world effect. "
                "STUDY means the user is asking BRO to study, research, read, review or learn about something so the knowledge is retained; it is read-and-learn only and causes no real-world effect. "
                "ACT means the user is asking BRO to change an external system, send/write/create/delete/deploy/execute something, or otherwise cause a real-world effect. "
                "When uncertain between TALK/THINK/STUDY and ACT, never choose ACT; never infer permission to act."
            ),
            request=f"Conversation history: {context}\nLatest user message: {request}",
        )

    def study_plan(self, mission: str, available_sources: Sequence[str]) -> dict[str, Any]:
        """Choose an ordered curriculum from sources that already exist."""
        return self.json_object(
            instruction=(
                "Plan a small BRO study curriculum. Required key: topics, an array of objects with keys "
                "topic and source_ref. Every source_ref MUST be copied exactly from the supplied available "
                "sources list; never invent a path. Order the topics so the most foundational source is first. "
                "Return at most eight topics and no commentary."
            ),
            request=f"Study mission: {mission.strip()}\nAvailable sources: {json.dumps(list(available_sources))}",
        )

    def study_extract(self, topic: str, source_text: str, *, max_chars: int = 12000) -> dict[str, Any]:
        """Extract claims, each carrying the verbatim quote that would prove it."""
        return self.json_object(
            instruction=(
                "Extract what can be learned about the topic from the supplied source text. Required key: "
                "claims, an array of objects with keys claim, evidence_quote and inference. evidence_quote "
                "MUST be copied verbatim from the source text and be long enough to locate; leave it empty "
                "and set inference true when the claim is your reasoning rather than something the source "
                "states. Never invent a quote. Return at most five claims and no commentary."
            ),
            request=f"Topic: {topic.strip()}\nSource text:\n{source_text[:max_chars]}",
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
