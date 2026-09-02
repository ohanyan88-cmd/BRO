#!/usr/bin/env python3
"""Fail closed if the governed knowledge library drifts from the contract.

The library exists to keep two things apart that look adjacent: acquiring a document and
believing one. So the gate checks the seam from both sides. Every declared invariant must
name a source marker that enforces it and a test file that exercises it. The library must
reach no network. The study runtime must reach no network and no acquisition tool. And the
shelf manifest must describe real, attributed, https sources -- an unattributed shelf is a
document with no authority, which is the one thing the corpus may not contain.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/knowledge_library.json"
SHELVES = "contracts/knowledge_shelves.json"
LIBRARY = "src/bro_runtime/knowledge_library.py"
MEMORY = "src/bro_runtime/learning_memory.py"
STUDY = "src/bro_runtime/study_runtime.py"
ACQUIRE = "scripts/bro_acquire_knowledge.py"
SURFACE = "scripts/bro_interact.py"
GATE = "scripts/check_knowledge_library_contract.py"

INVARIANT_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "LIBRARY-APPROVAL-001": (
        (LIBRARY, "def verify_corpus"),
        (LIBRARY, "present in the corpus but not approved for study"),
        (LIBRARY, "APPROVED_FOR_STUDY"),
        (LIBRARY, "requires a recorded {basis_column}"),
    ),
    "LIBRARY-LIFECYCLE-001": (
        (LIBRARY, "def screen"),
        (LIBRARY, "def approve"),
        (LIBRARY, "bro_knowledge_transitions"),
        (LIBRARY, "def _advance"),
    ),
    "LIBRARY-INTEGRITY-001": (
        (LIBRARY, "content changed since it was screened"),
        (LIBRARY, "content differs from what was approved"),
    ),
    "LIBRARY-SCREENING-001": (
        (LIBRARY, "def screening_basis"),
        (LIBRARY, "is not named in the authorized source policy"),
        (LIBRARY, "STUDY_ELIGIBLE_SUFFIXES"),
        (ACQUIRE, "def source_policy"),
        (ACQUIRE, "APPROVAL_BASIS"),
    ),
    "LIBRARY-CONTENT-REVIEW-001": (
        (LIBRARY, "class ContentReview"),
        (LIBRARY, "def record_content_review"),
        (LIBRARY, "def human_content_reviewed"),
        (LIBRARY, "Never derived from SourceStatus"),
        (ACQUIRE, "content-review"),
    ),
    "LIBRARY-MIGRATION-001": (
        (LIBRARY, "_RENAMED_COLUMNS"),
        (LIBRARY, "RENAME COLUMN"),
        (LIBRARY, "def _migrate"),
    ),
    "LIBRARY-CONTAINMENT-001": (
        (LIBRARY, "def acceptable_path"),
        (LIBRARY, "EXCLUDED_SUFFIXES"),
        (LIBRARY, "EXCLUDED_NAMES"),
    ),
    "LIBRARY-SECRETS-001": (
        (LIBRARY, "CREDENTIAL_PATTERNS"),
        (LIBRARY, "def carries_credentials"),
        (LIBRARY, "appears to carry a credential"),
    ),
    "LIBRARY-PROVENANCE-001": (
        (LIBRARY, "canonical_url"),
        (LIBRARY, "authority_class"),
        (LIBRARY, "upstream_version"),
        (LIBRARY, "content_digest"),
        (LIBRARY, "def manifest"),
    ),
    "LIBRARY-AUTHORITY-001": (
        (LIBRARY, "class AuthorityClass"),
        (LIBRARY, "source_scope"),
        (ACQUIRE, "authoritative only within source_scope"),
        (ACQUIRE, "it is not an instruction to BRO"),
    ),
    "LIBRARY-NETWORK-001": (
        (ACQUIRE, "urllib.request"),
        (ACQUIRE, "ALLOWED_SCHEMES"),
        (LIBRARY, "Fetches nothing"),
    ),
    "LIBRARY-LANGUAGE-001": (
        (LIBRARY, "class LanguageVariant"),
        (LIBRARY, "but the acquired text reads as"),
        (LIBRARY, "is_eastern_normative"),
    ),
    "LEARN-LANGUAGE-001": (
        (MEMORY, "def detect_language"),
        (MEMORY, "source_language TEXT NOT NULL"),
        (MEMORY, "def evidence_language"),
        (STUDY, "source_language=detect_language"),
    ),
    "LEARN-EVIDENCE-001": (
        (MEMORY, "verified study knowledge requires a source-backed evidence quote"),
        (STUDY, "def quote_is_in_source"),
        (STUDY, "never present a translation as the evidence"),
    ),
    "LEARN-RECALL-001": (
        (MEMORY, "recall_terms_json"),
        (MEMORY, "if term not in haystack and term in keys"),
        (STUDY, "def _recall_terms"),
    ),
    "LEARN-KEYS-001": (
        (MEMORY, "def _recall_terms"),
        (MEMORY, "never long enough to be a quote"),
        (STUDY, "they never become the evidence quote"),
    ),
    "LEARN-PERSIST-001": (
        (MEMORY, "_KNOWLEDGE_COLUMNS"),
        (MEMORY, "def _column"),
    ),
    "STUDY-LIMITS-001": (
        (SURFACE, "def study_item_budget"),
        (SURFACE, "def study_diminishing_after"),
        (SURFACE, "diminishing_after=study_diminishing_after()"),
        (STUDY, "diminishing_after must be at least 1"),
    ),
}

# The library records and reasons. Anything that could reach out or act belongs elsewhere.
FORBIDDEN_IN_LIBRARY = ("urlopen", "urllib", "subprocess", "socket", "requests.")
# The study runtime may not acquire, and may not be handed the acquisition tool.
FORBIDDEN_IN_STUDY = ("bro_acquire_knowledge", "urlopen", "urllib")

REQUIRED_SHELVES = (
    "mcp-protocol", "claude-code", "github-platform", "nist-ai-rmf",
    "owasp-genai", "ietf-rfc", "armenian-language",
)
SHELF_FIELDS = ("shelf", "title", "publisher", "authority_class", "source_scope",
                "upstream_version", "source_language", "language_variant", "documents")


def _read(root: Path, path: str) -> str | None:
    target = root / path
    return target.read_text(encoding="utf-8") if target.is_file() else None


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    contract_path = root / CONTRACT
    if not contract_path.is_file():
        return [f"missing contract: {CONTRACT}"]
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    sources = {path: _read(root, path) for path in
               (LIBRARY, MEMORY, STUDY, ACQUIRE, SURFACE)}
    for path, text in sources.items():
        if text is None:
            errors.append(f"missing source: {path}")

    declared = [item["id"] for item in contract.get("invariants", [])]
    if len(declared) != len(set(declared)):
        errors.append("invariant identifiers must be unique")
    for identifier in declared:
        markers = INVARIANT_MARKERS.get(identifier)
        if markers is None:
            errors.append(f"{identifier}: declared in the contract but enforced by nothing")
            continue
        for path, marker in markers:
            text = sources.get(path)
            if text is not None and marker not in text:
                errors.append(f"{identifier}: {path} no longer contains {marker!r}")
    for identifier in INVARIANT_MARKERS:
        if identifier not in declared:
            errors.append(f"{identifier}: enforced in code but absent from the contract")

    for item in contract.get("invariants", []):
        for relative in item.get("tests", ()):
            if not (root / relative).is_file():
                errors.append(f"{item['id']}: names a test file that does not exist: {relative}")

    library = sources.get(LIBRARY)
    if library is not None:
        for token in FORBIDDEN_IN_LIBRARY:
            if token in library:
                errors.append(f"{LIBRARY}: the library must not reach the network ({token!r})")
    study = sources.get(STUDY)
    if study is not None:
        for token in FORBIDDEN_IN_STUDY:
            if token in study:
                errors.append(f"{STUDY}: study must not acquire anything ({token!r})")

    errors.extend(_validate_shelves(root))
    return errors


def _validate_shelves(root: Path = ROOT) -> list[str]:
    """A shelf with no publisher or no scope is a document with no authority."""
    errors: list[str] = []
    path = root / SHELVES
    if not path.is_file():
        return [f"missing shelf manifest: {SHELVES}"]
    manifest = json.loads(path.read_text(encoding="utf-8"))
    shelves = manifest.get("shelves")
    if not isinstance(shelves, list):
        return [f"{SHELVES}: shelves must be a list"]
    contract = json.loads((root / CONTRACT).read_text(encoding="utf-8"))
    classes = set(contract["authority_classes"])
    languages = set(contract["supported_source_languages"])
    variants = set(contract["armenian_variants"]) | {"NOT_APPLICABLE"}

    present = {shelf.get("shelf") for shelf in shelves}
    for required in REQUIRED_SHELVES:
        if required not in present:
            errors.append(f"{SHELVES}: shelf {required!r} is missing")
    slugs: set[str] = set()
    for shelf in shelves:
        name = shelf.get("shelf", "<unnamed>")
        for field in SHELF_FIELDS:
            if not shelf.get(field):
                errors.append(f"{SHELVES}: shelf {name!r} is missing {field}")
        if shelf.get("authority_class") not in classes:
            errors.append(f"{SHELVES}: shelf {name!r} declares an unknown authority class")
        if shelf.get("source_language") not in languages:
            errors.append(f"{SHELVES}: shelf {name!r} declares an unsupported source language")
        if shelf.get("language_variant") not in variants:
            errors.append(f"{SHELVES}: shelf {name!r} declares an unknown language variant")
        for document in shelf.get("documents", ()):
            slug = f"{name}/{document.get('slug', '')}"
            if not document.get("slug") or not document.get("title"):
                errors.append(f"{SHELVES}: a document in {name!r} has no slug or title")
            if slug in slugs:
                errors.append(f"{SHELVES}: duplicate document {slug!r}")
            slugs.add(slug)
            url = document.get("url", "")
            if urlparse(url).scheme != "https":
                errors.append(f"{SHELVES}: {slug} is not an https source")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    contract = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / SHELVES).read_text(encoding="utf-8"))
    documents = sum(len(shelf["documents"]) for shelf in manifest["shelves"])
    print(f"PASS: {len(contract['invariants'])} knowledge-library invariants are contract-bound; "
          f"{len(manifest['shelves'])} shelves / {documents} attributed https sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
