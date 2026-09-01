#!/usr/bin/env python3
"""Fail closed when canonical truth-writing bypass patterns appear in production source."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("src/bro_runtime")

# These lower-level primitives remain testable, but canonical composition owns
# where production source may invoke them. A new call site must therefore change
# this gate deliberately instead of silently opening another truth path.
RULES = (
    ("Evidence(", {"immune.py", "evidence_verification.py"}, "canonical Evidence construction"),
    ("CompletionManifest(", {"immune.py"}, "canonical CompletionManifest construction"),
    (".evidence.record(", {"supervision.py"}, "direct Evidence ledger write"),
    (".evidence.evaluate_completion(", {"supervision.py"}, "direct completion evaluation"),
    ("._evaluate_bound_completion(", {"governed_supervision.py"}, "bound completion writer hook"),
    ("allow_legacy_callable=True", set(), "legacy callable live readback opt-in"),
)


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    source = root / SOURCE
    if not source.is_dir():
        return [f"missing production source directory: {source}"]
    for path in sorted(source.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token, allowed_files, label in RULES:
            if token in text and path.name not in allowed_files:
                errors.append(f"{path.relative_to(root)}: {label} is outside its canonical owner")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(RULES)} canonical truth-writing boundaries are source-enforced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
