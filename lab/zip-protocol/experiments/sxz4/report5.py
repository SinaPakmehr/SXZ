"""Summarise a benchmark JSON into the tables used by the validation report."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

ORDER = ["deflate-6", "zstd-19", "xz-6", "brotli-11", "sxz2", "sxz3-B",
         "sxz4-off", "sxz4-tx", "sxz4-on", "sxz4-prog"]


def fmt(value: int | float) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return f"{value:,}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, default=Path("results/sxz4_bench_full.json"))
    parser.add_argument("target", type=Path, default=Path("results/sxz4_bench_full.md"))
    args = parser.parse_args()
    rows = json.loads(args.source.read_text(encoding="utf-8"))
    methods = [m for m in ORDER if any(r["method"] == m for r in rows)]
    names = list(dict.fromkeys(r["name"] for r in rows))
    meta = {r["name"]: r for r in rows}
    by = {(r["name"], r["method"]): r for r in rows}

    lines = ["# SXZ4 full corpus (39 items)", "",
             "Every archive is decoded and compared byte for byte. Sizes include all headers.",
             "Encode times are wall-clock seconds on one machine and are indicative only.", ""]

    # Category totals.
    for category in ("synthetic", "real", "precompressed"):
        group = [n for n in names if meta[n]["category"] == category]
        if not group:
            continue
        total_in = sum(meta[n]["bytes_in"] for n in group)
        lines += [f"## {category} ({len(group)} files, {total_in:,} B)", "",
                  "| Method | Total B | Ratio | Encode s | Decode s |", "|---|---:|---:|---:|---:|"]
        for method in methods:
            got = [by[(n, method)] for n in group if (n, method) in by]
            if not got:
                continue
            size = sum(r["bytes"] for r in got)
            lines.append(f"| `{method}` | {size:,} | {size/total_in:.2%} | "
                         f"{sum(r['encode'] for r in got):.1f} | {sum(r['decode'] for r in got):.1f} |")
        lines.append("")

    # Held-out.
    hold = [n for n in names if meta[n]["heldout"]]
    if hold:
        lines += ["## Held-out files", "",
                  "| File | Cat | Deflate | zstd-19 | xz-6 | brotli-11 | SXZ4-tx | SXZ4-on | vs best |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for name in hold:
            r = meta[name]
            def g(m):
                return by[(name, m)]["bytes"] if (name, m) in by else None
            external = [g("deflate-6"), g("zstd-19"), g("xz-6"), g("brotli-11")]
            external = [v for v in external if v]
            best = min(external) if external else None
            on = g("sxz4-on")
            gap = f"{(on-best)/best:+.2%}" if best and on else "—"
            lines.append(f"| {name} | {r['category']} | {fmt(g('deflate-6'))} | {fmt(g('zstd-19'))} | "
                         f"{fmt(g('xz-6'))} | {fmt(g('brotli-11'))} | {fmt(g('sxz4-tx'))} | "
                         f"{fmt(on)} | {gap} |")
        lines.append("")

    # Per-file table: best external, tx, on, and the gain attributable to spans.
    lines += ["## Per file", "",
              "| File | Cat | In | Best external | Method | SXZ4-tx | SXZ4-on | spans | modelled | chain | models |",
              "|---|---|---:|---:|---|---:|---:|---:|---:|---|---|"]
    for name in names:
        r = meta[name]
        external = [(by[(name, m)]["bytes"], m) for m in methods
                    if m in ("deflate-6", "zstd-19", "xz-6", "brotli-11") and (name, m) in by]
        best, best_method = min(external) if external else (0, "—")
        on = by.get((name, "sxz4-on"))
        tx = by.get((name, "sxz4-tx"))
        models = ", ".join(f"{k}:{v}" for k, v in (on or {}).get("models", {}).items())
        lines.append(f"| {name} | {r['category'][:4]} | {r['bytes_in']:,} | {best:,} | `{best_method}` | "
                     f"{tx['bytes'] if tx else 0:,} | {on['bytes'] if on else 0:,} | "
                     f"{(on or {}).get('spans', 0)} | {(on or {}).get('modelled', 0):,} | "
                     f"{(on or {}).get('chain')} | {models} |")
    lines.append("")

    # Discovery accounting.
    wins = []
    for name in names:
        on = by.get((name, "sxz4-on"))
        tx = by.get((name, "sxz4-tx"))
        if on and tx and on["bytes"] < tx["bytes"] * 0.995:
            wins.append((name, tx["bytes"], on["bytes"]))
    lines += ["## Files where the span engine beats transforms-only by >0.5%", "",
              "| File | tx | on | gain |", "|---|---:|---:|---:|"]
    for name, a, b in wins:
        lines.append(f"| {name} | {a:,} | {b:,} | {(a-b)/a:.1%} |")
    lines.append("")

    # Model and mode usage.
    models: Counter = Counter()
    modes: Counter = Counter()
    chains: Counter = Counter()
    for name in names:
        on = by.get((name, "sxz4-on"))
        if not on:
            continue
        models.update(on.get("models", {}))
        modes.update(on.get("modes", {}))
        chains[str(on.get("chain"))] += 1
    lines += ["## What the engine selected", "",
              f"- models: {dict(models)}", f"- residual modes: {dict(modes)}",
              f"- transform chains: {dict(chains)}", ""]

    args.target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.target} ({len(rows)} rows, {len(names)} files)")


if __name__ == "__main__":
    main()
