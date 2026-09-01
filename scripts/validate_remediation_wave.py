#!/usr/bin/env python3
"""Fail closed when protected architecture changes are delivered as undeclared micro-fixes."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "contracts" / "remediation_policy.json"


def _fields(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in (body or "").splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key:
            result[key] = value
    return result


def validate_declaration(body: str, changed_files: list[str], policy: dict) -> list[str]:
    protected_prefixes = tuple(policy["protected_prefixes"])
    protected = [path for path in changed_files if path.startswith(protected_prefixes)]
    if not protected:
        return []

    fields = _fields(body)
    errors: list[str] = []
    wave = policy["wave"]
    for field in wave["required_fields"]:
        if not fields.get(field):
            errors.append(f"protected architecture change requires PR field: {field}")

    wave_class = fields.get("Wave-Class", "").upper()
    if wave_class and wave_class not in policy["allowed_wave_classes"]:
        errors.append(f"unsupported Wave-Class: {wave_class}")
        return errors

    if wave_class == "EMERGENCY":
        emergency_field = policy["emergency_required_field"]
        if not fields.get(emergency_field):
            errors.append(f"EMERGENCY wave requires PR field: {emergency_field}")
        return errors

    if wave_class == "SUBSYSTEM":
        if len(protected) < int(wave["minimum_protected_files"]):
            errors.append(
                f"SUBSYSTEM wave requires at least {wave['minimum_protected_files']} protected files; found {len(protected)}"
            )
        areas = [item.strip() for item in fields.get("Scope", "").split(",") if item.strip()]
        if len(set(areas)) < int(wave["minimum_scope_areas"]):
            errors.append(
                f"SUBSYSTEM wave requires at least {wave['minimum_scope_areas']} distinct Scope areas"
            )
    return errors


def _github_changed_files(event: dict) -> list[str]:
    pr = event.get("pull_request") or {}
    url = pr.get("url")
    if not url:
        return []
    token = os.environ.get("GITHUB_TOKEN", "")
    request = urllib.request.Request(
        f"{url}/files?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    return [item["filename"] for item in payload]


def validate_event(event: dict, changed_files: list[str] | None = None) -> list[str]:
    if event.get("pull_request") is None:
        return []
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    files = _github_changed_files(event) if changed_files is None else changed_files
    body = (event.get("pull_request") or {}).get("body") or ""
    return validate_declaration(body, files, policy)


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("PASS: remediation wave gate not running inside a GitHub event")
        return 0
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    errors = validate_event(event)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("PASS: remediation wave declaration satisfies protected architecture policy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
