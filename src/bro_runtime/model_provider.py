"""One place that decides which model backend BRO is speaking through.

Both production entrypoints used to carry their own copy of this branch, which is how
one of them can quietly drift from the other. Provider selection is configuration, not
architecture: adding a backend means adding a case here, and nothing that consumes a
model needs to know which one answered beyond the provenance it records.
"""
from __future__ import annotations

from typing import Any, Mapping

from .anthropic_messages import AnthropicMessagesConfig, AnthropicMessagesModel
from .claude_code_cli import ClaudeCodeCLIConfig, ClaudeCodeCLIModel
from .external_model import ExternalModel, ExternalModelConfig, ExternalModelRejected

CLAUDE_CODE_CLI = "claude-code-cli"
ANTHROPIC = "anthropic"

# Named for diagnostics and documentation. Anything else is treated as an
# OpenAI-compatible endpoint, which is how cloudflare and its successors are served.
KNOWN_PROVIDERS = (CLAUDE_CODE_CLI, ANTHROPIC, "cloudflare")


def _value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name, "")).strip()


def _required(env: Mapping[str, str], name: str) -> str:
    value = _value(env, name)
    if not value:
        raise ExternalModelRejected(f"missing required environment variable: {name}")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _value(env, name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ExternalModelRejected(f"{name} must be numeric") from exc


def build_model(env: Mapping[str, str]) -> Any:
    """Return the configured model backend, or say exactly what configuration is missing."""
    provider = _required(env, "BRO_MODEL_PROVIDER").lower()

    if provider == CLAUDE_CODE_CLI:
        # No credential is read, required or derived here: the official CLI owns the
        # session, and BRO never turns a subscription into an API key.
        return ClaudeCodeCLIModel(ClaudeCodeCLIConfig(
            model=_required(env, "BRO_MODEL_NAME"),
            executable=_value(env, "BRO_MODEL_CLI_PATH") or "claude",
            timeout_seconds=_float(env, "BRO_MODEL_TIMEOUT_SECONDS", 180.0),
            working_directory=_value(env, "BRO_MODEL_CLI_WORKDIR") or "/",
        ))

    if provider == ANTHROPIC:
        return AnthropicMessagesModel(AnthropicMessagesConfig(
            api_key=_required(env, "BRO_MODEL_API_KEY"),
            model=_required(env, "BRO_MODEL_NAME"),
            api_url=_value(env, "BRO_MODEL_API_URL") or "https://api.anthropic.com/v1/messages",
        ))

    return ExternalModel(ExternalModelConfig(
        provider=provider,
        api_key=_required(env, "BRO_MODEL_API_KEY"),
        model=_required(env, "BRO_MODEL_NAME"),
        api_url=_required(env, "BRO_MODEL_API_URL"),
        timeout_seconds=_float(env, "BRO_MODEL_TIMEOUT_SECONDS", 60.0),
    ))
