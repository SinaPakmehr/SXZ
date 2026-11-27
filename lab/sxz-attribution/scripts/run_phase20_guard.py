#!/usr/bin/env python3
"""Cumulative 180-second subprocess guard for Phase 20 Episode 1."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab/sxz-attribution/results"
LEDGER = RESULTS / "phase20-runtime.json"
WORKER = Path(__file__).with_name("run_phase20.py")
LIMIT_S = 180.0


def read_ledger() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf8"))
    return {"total_s": 0.0, "runs": []}


def write_ledger(ledger: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(ledger, indent=1) + "\n", encoding="utf8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args()
    ledger = read_ledger()
    used = float(ledger.get("total_s", 0.0))
    remaining = LIMIT_S - used
    if remaining <= 1.0:
        print(f"cumulative budget exhausted: used={used:.3f}s")
        return 3
    worker = WORKER.with_name("audit_phase20_systematic.py") if args.audit else WORKER
    command = [sys.executable, "-B", str(worker)]
    started = time.perf_counter()
    status = "ok"
    try:
        completed = subprocess.run(command, timeout=remaining, check=False)
        return_code = completed.returncode
        if return_code != 0:
            status = f"worker_exit_{return_code}"
    except subprocess.TimeoutExpired:
        return_code = 124
        status = "timeout"
    elapsed = time.perf_counter() - started
    ledger["total_s"] = round(used + elapsed, 3)
    ledger.setdefault("runs", []).append(
        {
            "split": "systematic_audit" if args.audit else "audit",
            "elapsed_s": round(elapsed, 3),
            "status": status,
            "cumulative_s": ledger["total_s"],
            "remaining_s": round(LIMIT_S - ledger["total_s"], 3),
        }
    )
    write_ledger(ledger)
    print(f"guard: status={status} elapsed={elapsed:.3f}s cumulative={ledger['total_s']:.3f}s")
    return return_code


if __name__ == "__main__":
    sys.exit(main())
