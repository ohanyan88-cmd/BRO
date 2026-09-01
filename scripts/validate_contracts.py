#!/usr/bin/env python3
"""Fail-closed structural validation for BRO's canonical contract registry."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts" / "registry.json"
REQUIRED_SCHEMA_KEYS = {"$schema", "$id", "title", "x-bro-primitive", "x-bro-owner", "type", "required", "properties"}


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be an object")
    return value


def validate(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    registry_path = root / "contracts" / "registry.json"
    try:
        registry = load_json(registry_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [str(exc)]

    allowed = registry.get("allowed_owners")
    contracts = registry.get("contracts")
    if not isinstance(allowed, list) or not allowed or len(allowed) != len(set(allowed)):
        errors.append("registry.allowed_owners must be a non-empty unique list")
        allowed = []
    if not isinstance(contracts, list) or not contracts:
        return errors + ["registry.contracts must be a non-empty list"]

    primitives: set[str] = set()
    paths: set[str] = set()
    for index, entry in enumerate(contracts):
        label = f"registry.contracts[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object")
            continue
        primitive, owner, relative = entry.get("primitive"), entry.get("owner"), entry.get("schema")
        if not all(isinstance(value, str) and value for value in (primitive, owner, relative)):
            errors.append(f"{label} requires primitive, owner, and schema")
            continue
        if primitive in primitives:
            errors.append(f"duplicate primitive registration: {primitive}")
        primitives.add(primitive)
        if relative in paths:
            errors.append(f"duplicate schema registration: {relative}")
        paths.add(relative)
        if owner not in allowed:
            errors.append(f"{primitive}: owner {owner} is not constitutionally allowed")
        schema_path = (root / relative).resolve()
        if root.resolve() not in schema_path.parents:
            errors.append(f"{primitive}: schema escapes repository root")
            continue
        try:
            schema = load_json(schema_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))
            continue
        missing = REQUIRED_SCHEMA_KEYS - schema.keys()
        if missing:
            errors.append(f"{primitive}: schema missing keys {sorted(missing)}")
        if schema.get("x-bro-primitive") != primitive:
            errors.append(f"{primitive}: schema primitive identity mismatch")
        if schema.get("x-bro-owner") != owner:
            errors.append(f"{primitive}: schema owner mismatch")
        if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
            errors.append(f"{primitive}: canonical record must be a closed object")
        required, properties = schema.get("required"), schema.get("properties")
        if not isinstance(required, list) or not required or len(required) != len(set(required)):
            errors.append(f"{primitive}: required must be a non-empty unique list")
        if not isinstance(properties, dict):
            errors.append(f"{primitive}: properties must be an object")
        elif isinstance(required, list):
            absent = set(required) - properties.keys()
            if absent:
                errors.append(f"{primitive}: required fields missing definitions {sorted(absent)}")
        schema_id = schema.get("$id")
        if not isinstance(schema_id, str) or urlparse(schema_id).scheme != "https":
            errors.append(f"{primitive}: $id must be an HTTPS URI")

    for baseline in registry.get("architecture_baseline", []):
        if not (root / baseline).is_file():
            errors.append(f"missing architecture baseline: {baseline}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    registry = load_json(REGISTRY)
    print(f"PASS: {len(registry['contracts'])} canonical contracts and ownership gates validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

