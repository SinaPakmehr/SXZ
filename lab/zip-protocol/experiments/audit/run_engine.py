"""Measure the formula engine itself on planted patterns (no framing involved)."""

from __future__ import annotations

import argparse
import json
import zlib
from dataclasses import asdict
from pathlib import Path

import sinuxz.container as container
from sinuxz.container import CODEC_FORMULA, HEADER, Packer
from sinuxz.transforms import TRANSFORMS
from experiments.audit import planted


CONFIGS = [
    # name, budget, window, experimental, transform names (None = all)
    ("base-bank", None, 128, False, None),
    ("experimental", None, 128, True, None),
    ("budget-8", 8, 128, True, None),
    ("budget-32", 32, 128, True, None),
    ("budget-128", 128, 128, True, None),
    ("window-512", None, 512, True, None),
    ("identity-only", None, 128, True, ["identity"]),
]


def overlap(a_start: int, a_len: int, b_start: int, b_len: int) -> int:
    return max(0, min(a_start + a_len, b_start + b_len) - max(a_start, b_start))


def run_case(case: planted.Case, name: str, budget, window: int, experimental: bool,
             transforms: list[str] | None) -> dict:
    saved = container.TRANSFORMS
    if transforms is not None:
        container.TRANSFORMS = [t for t in saved if t.name in transforms]
    try:
        packer = Packer(max_window=window, min_formula_bytes=16, extend_bytes=65536,
                        level=6, experimental_models=experimental, scan_budget=budget)
        packer.trace = []
        blob = packer.pack(case.data)
        assert container.unpack(blob) == case.data
    finally:
        container.TRANSFORMS = saved

    baseline = HEADER.size + len(zlib.compress(case.data, 6))
    covered = 0
    accepted = 0
    offset = 0
    for seg in packer.segments:
        if seg.codec == CODEC_FORMULA:
            covered += overlap(offset, seg.size, case.start, case.length)
            accepted += 1
        offset += seg.size
    fits = [f for event in packer.trace for f in event.get("fits", [])]
    models = {}
    for fit in fits:
        slot = models.setdefault(fit["model"], {"candidates": 0, "exact": 0, "best_cover": 0})
        slot["candidates"] += 1
        if fit["cover"] >= 16:
            slot["exact"] += 1
        slot["best_cover"] = max(slot["best_cover"], fit["cover"])
    reasons = {}
    for event in packer.trace:
        reasons[event["reason"]] = reasons.get(event["reason"], 0) + 1
    return {
        "config": name, "case": case.name, "family": case.family,
        "planted": case.length, "covered": covered,
        "coverage": covered / case.length if case.length else 0.0,
        "detected": covered >= case.length // 2,
        "probes": packer.probe_count, "accepted_segments": accepted,
        "archive_bytes": len(blob), "deflate_baseline": baseline,
        "net_bytes": len(blob) - baseline,
        "scan_seconds": packer.scan_seconds,
        "models": models, "reasons": reasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=Path("results/audit_engine.json"))
    parser.add_argument("--only", nargs="*", help="case name filters")
    args = parser.parse_args()
    cases = planted.build()
    if args.only:
        cases = [c for c in cases if any(f in c.name for f in args.only)]
    rows = []
    for case in cases:
        for name, budget, window, experimental, transforms in CONFIGS:
            row = run_case(case, name, budget, window, experimental, transforms)
            row["expected"] = case.expected
            row["note"] = case.note
            rows.append(row)
            print(f"{case.name:<32} {name:<14} cover={row['coverage']:6.1%} "
                  f"probes={row['probes']:5d} net={row['net_bytes']:+7d} "
                  f"accept={row['accepted_segments']:3d} {row['scan_seconds']:.2f}s", flush=True)
        args.save.write_text(json.dumps(rows, indent=2, default=str) + "\n", encoding="utf-8")
    print("saved", args.save)


if __name__ == "__main__":
    main()
