#!/usr/bin/env python3
"""Fail closed if Debian production deployment controls drift."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
contract = json.loads((ROOT / "contracts/production_deployment.json").read_text(encoding="utf-8"))
unit = (ROOT / "deploy/systemd/bro.service").read_text(encoding="utf-8")
installer = (ROOT / "scripts/install_debian_production.sh").read_text(encoding="utf-8")
host = (ROOT / "src/bro_runtime/production_host.py").read_text(encoding="utf-8")

required_contract = ("HOST_DEPLOYED", "PRODUCTION_ACCEPTED", "PRODUCTION_GRADUATED")
missing = [name for name in required_contract if name not in contract.get("states", {})]
if missing:
    raise SystemExit(f"ERROR: production deployment contract missing states: {missing}")

for marker in (
    "User=bro",
    "StateDirectory=bro",
    "RuntimeDirectory=bro",
    "ProtectSystem=strict",
    "NoNewPrivileges=true",
    "ExecStartPre=/usr/bin/python3 /opt/bro/current/scripts/production_status.py --preflight",
):
    if marker not in unit:
        raise SystemExit(f"ERROR: systemd hardening/runtime marker missing: {marker}")

for marker in (
    "git fetch --quiet origin main",
    "REMOTE_MAIN=",
    "git archive",
    "BRO_SOURCE_REVISION=$EXPECTED_SHA",
    "systemctl restart bro.service",
):
    if marker not in installer:
        raise SystemExit(f"ERROR: deterministic installer marker missing: {marker}")

for marker in ("journal_mode=WAL", "LOCK_EX | fcntl.LOCK_NB", "host_readback"):
    if marker not in host:
        raise SystemExit(f"ERROR: production host control missing: {marker}")

if "do not by themselves satisfy final production graduation" not in contract.get("purpose", ""):
    raise SystemExit("ERROR: deployment truth-boundary disclaimer is missing")

print("PASS: Debian production deployment is exact-revision, hardened, durable, and truth-boundary controlled")
