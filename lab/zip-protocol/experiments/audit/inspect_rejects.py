"""Explain why formulas that were accepted per segment never reached the archive."""

from __future__ import annotations

import argparse
import json
import zlib
from collections import Counter
from pathlib import Path

from sinuxz.container import CODEC_FORMULA, HEADER, Packer, unpack


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--size", type=int, default=1 << 20)
    parser.add_argument("--budget", type=int, default=None)
    parser.add_argument("--minimum", type=int, default=16)
    parser.add_argument("--window", type=int, default=128)
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    with args.path.open("rb") as handle:
        handle.seek(args.offset)
        data = handle.read(args.size)
    packer = Packer(max_window=args.window, min_formula_bytes=args.minimum, extend_bytes=65536,
                    level=6, experimental_models=True, scan_budget=args.budget)
    packer.trace = []
    blob = packer.pack(data)
    assert unpack(blob) == data
    accepted = [e for e in packer.trace if e["accepted"]]
    emitted = [s for s in packer.segments if s.codec == CODEC_FORMULA]
    baseline = HEADER.size + len(zlib.compress(data, 6))
    summary = {
        "path": str(args.path), "size": len(data), "budget": args.budget,
        "archive_bytes": len(blob), "deflate_baseline": baseline,
        "accepted_segments": len(accepted),
        "accepted_bytes": sum(e["span"] for e in accepted),
        "accepted_cost_bytes": sum((e["cost_bits"] + 7) // 8 for e in accepted),
        "emitted_formula_segments": len(emitted),
        "emitted_formula_bytes": sum(s.size for s in emitted),
        "models": dict(Counter(e["model"] for e in accepted)),
        "transforms": dict(Counter(e["transform"] for e in accepted)),
        "median_cover": sorted(e["span"] for e in accepted)[len(accepted) // 2] if accepted else 0,
        "max_cover": max((e["span"] for e in accepted), default=0),
        "examples": sorted(
            ({"pos": e["pos"], "model": e["model"], "transform": e["transform"],
              "cover": e["span"], "cost": (e["cost_bits"] + 7) // 8,
              "fallback": e["fallback_bytes"]} for e in accepted),
            key=lambda item: -item["cover"])[:12],
        "reasons": dict(Counter(e["reason"] for e in packer.trace)),
        "candidate_archives": packer.choices,
        "structured_vs_plain": next(
            (size - baseline for size, detail in (packer.choices or [])
             if detail != "deflate-whole"), None),
    }
    print(json.dumps(summary, indent=2))
    if args.save:
        args.save.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
