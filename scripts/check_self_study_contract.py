#!/usr/bin/env python3
"""Fail closed if the governed self-study contract drifts from runtime code.

Self-study is the one capability where BRO's own words are the raw material, so the
gate's job is to keep the line between what a source says and what a model asserted.
Every declared invariant must name the source marker that enforces it and the test
file that exercises it; an invariant with no mapping is itself an error. The gate also
scans the study runtime for anything that could act -- a provider, an executor, a
network client, an approval or promotion call, or a direct write to the store.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/self_study.json"
STUDY = "src/bro_runtime/study_runtime.py"
MEMORY = "src/bro_runtime/learning_memory.py"
CURRICULUM = "src/bro_runtime/curriculum.py"
CONVERSATION = "src/bro_runtime/conversation.py"
INFERENCE = "src/bro_runtime/inference.py"
SURFACE = "scripts/bro_interact.py"

INVARIANT_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "STUDY-CURRICULUM-STATE-001": (
        (CURRICULUM, "class MasterCurriculum"),
        (CURRICULUM, "def master_complete"),
        (STUDY, "master_complete=bool("),
        (STUDY, "master_curriculum"),
    ),
    "STUDY-COVERAGE-EVIDENCE-001": (
        (CURRICULUM, "min_distinct_keywords"),
        (CURRICULUM, "def _sufficient_sources"),
        (CURRICULUM, "def _stale_sources"),
        (CURRICULUM, "class DomainState"),
    ),
    "STUDY-ANTI-REPETITION-001": (
        (STUDY, "def _offer"),
        (STUDY, "def _record_revisits"),
        (STUDY, "def _revisit_reasons"),
        (MEMORY, "def record_revisit"),
        (CURRICULUM, "class RevisitReason"),
    ),
    "STUDY-PLANNING-CONTEXT-001": (
        (CURRICULUM, "class PlanningContext"),
        (CURRICULUM, "PLANNING_SOURCE_LIMIT"),
        (STUDY, "def _planning_context"),
    ),
    "STUDY-ACQUISITION-OUTCOME-001": (
        (MEMORY, "def record_acquisition_outcome"),
        (MEMORY, "def acquisition_outcomes"),
    ),
    "STUDY-TARGETING-001": (
        (STUDY, "def derive_hints"),
        (STUDY, "def ordered_sources"),
        (STUDY, "Preference, not exclusion"),
        (STUDY, "no available source matches this mission's subject"),
    ),
    "STUDY-READONLY-001": (
        (STUDY, "class StudySourceReader"),
        (STUDY, "study source escapes the declared study root"),
        (STUDY, "read_bytes()"),
    ),
    "STUDY-VERIFY-001": (
        (STUDY, "def quote_is_in_source"),
        (STUDY, "MIN_EVIDENCE_QUOTE"),
        (MEMORY, "verified study knowledge requires a source-backed evidence quote"),
    ),
    "STUDY-KINDS-001": (
        (MEMORY, "class KnowledgeKind"),
        (MEMORY, "KIND_CONFIDENCE"),
        (STUDY, "def classify"),
    ),
    "STUDY-PROVENANCE-001": (
        (MEMORY, "source_digest TEXT NOT NULL"),
        (MEMORY, "provenance_json TEXT NOT NULL"),
        (MEMORY, "class VerificationState"),
    ),
    "STUDY-BOUNDED-001": (
        (STUDY, "class StudyStop"),
        (STUDY, "DIMINISHING_RETURNS"),
        (STUDY, "item_budget"),
    ),
    "STUDY-TRUTH-001": (
        (MEMORY, "def _knowledge_contradictions"),
        (MEMORY, "current_digests"),
        (STUDY, "def _mission_contradiction"),
    ),
    "STUDY-AUTHORITY-001": (
        (STUDY, "never produces permission"),
        (STUDY, '"grants_authority": False'),
    ),
    "STUDY-STORE-001": (
        (STUDY, "from .learning_memory import"),
        (MEMORY, "CREATE TABLE IF NOT EXISTS bro_study_knowledge"),
    ),
    "STUDY-PORTABLE-001": (
        (MEMORY, "class Provenance"),
        (STUDY, "Provenance, never ownership"),
    ),
    "STUDY-ROUTING-001": (
        (CONVERSATION, "if mode is InteractionMode.STUDY:"),
        (CONVERSATION, "study mode is not configured on this surface"),
        (INFERENCE, "STUDY means the user is asking BRO to study"),
        (SURFACE, "study_runner=run_study"),
    ),
}

# Nothing in the study runtime may act, and nothing may write the store behind its back.
FORBIDDEN_IN_STUDY = (
    "urlopen", "Request(", "socket", "subprocess", "os.system", "popen",
    "approve_candidate", "promote_candidate", "confirm_scope",
    "GitHubIssueCommentProvider", "IntelligentInteractionRuntime",
    "connection.execute", "INSERT INTO", "UPDATE ", "DELETE ",
    "write_text", "write_bytes", "mkdir", "unlink", "rmtree",
)


def _read(root: Path, relative: str) -> str | None:
    path = root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    raw = _read(root, CONTRACT)
    if raw is None:
        return [f"missing self-study contract: {CONTRACT}"]
    try:
        contract = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"{CONTRACT}: {exc}"]

    entry = contract.get("study_entry")
    if not isinstance(entry, dict):
        errors.append("contract must declare a single study_entry")
        entry = {}
    for key in ("runtime", "reader", "store"):
        dotted = entry.get(key)
        if not isinstance(dotted, str) or "." not in dotted:
            errors.append(f"study_entry.{key} must name a module-qualified class")
            continue
        module, _, symbol = dotted.rpartition(".")
        relative = "src/" + module.replace(".", "/") + ".py"
        source = _read(root, relative)
        if source is None:
            errors.append(f"study_entry.{key}: missing module {relative}")
        elif f"class {symbol}" not in source:
            errors.append(f"study_entry.{key}: {relative} does not define {symbol}")
    surface = entry.get("surface")
    surface_source = _read(root, surface) if isinstance(surface, str) else None
    if surface_source is None:
        errors.append(f"declared study surface is missing: {surface!r}")
    elif "GovernedStudyRuntime" not in surface_source:
        errors.append(f"{surface} is declared as the study surface but does not use the study runtime")
    mode = entry.get("mode")
    conversation = _read(root, CONVERSATION)
    if conversation is None:
        errors.append(f"missing {CONVERSATION}")
    elif not isinstance(mode, str) or f'{mode} = "{mode}"' not in conversation:
        errors.append(f"declared study mode is not an InteractionMode member: {mode!r}")

    if not contract.get("cycle"):
        errors.append("contract must declare the governed study cycle")

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
            errors.append(f"duplicate self-study invariant id: {iid}")
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
            errors.append(f"{iid}: declared self-study invariant has no executable enforcement mapping")
            continue
        for relative, marker in INVARIANT_MARKERS[iid]:
            source = _read(root, relative)
            if source is None:
                errors.append(f"{iid}: missing enforcement file {relative}")
            elif marker not in source:
                errors.append(f"{iid}: {relative} lost its enforcement marker: {marker!r}")

    boundary = contract.get("truth_boundary")
    if not isinstance(boundary, dict) or not boundary.get("not_claimed"):
        errors.append("contract must declare what self-study does not claim")
    else:
        joined = " ".join(str(item).lower() for item in boundary["not_claimed"])
        for phrase in ("model-weight training", "self-modifying code", "authority"):
            if phrase not in joined:
                errors.append(f"truth boundary must explicitly disclaim {phrase}")

    # Coverage is derived from the one memory. A writer here would make it a second store
    # that drifts from the knowledge it claims to summarise.
    curriculum_source = _read(root, CURRICULUM)
    if curriculum_source is None:
        errors.append(f"missing the curriculum runtime: {CURRICULUM}")
    else:
        for token in ("INSERT INTO", "UPDATE ", "DELETE ", "CREATE TABLE", "commit()"):
            if token in curriculum_source:
                errors.append(f"{CURRICULUM}: coverage is derived, never stored ({token!r})")

    study_source = _read(root, STUDY)
    if study_source is None:
        errors.append(f"missing study runtime: {STUDY}")
    else:
        for token in FORBIDDEN_IN_STUDY:
            if token in study_source:
                errors.append(f"{STUDY}: study must not be able to act or write directly ({token!r})")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    contract = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
    print(
        f"PASS: {len(contract['invariants'])} governed self-study invariants are contract-bound "
        "to a read-only study runtime"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
