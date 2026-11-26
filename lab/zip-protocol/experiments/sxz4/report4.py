"""Aggregate SXZ4 results by category so synthetic wins cannot hide real losses."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REFS = ["deflate-6", "zstd-19", "xz-6"]
MAIN = ["sxz2", "sxz2-scan", "sxz3-B", "sxz4-off", "sxz4-tx", "sxz4-on", "sxz4-prog"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=Path("results/sxz4_bench.json"))
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_bench.md"))
    args = parser.parse_args()
    rows = json.loads(args.json.read_text(encoding="utf-8"))
    by = {(r["name"], r["method"]): r for r in rows}
    names = list(dict.fromkeys(r["name"] for r in rows))
    hero = {r["name"]: r for r in rows}

    lines = ["# SXZ4 benchmark", "",
             "Every output is decoded and compared byte for byte. Sizes include all headers.",
             "SXZ variants share the Deflate-6 backend; zstd/xz are external references.",
             "Categories are reported separately on purpose.", ""]

    for category in ("synthetic", "real", "precompressed"):
        subset = [n for n in names if hero[n]["category"] == category]
        if not subset:
            continue
        lines += [f"## {category} ({len(subset)} files)", "",
                  "| Method | Total B | Ratio | Encode s | Decode s |", "|---|---:|---:|---:|---:|"]
        for method in REFS + MAIN + ["gorilla", "fpc", "delta-deflate"]:
            part = [by[(n, method)] for n in subset if (n, method) in by]
            if not part:
                continue
            total = sum(r["bytes"] for r in part)
            raw = sum(r["bytes_in"] for r in part)
            lines.append(f"| `{method}` | {total:,} | {total/raw:.2%} | "
                         f"{sum(r['encode'] for r in part):.1f} | {sum(r['decode'] for r in part):.1f} |")
        lines.append("")

    lines += ["## Per-file (SXZ4-on vs best reference)", "",
              "| File | Cat | Raw | SXZ4-on | Best ref | Gap | Spans | Modelled | Models |",
              "|---|---|---:|---:|---|---:|---:|---:|---|"]
    for name in names:
        row = by.get((name, "sxz4-on"))
        if not row:
            continue
        refs = {m: by[(name, m)]["bytes"] for m in REFS if (name, m) in by}
        best = min(refs, key=refs.get) if refs else None
        gap = f"{row['bytes']/refs[best]-1:+.1%}" if best else "—"
        models = ", ".join(f"{k}×{v}" for k, v in row.get("models", {}).items()) or "—"
        lines.append(f"| {name} | {row['category'][:3]} | {row['bytes_in']:,} | {row['bytes']:,} | "
                     f"{best}: {refs[best]:,} | {gap} | {row.get('spans', 0)} | "
                     f"{row.get('modelled', 0)/max(1,row['bytes_in']):.0%} | {models} |")
    lines.append("")

    lines += ["## Held-out", "", "| File | Cat | zstd-19 | xz-6 | SXZ4-on |", "|---|---|---:|---:|---:|"]
    for name in names:
        if not hero[name]["heldout"]:
            continue
        cells = [by.get((name, m), {}).get("bytes") for m in ("zstd-19", "xz-6", "sxz4-on")]
        lines.append(f"| {name} | {hero[name]['category'][:3]} | " +
                     " | ".join(f"{c:,}" if c else "—" for c in cells) + " |")
    lines.append("")

    lines += ["## Transform chains chosen", "", "| File | SXZ4-on chain | SXZ4-tx chain |", "|---|---|---|"]
    for name in names:
        on = by.get((name, "sxz4-on"));
        tx = by.get((name, "sxz4-tx"))
        if not on:
            continue
        lines.append(f"| {name} | {on.get('chain')} | {tx.get('chain') if tx else '—'} |")

    args.save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.save} ({len(rows)} rows, {len(names)} files)")


if __name__ == "__main__":
    main()
