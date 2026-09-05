#!/usr/bin/env python3
"""Fail closed if the governed study-acquisition boundary drifts from its contract.

Two separations are the whole design, and both are checkable from source. External
retrieval lives in exactly one module: the study runtime must import no network client and
must reach the outside only through an injected callable. And retrieval is read-only: the
acquisition module must express no verb but GET, and must never carry a request body.

The rest is invariant-to-marker mapping, plus a policy sanity pass -- a tier nobody defined,
a family with no hosts, or an entry point on a host the policy does not claim would each
make the allowlist stop being one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/study_acquisition.json"
POLICY = "contracts/source_policy.json"
ACQUISITION = "src/bro_runtime/study_acquisition.py"
POLICY_RUNTIME = "src/bro_runtime/source_policy.py"
STUDY = "src/bro_runtime/study_runtime.py"
LIBRARY = "src/bro_runtime/knowledge_library.py"
SURFACE = "scripts/bro_interact.py"

INVARIANT_MARKERS: dict[str, tuple[tuple[str, str], ...]] = {
    "ACQ-ONE-BOUNDARY-001": (
        (ACQUISITION, "class BoundedFetcher"),
        (STUDY, "acquirer: Callable"),
        (STUDY, "self.acquirer = acquirer"),
        (SURFACE, "def build_acquirer"),
    ),
    "ACQ-READ-ONLY-001": (
        (ACQUISITION, 'method="GET"'),
        (ACQUISITION, "Only GET is expressible"),
    ),
    "ACQ-SSRF-001": (
        (ACQUISITION, "def resolve_public_addresses"),
        (ACQUISITION, "is_private or address.is_loopback"),
        (ACQUISITION, "non-public address"),
    ),
    "ACQ-SCHEME-001": (
        (ACQUISITION, "def require_safe_url"),
        (ACQUISITION, "refusing a url that carries credentials"),
        (ACQUISITION, "ALLOWED_SCHEMES"),
    ),
    "ACQ-BUDGET-001": (
        (ACQUISITION, "max_response_bytes"),
        (ACQUISITION, "CHUNK_BYTES"),
        (ACQUISITION, "def _pace"),
    ),
    "ACQ-REDIRECT-001": (
        (ACQUISITION, "class _NoRedirect"),
        (ACQUISITION, "redirected more than"),
    ),
    "ACQ-NORMALISE-001": (
        (ACQUISITION, "class _HtmlToText"),
        (ACQUISITION, "DROPPED_ELEMENTS"),
        (ACQUISITION, "def normalise"),
    ),
    "ACQ-PDF-001": (
        (ACQUISITION, "def extract_pdf_text"),
        (ACQUISITION, "def _reads_as_prose"),
        (ACQUISITION, "no readable text layer"),
    ),
    "ACQ-FRONTIER-001": (
        (ACQUISITION, "class LinkFrontier"),
        (ACQUISITION, "def next_links"),
        (POLICY_RUNTIME, "def canonical_url"),
    ),
    "ACQ-TIER-001": (
        (POLICY_RUNTIME, "class AuthorityTier"),
        (POLICY_RUNTIME, "def _matches"),
        (POLICY_RUNTIME, "may_produce_verified_knowledge"),
    ),
    "ACQ-ADMISSION-001": (
        (ACQUISITION, "if not candidate.admissible"),
        (ACQUISITION, "def _screening_policy"),
        (LIBRARY, "DISCOVERED"),
    ),
    "ACQ-PROVENANCE-001": (
        (ACQUISITION, "def _artifact_body"),
        (LIBRARY, "requested_url"),
        (LIBRARY, "artifact_digest"),
    ),
    "ACQ-STALENESS-001": (
        (ACQUISITION, "existing.artifact_digest == artifact.artifact_digest"),
        (LIBRARY, "bro_knowledge_source_live_path"),
    ),
    "ACQ-INJECTION-001": (
        (ACQUISITION, "INJECTION_MARKERS"),
        (ACQUISITION, "def injection_markers"),
        (ACQUISITION, "not instructions to BRO"),
    ),
    "ACQ-AUTONOMY-001": (
        (STUDY, "def _acquire"),
        (STUDY, "acquisition failed"),
        (STUDY, "def _uncertain_topics"),
    ),
    "ACQ-SWITCH-001": (
        (SURFACE, "def acquisition_enabled"),
        (SURFACE, "BRO_STUDY_ACQUISITION"),
    ),
}

# The study runtime reads; it does not reach. A network name here would mean the separation
# had become a convention instead of a boundary.
FORBIDDEN_IN_STUDY = ("urlopen", "urllib", "socket", "http.client", "requests.",
                      "study_acquisition", "BoundedFetcher")
# Anything that would make acquisition a writer rather than a reader.
FORBIDDEN_IN_ACQUISITION = ('method="POST"', 'method="PUT"', 'method="DELETE"',
                            'method="PATCH"', "data=payload", "os.system", "eval(", "exec(")


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
               (ACQUISITION, POLICY_RUNTIME, STUDY, LIBRARY, SURFACE)}
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

    study = sources.get(STUDY)
    if study is not None:
        for token in FORBIDDEN_IN_STUDY:
            if token in study:
                errors.append(f"{STUDY}: study reading must not reach the network ({token!r})")
    acquisition = sources.get(ACQUISITION)
    if acquisition is not None:
        for token in FORBIDDEN_IN_ACQUISITION:
            if token in acquisition:
                errors.append(f"{ACQUISITION}: acquisition must stay read-only ({token!r})")
        if acquisition.count('method="GET"') != 1:
            errors.append(f"{ACQUISITION}: exactly one request verb may be expressed, and it is GET")

    errors.extend(_validate_policy(root))
    return errors


def _validate_policy(root: Path = ROOT) -> list[str]:
    """An allowlist with a hole in it is not an allowlist."""
    errors: list[str] = []
    path = root / POLICY
    if not path.is_file():
        return [f"missing source policy: {POLICY}"]
    policy = json.loads(path.read_text(encoding="utf-8"))
    tiers = policy.get("tiers", {})
    if not tiers:
        return [f"{POLICY}: a source policy must declare its tiers"]
    for name, rule in tiers.items():
        for field in ("name", "statement", "auto_admit", "may_produce_verified_knowledge"):
            if field not in rule:
                errors.append(f"{POLICY}: tier {name} does not declare {field}")
    if tiers.get("D", {}).get("may_produce_verified_knowledge"):
        errors.append(f"{POLICY}: tier D must never produce verified knowledge")
    if tiers.get("UNCLASSIFIED", {}).get("auto_admit"):
        errors.append(f"{POLICY}: an unclassified host must never be admitted automatically")

    claimed: set[str] = set()
    for family in policy.get("families", ()):
        name = family.get("family", "<unnamed>")
        for field in ("family", "tier", "publisher", "scope", "hosts", "authority_class"):
            if not family.get(field):
                errors.append(f"{POLICY}: family {name!r} is missing {field}")
        if family.get("tier") not in tiers:
            errors.append(f"{POLICY}: family {name!r} declares an unknown tier")
        for host in family.get("hosts", ()):
            if host in claimed:
                errors.append(f"{POLICY}: host {host!r} is claimed by more than one family")
            claimed.add(host)
        for entry in family.get("entry_points", ()):
            parts = urlsplit(entry)
            if parts.scheme != "https":
                errors.append(f"{POLICY}: entry point {entry!r} is not https")
            host = (parts.hostname or "").lower()
            if not any(host == claimed_host or host.endswith("." + claimed_host)
                       for claimed_host in family.get("hosts", ())):
                errors.append(
                    f"{POLICY}: entry point {entry!r} is on a host the {name!r} family does not claim")
    for denied in policy.get("denied_hosts", ()):
        if denied in claimed:
            errors.append(f"{POLICY}: {denied!r} is both denied and claimed by a family")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    contract = json.loads((ROOT / CONTRACT).read_text(encoding="utf-8"))
    policy = json.loads((ROOT / POLICY).read_text(encoding="utf-8"))
    hosts = sum(len(family["hosts"]) for family in policy["families"])
    print(f"PASS: {len(contract['invariants'])} study-acquisition invariants are contract-bound; "
          f"{len(policy['families'])} source families / {hosts} allowlisted hosts, read-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
