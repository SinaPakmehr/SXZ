#!/usr/bin/env python3
"""Cumulative 180-second subprocess guard for Phase 18 Episode 1."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab/sxz-spectral/results"
LEDGER = RESULTS / "phase18-runtime.json"
WORKER = Path(__file__).with_name("run_phase18.py")
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
    parser.add_argument("--split", choices=("dev", "val", "both"), default="both")
    parser.add_argument("--file", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    ledger = read_ledger()
    used = float(ledger.get("total_s", 0.0))
    remaining = LIMIT_S - used
    if remaining <= 1.0:
        print(f"cumulative budget exhausted: used={used:.3f}s limit={LIMIT_S:.0f}s")
        return 3
    command = [sys.executable, "-B", str(WORKER), "--split", args.split]
    if args.file:
        command += ["--file", args.file]
    if args.out:
        command += ["--out", args.out]
    if args.selftest:
        command.append("--selftest")
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
            "split": args.split,
            "elapsed_s": round(elapsed, 3),
            "status": status,
            "cumulative_s": ledger["total_s"],
            "remaining_s": round(LIMIT_S - ledger["total_s"], 3),
        }
    )
    write_ledger(ledger)
    print(
        f"guard: status={status} elapsed={elapsed:.3f}s "
        f"cumulative={ledger['total_s']:.3f}s remaining={LIMIT_S - ledger['total_s']:.3f}s"
    )
    return return_code


if __name__ == "__main__":
    sys.exit(main())
