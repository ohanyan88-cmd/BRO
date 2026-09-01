#!/usr/bin/env python3
"""Run the long-lived BRO production host under an external service manager."""
from __future__ import annotations

import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bro_runtime.production_host import ProductionHost, ProductionHostConfig, ProductionHostRejected


def main() -> int:
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        config = ProductionHostConfig.from_env()
        host = ProductionHost(config)
        host.run(should_stop=lambda: stopping)
    except ProductionHostRejected as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
