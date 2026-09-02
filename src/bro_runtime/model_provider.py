"""Which backend performs inference. One line of configuration, not architecture.

BRO's active production backend is the Claude Code CLI. The seam stays here so another
backend can be added later by implementing BROInference and adding one case -- but an
unused implementation is not kept in the tree for that day. Git history is the history.
"""
from __future__ import annotations

from typing import Any, Mapping

from .claude_code_cli import ClaudeCodeCLIConfig, ClaudeCodeCLIModel
from .inference import InferenceRejected

CLAUDE_CODE_CLI = "claude-code-cli"
KNOWN_PROVIDERS = (CLAUDE_CODE_CLI,)


def _value(env: Mapping[str, str], name: str) -> str:
    return str(env.get(name, "")).strip()


def _required(env: Mapping[str, str], name: str) -> str:
    value = _value(env, name)
    if not value:
        raise InferenceRejected(f"missing required environment variable: {name}")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = _value(env, name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise InferenceRejected(f"{name} must be numeric") from exc


def build_model(env: Mapping[str, str]) -> Any:
    """Return the configured inference backend, or say exactly what is wrong."""
    provider = _required(env, "BRO_MODEL_PROVIDER").lower()
    if provider != CLAUDE_CODE_CLI:
        raise InferenceRejected(
            f"unsupported BRO_MODEL_PROVIDER {provider!r}; the active backend is "
            f"{CLAUDE_CODE_CLI}"
        )
    # No credential is read, required or derived here: the official CLI owns the
    # session, and BRO never turns a subscription into an API key.
    return ClaudeCodeCLIModel(ClaudeCodeCLIConfig(
        model=_required(env, "BRO_MODEL_NAME"),
        executable=_value(env, "BRO_MODEL_CLI_PATH") or "claude",
        timeout_seconds=_float(env, "BRO_MODEL_TIMEOUT_SECONDS", 180.0),
        working_directory=_value(env, "BRO_MODEL_CLI_WORKDIR") or "/",
        # Declared so production does not depend on whatever HOME an invocation happened
        # to inherit: the CLI keeps its session under HOME, and sudo drops it by default.
        home=_value(env, "BRO_MODEL_CLI_HOME"),
    ))
