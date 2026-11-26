"""Summarise the public-real corpus (SXZ5) by category and by file family."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ORDER = ["deflate-6", "zstd-19", "xz-6", "brotli-11", "sxz3-B",
         "sxz4-off", "sxz4-tx", "sxz4-on", "sxz4-prog"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, default=Path("results/sxz5_bench.json"))
    parser.add_argument("target", type=Path, default=Path("results/sxz5_bench.md"))
    args = parser.parse_args()
    rows = json.loads(args.source.read_text(encoding="utf-8"))
    by = {(r["name"], r["method"]): r for r in rows}
    meta = {r["name"]: r for r in rows}
    names = list(dict.fromkeys(r["name"] for r in rows))
    methods = [m for m in ORDER if any(r["method"] == m for r in rows)]

    lines = ["# SXZ5 public-real corpus", "",
             "Real formats and public corpora, 256 KiB slices unless the file is smaller.",
             "All archives decoded and compared byte for byte; headers counted.", ""]

    def totals(group: list[str]) -> list[tuple[str, int, float, float]]:
        total_in = sum(meta[n]["bytes_in"] for n in group)
        out = []
        for method in methods:
            got = [by[(n, method)] for n in group if (n, method) in by]
            if not got:
                continue
            size = sum(r["bytes"] for r in got)
            out.append((method, size, size / total_in if total_in else 0,
                        sum(r["encode"] for r in got)))
        return out

    # By category.
    cats: dict[str, list[str]] = defaultdict(list)
    for n in names:
        cats[meta[n]["category"]].append(n)
    for cat in sorted(cats, key=lambda c: -sum(meta[n]["bytes_in"] for n in cats[c])):
        group = cats[cat]
        total_in = sum(meta[n]["bytes_in"] for n in group)
        lines += [f"## {cat} ({len(group)} files, {total_in:,} B)", "",
                  "| Method | Total B | Ratio | Encode s |", "|---|---:|---:|---:|"]
        for method, size, ratio, enc in totals(group):
            lines.append(f"| `{method}` | {size:,} | {ratio:.2%} | {enc:.1f} |")
        lines.append("")

    # By file family (pdf/docx/jpeg/...).
    fams: dict[str, list[str]] = defaultdict(list)
    for n in names:
        fams[meta[n]["family"]].append(n)
    lines += ["## By format family", "",
              "| Family | Files | In | Best external | SXZ4-tx | SXZ4-on | on vs best |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for fam in sorted(fams, key=lambda f: -sum(meta[n]["bytes_in"] for n in fams[f])):
        group = fams[fam]
        total_in = sum(meta[n]["bytes_in"] for n in group)
        ext = min(sum(by[(n, m)]["bytes"] for n in group) for m in
                  ("deflate-6", "zstd-19", "xz-6", "brotli-11")
                  if all((n, m) in by for n in group))
        tx = sum(by[(n, "sxz4-tx")]["bytes"] for n in group if (n, "sxz4-tx") in by)
        on = sum(by[(n, "sxz4-on")]["bytes"] for n in group if (n, "sxz4-on") in by)
        lines.append(f"| {fam} | {len(group)} | {total_in:,} | {ext:,} | {tx:,} | {on:,} | "
                     f"{(on-ext)/ext:+.1%} |")
    lines.append("")

    # Per file.
    lines += ["## Per file", "",
              "| File | Cat | Family | In | Best external | SXZ4-tx | SXZ4-on | notices | spans | chain |",
              "|---|---|---|---:|---:|---:|---:|---|---:|---|"]
    for n in names:
        r = meta[n]
        ext = [(by[(n, m)]["bytes"], m) for m in ("deflate-6", "zstd-19", "xz-6", "brotli-11")
               if (n, m) in by]
        best, bm = min(ext)
        on = by.get((n, "sxz4-on"), {})
        tx = by.get((n, "sxz4-tx"), {})
        lines.append(f"| {n} | {r['category']} | {r['family']} | {r['bytes_in']:,} | {best:,} (`{bm}`) | "
                     f"{tx.get('bytes', 0):,} | {on.get('bytes', 0):,} | "
                     f"{on.get('models', {})} | {on.get('spans', 0)} | {on.get('chain')} |")
    lines.append("")

    # Held-out.
    hold = [n for n in names if meta[n].get("heldout")]
    if hold:
        lines += ["## Held-out", "",
                  "| File | Family | Best external | SXZ4-on | gap |", "|---|---|---:|---:|---:|"]
        for n in hold:
            ext = [(by[(n, m)]["bytes"], m) for m in ("deflate-6", "zstd-19", "xz-6", "brotli-11")
                   if (n, m) in by]
            best, bm = min(ext)
            on = by[(n, "sxz4-on")]["bytes"] if (n, "sxz4-on") in by else 0
            lines.append(f"| {n} | {meta[n]['family']} | {best:,} (`{bm}`) | {on:,} | "
                         f"{(on-best)/best:+.1%} |")
        lines.append("")

    args.target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {args.target} ({len(rows)} rows, {len(names)} files)")


if __name__ == "__main__":
    main()
