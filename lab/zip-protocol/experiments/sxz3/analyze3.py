"""Compact aggregates from sxz3_bench.json for the research write-up."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REFS = ["deflate-6", "deflate-9", "zstd-3", "zstd-19", "xz-6"]
MAIN = ["sxz2", "sxz2-scan", "sxz2+models", "sxz3-A", "sxz3-B", "sxz3-C"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=Path("results/sxz3_bench.json"))
    args = parser.parse_args()
    rows = json.loads(args.json.read_text(encoding="utf-8"))
    by = {(r["name"], r["method"]): r for r in rows}
    names = list(dict.fromkeys(r["name"] for r in rows))
    info = {r["name"]: r for r in rows}

    print("== totals")
    for method in REFS + MAIN + ["sxz3-B-basic", "sxz3-B-exact", "sxz3-B-adaptive", "sxz3-B-nocompose"]:
        subset = [r for r in rows if r["method"] == method]
        if not subset:
            continue
        total = sum(r["bytes"] for r in subset)
        raw = sum(r["bytes_in"] for r in subset)
        print(f"{method:<20} {total:>12,} {total/raw:7.2%} enc={sum(r['encode'] for r in subset):7.1f}s")

    print("\n== wins over best reference (>1%)")
    for name in names:
        refs = {m: by[(name, m)]["bytes"] for m in REFS if (name, m) in by}
        sxz3 = by.get((name, "sxz3-B"))
        if not refs or not sxz3:
            continue
        best = min(refs, key=refs.get)
        saving = 1 - sxz3["bytes"] / refs[best]
        if saving > 0.01:
            print(f"{name:<28} {sxz3['bytes']:>10,} vs {best:<10} {refs[best]:>10,} {saving:7.1%}")

    print("\n== noised numeric")
    for name in names:
        if "noise" not in name:
            continue
        row = by.get((name, "sxz3-B"))
        ref = min(by[(name, m)]["bytes"] for m in REFS if (name, m) in by)
        print(f"{name:<28} sxz3-B={row['bytes']:>9,} best-ref={ref:>9,} "
              f"{1 - row['bytes']/ref:7.1%} modelled={row.get('modelled')} "
              f"modes={row.get('residual_modes')}")

    print("\n== held out")
    for name in names:
        if not info[name]["heldout"]:
            continue
        cells = []
        for method in ("zstd-19", "xz-6", "sxz3-B"):
            row = by.get((name, method))
            cells.append(f"{method}={row['bytes']:,}" if row else "")
        print(f"{name:<28} " + "  ".join(cells))

    print("\n== ablation (B)")
    for name in names:
        line = [f"{name:<26}"]
        for method in ("sxz3-B", "sxz3-B-basic", "sxz3-B-exact", "sxz3-B-adaptive", "sxz3-B-nocompose"):
            row = by.get((name, method))
            line.append(f"{row['bytes']:>9,}" if row else "        —")
        print(" ".join(line))

    print("\n== selected models on structured items")
    for name in names:
        row = by.get((name, "sxz3-B"))
        if not row or not row.get("modelled"):
            continue
        if row["family"] in ("affine", "prng", "recurrence", "multichannel", "period", "reference",
                             "quadratic", "noise", "composite"):
            print(f"{name:<28} {row['modelled']}/{row['blocks']} {row['models']} {row['residual_modes']}")


if __name__ == "__main__":
    main()
