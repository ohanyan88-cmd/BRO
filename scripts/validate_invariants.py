#!/usr/bin/env python3
"""Fail closed when a declared BRO invariant loses executable enforcement."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "contracts" / "invariants.json"

def validate(root: Path = ROOT) -> list[str]:
    path = root / "contracts" / "invariants.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [str(exc)]
    invariants = data.get("invariants")
    if not isinstance(invariants, list) or not invariants:
        return ["invariants registry must contain a non-empty invariants list"]
    errors=[]; ids=set()
    for item in invariants:
        if not isinstance(item, dict):
            errors.append("invariant entry must be an object"); continue
        iid=item.get("id"); statement=item.get("statement"); enforcement=item.get("enforcement")
        if not isinstance(iid,str) or not iid:
            errors.append("invariant requires id"); continue
        if iid in ids: errors.append(f"duplicate invariant id: {iid}")
        ids.add(iid)
        if not isinstance(statement,str) or not statement.strip(): errors.append(f"{iid}: statement required")
        if not isinstance(enforcement,list) or not enforcement:
            errors.append(f"{iid}: executable enforcement required"); continue
        for relative in enforcement:
            if not isinstance(relative,str) or not relative.startswith("tests/") or not relative.endswith(".py"):
                errors.append(f"{iid}: enforcement must reference test files: {relative!r}"); continue
            target=(root/relative).resolve()
            if root.resolve() not in target.parents or not target.is_file():
                errors.append(f"{iid}: missing enforcement file: {relative}")
    return errors

def main() -> int:
    errors=validate()
    if errors:
        for error in errors: print(f"ERROR: {error}")
        return 1
    count=len(json.loads(REGISTRY.read_text(encoding="utf-8"))["invariants"])
    print(f"PASS: {count} recurring invariants have executable test enforcement")
    return 0

if __name__ == "__main__": raise SystemExit(main())
