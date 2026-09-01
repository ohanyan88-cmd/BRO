#!/usr/bin/env python3
"""Validate the durable sanitized record from governed GitHub write acceptance."""
from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    path = Path(os.environ.get("BRO_GITHUB_ACCEPTANCE_RECORD", "artifacts/github-write-acceptance.json"))
    if not path.is_file():
        raise SystemExit(f"acceptance record is missing: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "task_ref",
        "provider",
        "resource_ref",
        "comment_id",
        "resource_url",
        "observation_ref",
        "initial_effect_state",
        "recovery_action_after_write",
        "completion_verdict",
        "task_state",
        "authenticated_live_write",
        "independent_live_readback",
    }
    missing = sorted(required - set(record))
    if missing:
        raise SystemExit("acceptance record is missing fields: " + ", ".join(missing))
    if record["provider"] != "github":
        raise SystemExit("acceptance provider must be github")
    if record["completion_verdict"] != "VERIFIED" or record["task_state"] != "COMPLETED":
        raise SystemExit("acceptance did not reach VERIFIED / COMPLETED")
    if record["authenticated_live_write"] is not True or record["independent_live_readback"] is not True:
        raise SystemExit("acceptance live-write/readback flags are not both true")
    if not isinstance(record["comment_id"], int) or record["comment_id"] <= 0:
        raise SystemExit("acceptance comment_id must be a positive external identifier")
    if not str(record["observation_ref"]).startswith("github-readback:sha256:"):
        raise SystemExit("acceptance observation_ref is not a registered GitHub readback digest")
    serialized = json.dumps(record, sort_keys=True).lower()
    for forbidden in ("authorization", "bearer ", "github_token", "bro_github_token"):
        if forbidden in serialized:
            raise SystemExit(f"acceptance record contains forbidden credential material: {forbidden}")
    print("PASS: governed authenticated GitHub write acceptance record is complete and sanitized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
