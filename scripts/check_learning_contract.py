#!/usr/bin/env python3
"""Fail closed if the governed self-learning contract drifts from runtime code.

contracts/learning_memory.json and contracts/learning_memory_readiness.json were
declarations that nothing executed: neither the Makefile nor CI referenced any gate
over them. Every invariant below must therefore name the source marker that enforces
it and the test file that exercises it, and an invariant with no mapping is an error
in its own right. The gate also refuses a second learning authority: outside the
boundary and the store, no production module may write a lesson.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/learning_memory.json"
READINESS = "contracts/learning_memory_readiness.json"
BOUNDARY = "src/bro_runtime/learning_boundary.py"
MEMORY = "src/bro_runtime/learning_memory.py"
CONVERSATION = "src/bro_runtime/conversation.py"
FINAL_DELIVERY = "src/bro_runtime/final_delivery.py"

INVARIANT_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "LEARN-ENTRY-001": (
        (BOUNDARY, "class GovernedLearningBoundary"),
        ("scripts/bro_interact.py", "GovernedLearningBoundary("),
        ("scripts/run_production_intelligent_acceptance.py", "GovernedLearningBoundary("),
    ),
    "LEARN-EVIDENCE-001": (
        (BOUNDARY, "EXTERNAL_ASSURANCE"),
        (BOUNDARY, "LearningEligibility.SELF_ATTESTED"),
        (MEMORY, "successful learning requires external evidence_ref"),
    ),
    "LEARN-FAILURE-001": (
        (MEMORY, "def _record_failure"),
        (MEMORY, "bro_failure_observations"),
    ),
    "LEARN-MODEL-001": (
        (BOUNDARY, 'proposed["pattern_key"] = self.pattern_key(context, receipt)'),
        (BOUNDARY, "def observations("),
    ),
    "LEARN-SECRET-001": (
        (BOUNDARY, "RECEIPT_FIELDS_FOR_EXTRACTION"),
        (BOUNDARY, "def sanitized_receipt"),
    ),
    "LEARN-CONFIDENCE-001": (
        (MEMORY, "def confidence_for"),
        (MEMORY, "def status_for"),
        (MEMORY, "DISPUTED_BELOW"),
    ),
    "LEARN-TRUTH-001": (
        (MEMORY, "def _contradictions_for"),
        (MEMORY, "BINDING_PREFIX"),
        (MEMORY, "bro_learning_contradictions"),
    ),
    "LEARN-PORTABLE-001": (
        (MEMORY, "class Provenance"),
        (BOUNDARY, "def capability_class"),
    ),
    "LEARN-CANDIDATE-001": (
        (MEMORY, "skill promotion requires prior explicit approval"),
        (MEMORY, "bro_skill_candidate_transitions"),
    ),
    "LEARN-ADVISORY-001": (
        (BOUNDARY, '"grants_authority": False'),
        (FINAL_DELIVERY, "material=self.material_floor or"),
    ),
    "LEARN-READ-001": (
        (MEMORY, "This is a read. It never writes"),
        (MEMORY, "def record_contradictions"),
        (BOUNDARY, '"contradictions_recorded"'),
    ),
    "LEARN-FAILSAFE-001": (
        (BOUNDARY, "learning must never rewrite an executed truth"),
        (CONVERSATION, "self._learning_errors.append"),
    ),
}

# Only these two modules may accumulate a lesson. Anything else doing so is a second
# learning authority, which is exactly what the boundary exists to prevent. This gate
# is exempt only because it quotes the tokens it searches for.
GATE = "scripts/check_learning_contract.py"
LESSON_WRITERS = {BOUNDARY, MEMORY}
SCAN_EXEMPT = LESSON_WRITERS | {GATE}
FORBIDDEN_VENDOR_TOKENS = ("cloudflare", "anthropic", "openai")


def _read(root: Path, relative: str) -> str | None:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    raw = _read(root, CONTRACT)
    if raw is None:
        return [f"missing learning contract: {CONTRACT}"]
    try:
        contract = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{CONTRACT}: {exc}"]
    if _read(root, READINESS) is None:
        errors.append(f"missing learning readiness contract: {READINESS}")

    entry = contract.get("learning_entry")
    if not isinstance(entry, dict):
        errors.append("contract must declare a single learning_entry")
        entry = {}
    for key in ("boundary", "store"):
        dotted = entry.get(key)
        if not isinstance(dotted, str) or "." not in dotted:
            errors.append(f"learning_entry.{key} must name a module-qualified class")
            continue
        module, _, symbol = dotted.rpartition(".")
        relative = "src/" + module.replace(".", "/") + ".py"
        source = _read(root, relative)
        if source is None:
            errors.append(f"learning_entry.{key}: missing module {relative}")
        elif f"class {symbol}" not in source:
            errors.append(f"learning_entry.{key}: {relative} does not define {symbol}")
    for relative in entry.get("submitting_paths", []):
        source = _read(root, relative)
        if source is None:
            errors.append(f"declared submitting path is missing: {relative}")
        elif "GovernedLearningBoundary" not in source:
            errors.append(f"{relative} is declared as a learning submitter but does not use the boundary")

    invariants = contract.get("invariants")
    if not isinstance(invariants, list) or not invariants:
        errors.append("contract must declare a non-empty invariants list")
        invariants = []
    seen: set[str] = set()
    for item in invariants:
        if not isinstance(item, dict):
            errors.append("invariant entry must be an object")
            continue
        iid = item.get("id")
        if not isinstance(iid, str) or not iid:
            errors.append("invariant requires an id")
            continue
        if iid in seen:
            errors.append(f"duplicate learning invariant id: {iid}")
        seen.add(iid)
        if not str(item.get("statement", "")).strip():
            errors.append(f"{iid}: statement required")
        enforcement = item.get("enforcement")
        if not isinstance(enforcement, list) or not enforcement:
            errors.append(f"{iid}: executable test enforcement required")
        else:
            for relative in enforcement:
                if not isinstance(relative, str) or not relative.startswith("tests/") or not relative.endswith(".py"):
                    errors.append(f"{iid}: enforcement must reference test files: {relative!r}")
                elif not (root / relative).is_file():
                    errors.append(f"{iid}: missing enforcement file: {relative}")
        if iid not in INVARIANT_MARKERS:
            errors.append(f"{iid}: declared learning invariant has no executable enforcement mapping")
            continue
        for relative, marker in INVARIANT_MARKERS[iid]:
            source = _read(root, relative)
            if source is None:
                errors.append(f"{iid}: missing enforcement file {relative}")
            elif marker not in source:
                errors.append(f"{iid}: {relative} lost its enforcement marker: {marker!r}")

    boundary = contract.get("truth_boundary")
    if not isinstance(boundary, dict) or not boundary.get("not_claimed"):
        errors.append("contract must declare what learning does not claim")
    else:
        joined = " ".join(str(item).lower() for item in boundary["not_claimed"])
        for phrase in ("model-weight training", "self-modifying code"):
            if phrase not in joined:
                errors.append(f"truth boundary must explicitly disclaim {phrase}")

    for directory in ("src/bro_runtime", "scripts"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.glob("*.py")):
            relative = str(path.relative_to(root))
            if relative in SCAN_EXEMPT:
                continue
            text = path.read_text(encoding="utf-8")
            if "record_outcome(" in text and "learning=" in text:
                errors.append(f"{relative}: writes lessons outside the governed learning boundary")

    schema_source = _read(root, MEMORY) or ""
    schema_block = schema_source.lower()
    for vendor in FORBIDDEN_VENDOR_TOKENS:
        if f'"{vendor}' in schema_block or f"'{vendor}" in schema_block:
            errors.append(f"durable learning storage must not encode {vendor}-specific semantics")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    contract = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
    print(
        f"PASS: {len(contract['invariants'])} governed self-learning invariants are contract-bound "
        "to one executable learning boundary"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
