"""Claude Code CLI as a replaceable model backend for BRO.

BRO stays the authority. This is an inference backend and nothing else: it inherits
every prompt, routing and study rule from ExternalModel and replaces only the step
that turns a conversation into text, so switching provider cannot change what BRO
asks, what it retains, or what it will refuse.

Authentication is not this module's business and never becomes its business. The
official CLI owns the session; nothing here reads, copies, prints, stores or converts
a credential, and no API key is set, required or derived. The subprocess inherits the
environment the service already runs with, which is exactly how the CLI finds its own
authentication and exactly how it stays the only thing that holds it.

The CLI is invoked in the narrowest supported shape for model-response behaviour:
non-interactive print mode, JSON output, restricted (no command- or code-running tools
and no web fetch), no MCP servers, and an explicit deny list on top. The prompt travels
on stdin and the argument vector is a list, so no user text is ever concatenated into a
command line and no shell is involved at any point.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from .inference import BROInference, InferenceRejected, TransientInferenceError

# Removed from the session on top of --restricted. Belt and braces: BRO's HANDS are
# BRO's, and a model backend must not be able to reach for them.
DENIED_TOOLS = (
    "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent",
)

# Statuses the CLI may report from the upstream API that are worth one more try.
RETRYABLE_API_STATUSES = frozenset({"429", "500", "502", "503", "504"})

# Text the CLI prints when it has no usable session. Retrying cannot fix it.
UNAUTHENTICATED_MARKERS = ("not logged in", "please run /login", "authentication", "unauthorized")


@dataclass(frozen=True)
class ClaudeCodeCLIConfig:
    """What BRO needs to run the CLI. Deliberately no credential field of any kind."""

    model: str = "sonnet"
    executable: str = "claude"
    timeout_seconds: float = 180.0
    working_directory: str = "/"
    max_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    max_retry_wait_seconds: float = 10.0
    denied_tools: tuple[str, ...] = field(default_factory=lambda: DENIED_TOOLS)

    def __post_init__(self) -> None:
        if not self.model.strip() or self.model.startswith("test:"):
            raise InferenceRejected("a non-test Claude Code model is required")
        if not self.executable.strip():
            raise InferenceRejected("the Claude Code executable is required")
        if self.timeout_seconds <= 0:
            raise InferenceRejected("timeout_seconds must be positive")
        if self.max_attempts < 1:
            raise InferenceRejected("max_attempts must be at least 1")
        if self.retry_backoff_seconds < 0 or self.max_retry_wait_seconds < 0:
            raise InferenceRejected("retry waits must not be negative")

    @property
    def model_ref(self) -> str:
        return f"claude-code-cli:{self.model}"


class ClaudeCodeCLIModel(BROInference):
    """BRO's prompts, answered through the locally authenticated Claude Code CLI.

    The only method here that BRO's behaviour depends on is _complete. Everything the
    product says and refuses comes from BROInference, so replacing this backend cannot
    change a mode, a prompt, or a boundary.
    """

    def __init__(
        self,
        config: ClaudeCodeCLIConfig,
        *,
        runner: Callable[[list[str], str, float], subprocess.CompletedProcess] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        import time

        self.config = config
        self.sleep = sleep or time.sleep
        self.runner = runner or self._run
        self.last_model_usage: dict[str, Any] = {}

    # ------------------------------------------------------------------ invocation
    def argv(self) -> list[str]:
        """The exact command. A list, never a shell string."""
        return [
            self.config.executable,
            "--print",
            "--output-format", "json",
            "--restricted",
            "--strict-mcp-config",
            "--model", self.config.model,
            "--disallowed-tools", ",".join(self.config.denied_tools),
        ]

    @staticmethod
    def render(messages: Sequence[Mapping[str, str]]) -> tuple[str, str]:
        """Split a BRO conversation into a system preamble and a dialogue transcript."""
        system: list[str] = []
        dialogue: list[str] = []
        for item in messages:
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if role == "system":
                system.append(content)
            elif role in {"user", "assistant"}:
                dialogue.append(f"[{role}]\n{content}")
        return "\n\n".join(system), "\n\n".join(dialogue)

    def _run(self, argv: list[str], prompt: str, timeout: float) -> subprocess.CompletedProcess:
        # The prompt goes on stdin and the argument vector is a list, so no user text
        # ever reaches a command line and no interpreter is involved.
        try:
            return subprocess.run(
                argv, input=prompt, capture_output=True, text=True,
                timeout=timeout, cwd=self.config.working_directory, check=False,
            )
        except FileNotFoundError:
            raise InferenceRejected(
                f"Claude Code CLI is not available as {self.config.executable!r}"
            ) from None

    # -------------------------------------------------------------------- decoding
    @staticmethod
    def _sanitised(text: str, limit: int = 200) -> str:
        collapsed = " ".join(str(text or "").split())
        return collapsed[:limit]

    @classmethod
    def _classify_failure(cls, completed: subprocess.CompletedProcess) -> None:
        """Map a non-zero exit deterministically. Always raises."""
        detail = cls._sanitised(completed.stderr or completed.stdout)
        lowered = detail.lower()
        if any(marker in lowered for marker in UNAUTHENTICATED_MARKERS):
            raise InferenceRejected(
                f"Claude Code CLI has no usable session; authenticate it with the official "
                f"login for this identity (exit {completed.returncode}): {detail}"
            ) from None
        raise InferenceRejected(
            f"Claude Code CLI exited with status {completed.returncode}: {detail}"
        ) from None

    def _decode(self, completed: subprocess.CompletedProcess) -> str:
        if completed.returncode != 0:
            self._classify_failure(completed)
        try:
            envelope = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise InferenceRejected(
                f"Claude Code CLI did not return valid JSON: {self._sanitised(completed.stdout)}"
            ) from exc
        if not isinstance(envelope, dict):
            raise InferenceRejected("Claude Code CLI output must be a JSON object")

        usage = envelope.get("modelUsage")
        self.last_model_usage = dict(usage) if isinstance(usage, dict) else {}

        status = envelope.get("api_error_status")
        if status is not None and str(status) in RETRYABLE_API_STATUSES:
            raise TransientInferenceError(f"Claude Code CLI reported upstream status {status}")
        if envelope.get("is_error") or str(envelope.get("subtype", "success")) != "success":
            raise InferenceRejected(
                f"Claude Code CLI reported a failed turn: "
                f"{self._sanitised(envelope.get('result') or envelope.get('subtype'))}"
            )
        if str(envelope.get("stop_reason", "")) == "max_tokens":
            raise InferenceRejected("Claude Code CLI response was truncated before it finished")
        text = envelope.get("result")
        if not isinstance(text, str) or not text.strip():
            raise InferenceRejected("Claude Code CLI response did not contain output text")
        return text.strip()

    # ------------------------------------------------------------------ completion
    def _attempt(self, argv: list[str], prompt: str) -> str:
        """One invocation. Whether a timeout is worth retrying is the adapter's call,
        not the runner's, so a substituted runner cannot change the policy."""
        try:
            completed = self.runner(argv, prompt, self.config.timeout_seconds)
        except subprocess.TimeoutExpired:
            raise TransientInferenceError(
                f"Claude Code CLI did not answer within {self.config.timeout_seconds:g}s"
            ) from None
        return self._decode(completed)

    def _complete(self, messages: list[dict[str, str]]) -> str:
        system, dialogue = self.render(messages)
        argv = self.argv()
        if system:
            argv += ["--append-system-prompt", system]
        prompt = dialogue or system
        if not prompt.strip():
            raise InferenceRejected("a Claude Code request must carry a prompt")
        return self._with_retries(lambda: self._attempt(argv, prompt))

    def observed_models(self) -> tuple[str, ...]:
        """Which models actually answered, for provenance and diagnostics."""
        return tuple(sorted(self.last_model_usage))
