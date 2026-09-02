"""BRO's one inference boundary.

Everything BRO is lives above this line: identity, TALK/THINK/STUDY/ACT routing, the
prompts and behavioural instructions, conversation semantics, memory, durable learning,
skills, governance, authority, approval, evidence, current-truth handling and execution
semantics. A backend below this line does exactly one thing -- turn a conversation into
text -- and its identity is recorded as provenance, never as authority and never as BRO.

A backend therefore implements a single method, ``_complete``. It does not get to
restate a prompt, redefine a mode, or decide what BRO will refuse. That rule is not
stylistic: an adapter that carried its own copy of these prompts had already drifted a
whole interaction mode behind the product before anyone noticed.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence


class InferenceRejected(RuntimeError):
    pass


class TransientInferenceError(InferenceRejected):
    """A failure worth one more try: throttling, a gateway hiccup, a timeout.

    It stays an InferenceRejected, so a caller that does not care about the distinction
    keeps failing exactly as before once the attempts are spent.
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class BROInference:
    """The prompts BRO asks. Subclasses supply only how a conversation becomes text.

    Subclasses provide ``self.config`` (carrying ``model_ref``, ``max_attempts``,
    ``retry_backoff_seconds`` and ``max_retry_wait_seconds``) and ``self.sleep``.
    """

    # ------------------------------------------------------------ backend contract
    def _complete(self, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError("an inference backend must implement _complete")

    # --------------------------------------------------------------- bounded retry
    def _wait_before(self, attempt: int, failure: TransientInferenceError) -> float:
        requested = failure.retry_after
        backoff = self.config.retry_backoff_seconds * (2 ** (attempt - 1))
        chosen = backoff if requested is None else max(requested, 0.0)
        return min(chosen, self.config.max_retry_wait_seconds)

    def _with_retries(self, call: Callable[[], Any]) -> Any:
        """Try a bounded number of times, then fail with how many attempts were spent.

        Bounded on purpose. A brief throttle is worth riding out; an exhausted quota is
        a wall, and a client that keeps knocking turns a clear failure into a long hang.
        """
        last: TransientInferenceError | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            try:
                return call()
            except TransientInferenceError as exc:
                last = exc
                if attempt == self.config.max_attempts:
                    break
                self.sleep(self._wait_before(attempt, exc))
        raise InferenceRejected(
            f"{last} (gave up after {self.config.max_attempts} attempt"
            f"{'s' if self.config.max_attempts != 1 else ''})"
        ) from None

    # ------------------------------------------------------------------- decoding
    @staticmethod
    def _unfenced(text: str) -> str:
        """Unwrap one markdown code fence, and nothing else.

        Asked for bare JSON, a model sometimes returns a complete and correct object
        inside a ```json fence. That is a wrapper, not malformed output. This
        deliberately unwraps only a response that is entirely one fenced block: it never
        scans prose for braces, so a reply that merely mentions JSON is still rejected.
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

    # -------------------------------------------------------------- BRO's prompts
    def json_object(self, *, instruction: str, request: str) -> dict[str, Any]:
        if not instruction.strip() or not request.strip():
            raise InferenceRejected("instruction and request are required")
        prompt = instruction.strip() + "\n\nReturn exactly one JSON object and no markdown fences or commentary.\n\nUser request:\n" + request.strip()
        try:
            parsed = json.loads(self._unfenced(self._complete([{"role": "user", "content": prompt}])))
        except json.JSONDecodeError as exc:
            raise InferenceRejected("model did not return valid JSON") from exc
        if not isinstance(parsed, dict):
            raise InferenceRejected("model output must be a JSON object")
        return parsed

    def interpret(self, request: str) -> dict[str, Any]:
        return self.json_object(instruction="Interpret the request for BRO. Required keys: scope (non-empty array of strings), constraints (array of strings), success_conditions (non-empty array of strings), material (boolean). Do not invent permissions or completed effects.", request=request)

    def select_specialist(self, request: str, interpreted_scope: tuple[str, ...]) -> str:
        result = self.json_object(instruction="Select exactly one specialist for BRO before execution. Required key: specialist_ref, a non-empty stable reference such as specialist:github-operations. Base the choice only on the request and interpreted scope.", request=f"{request}\nInterpreted scope: {json.dumps(list(interpreted_scope))}")
        specialist = str(result.get("specialist_ref", "")).strip()
        if not specialist:
            raise InferenceRejected("specialist selection was empty")
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
            raise InferenceRejected("conversational response is only valid for TALK or THINK")
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
