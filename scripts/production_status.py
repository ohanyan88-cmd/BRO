#!/usr/bin/env python3
"""Read back BRO host health from durable production state."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bro_runtime.production_host import ProductionHostConfig, ProductionHostRejected, read_host_status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true", help="validate production configuration only")
    parser.add_argument("--max-age-seconds", type=float, default=None)
    args = parser.parse_args()
    try:
        config = ProductionHostConfig.from_env()
        if args.preflight:
            print(json.dumps({"ok": True, "environment": config.environment, "source_revision": config.source_revision}, sort_keys=True))
            return 0
        status = read_host_status(config, max_age_seconds=args.max_age_seconds)
    except (ProductionHostRejected, OSError) as exc:
        print(json.dumps({"healthy": False, "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(status, sort_keys=True))
    return 0 if status["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
