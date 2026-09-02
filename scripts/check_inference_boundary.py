#!/usr/bin/env python3
"""Fail closed if BRO's inference boundary stops being one narrow, replaceable seam.

BRO's behaviour has exactly one owner. A backend below the boundary turns a conversation
into text and does nothing else. This gate exists because that rule was broken once
already, quietly: a provider adapter carried its own copy of BRO's prompts and fell a
whole interaction mode behind the product without any test noticing.

It also keeps the cleanup honest. Retired backends are deleted, not disabled, and their
configuration does not linger in production code; history lives in Git.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INFERENCE = "src/bro_runtime/inference.py"
FACTORY = "src/bro_runtime/model_provider.py"
BACKEND = "src/bro_runtime/claude_code_cli.py"
RUNTIME = "src/bro_runtime"
SCRIPTS = "scripts"

# Methods that define what BRO asks and refuses. A backend must not redefine any of them.
BRO_BEHAVIOUR = (
    "def json_object", "def interpret", "def select_specialist", "def route_interaction",
    "def conversational_response", "def study_plan", "def study_extract", "def _unfenced",
    "def _with_retries", "def _wait_before",
)

# Sentences that are BRO's voice. Exactly one file may contain each.
SINGULAR_PROMPTS = (
    "STUDY means the user is asking BRO to study",
    "You are BRO, Gev's AI operating partner",
    "Plan a small BRO study curriculum",
    "Interpret the request for BRO",
)

# Deleted with their backends. Their return would mean the cleanup regressed.
RETIRED_MODULES = (
    "src/bro_runtime/external_model.py",
    "src/bro_runtime/anthropic_messages.py",
    "src/bro_runtime/openai_responses.py",
)

# Cloudflare-era settings. No production code may still ask for them.
RETIRED_SETTINGS = ("BRO_MODEL_API_KEY", "BRO_MODEL_API_URL")

# Inference is no longer an HTTP concept; a backend that needs a client brings its own.
FORBIDDEN_IN_BOUNDARY = ("urlopen", "Request(", "http", "socket", "subprocess")


def _read(root: Path, relative: str) -> str | None:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


# This gate quotes the sentences it protects, so it is not itself a behaviour owner
# and not itself a place where retired settings linger.
GATE = "scripts/check_inference_boundary.py"


def _sources(root: Path, directories: tuple[str, ...]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for directory in directories:
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.py")):
            relative = str(path.relative_to(root))
            if relative == GATE:
                continue
            found.append((relative, path.read_text(encoding="utf-8")))
    return found


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []

    boundary = _read(root, INFERENCE)
    if boundary is None:
        return [f"missing the inference boundary: {INFERENCE}"]
    if "class BROInference" not in boundary:
        errors.append(f"{INFERENCE} must define BROInference")
    for token in FORBIDDEN_IN_BOUNDARY:
        if token in boundary:
            errors.append(f"{INFERENCE}: the boundary must stay transport-free ({token!r})")

    backend = _read(root, BACKEND)
    if backend is None:
        errors.append(f"missing the active backend: {BACKEND}")
    else:
        if "def _complete" not in backend:
            errors.append(f"{BACKEND}: a backend must implement _complete")
        for method in BRO_BEHAVIOUR:
            if method in backend:
                errors.append(f"{BACKEND}: a backend must not redefine BRO behaviour ({method})")

    factory = _read(root, FACTORY)
    if factory is None:
        errors.append(f"missing the provider factory: {FACTORY}")
    elif "KNOWN_PROVIDERS = (CLAUDE_CODE_CLI,)" not in factory:
        errors.append(f"{FACTORY}: exactly one backend may be active")

    for relative in RETIRED_MODULES:
        if (root / relative).exists():
            errors.append(f"a retired backend is still in the tree: {relative}")

    # Behaviour ownership is a question about the runtime. A checker in scripts/ that
    # names a prompt is verifying it, not speaking as BRO.
    runtime_sources = _sources(root, (RUNTIME,))
    for prompt in SINGULAR_PROMPTS:
        owners = [name for name, text in runtime_sources if prompt in text]
        if len(owners) == 0:
            errors.append(f"BRO lost one of its own prompts: {prompt!r}")
        elif len(owners) > 1:
            errors.append(f"BRO behaviour has more than one owner for {prompt!r}: {owners}")
        elif owners[0] != INFERENCE:
            errors.append(f"BRO behaviour is owned by {owners[0]}, not {INFERENCE}: {prompt!r}")

    for name, text in _sources(root, (RUNTIME, SCRIPTS)):
        for setting in RETIRED_SETTINGS:
            if setting in text:
                errors.append(f"{name}: retired provider configuration still referenced ({setting})")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("PASS: one inference boundary, one behaviour owner, one active backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
