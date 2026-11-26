"""Render results/sxz3_bench.json as Markdown tables and gap summaries."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

REFS = ["deflate-6", "deflate-9", "zstd-3", "zstd-19", "xz-6"]
MAIN = ["sxz2", "sxz2-scan", "sxz2+models", "sxz3-A", "sxz3-B", "sxz3-C"]
ABLATION = ["sxz3-B-basic", "sxz3-B-exact", "sxz3-B-adaptive", "sxz3-B-nocompose"]
ORDER = REFS + MAIN + ABLATION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=Path("results/sxz3_bench.json"))
    parser.add_argument("--save", type=Path, default=Path("results/sxz3_bench.md"))
    args = parser.parse_args()
    rows = json.loads(args.json.read_text(encoding="utf-8"))
    by = {(r["name"], r["method"]): r for r in rows}
    names = []
    for row in rows:
        if row["name"] not in names:
            names.append(row["name"])
    info = {row["name"]: row for row in rows}
    lines = ["# SXZ3 benchmark", "",
             "Every output was decoded and compared byte for byte with the input.",
             "Sizes are complete files including headers; times are wall clock, one run.",
             "`sxz2` is the shipped format with its product settings; `sxz2-scan` turns its",
             "formula scan on; `sxz2+models` installs the new bank into the same format.",
             "`sxz3-*` use 32 KiB blocks. Held-out items are marked with `*`.", ""]

    # Per-item table.
    header = "| Item | Raw | " + " | ".join(ORDER) + " | SXZ3-B vs best ref |"
    lines += [header, "|---|" + "---:|" * (len(ORDER) + 2)]
    for name in names:
        raw = info[name]["bytes_in"]
        cells = []
        for method in ORDER:
            row = by.get((name, method))
            cells.append(f"{row['bytes']:,}" if row else "—")
        refs = [by[(name, m)]["bytes"] for m in REFS if (name, m) in by]
        sxz3 = by.get((name, "sxz3-B"))
        gap = f"{sxz3['bytes'] / min(refs) - 1:+.2%}" if sxz3 and refs else "—"
        mark = "*" if info[name]["heldout"] else ""
        lines.append(f"| {name}{mark} | {raw:,} | " + " | ".join(cells) + f" | {gap} |")
    lines.append("")

    # Totals and geometric means.
    lines += ["## Totals", "", "| Method | Total bytes | Ratio of all inputs | Encode s | Decode s |",
              "|---|---:|---:|---:|---:|---:|"]
    for method in ORDER:
        subset = [r for r in rows if r["method"] == method]
        if not subset:
            continue
        total = sum(r["bytes"] for r in subset)
        raw = sum(r["bytes_in"] for r in subset)
        enc = sum(r["encode"] for r in subset)
        dec = sum(r["decode"] for r in subset)
        lines.append(f"| `{method}` | {total:,} | {total / raw:.2%} | {enc:.1f} | {dec:.1f} |")
    lines.append("")

    # Per-family means.
    families = sorted({r["family"] for r in rows})
    lines += ["## Mean ratio by family", "",
              "| Family | " + " | ".join(MAIN + ["zstd-19", "xz-6"]) + " |",
              "|---|" + "---:|" * (len(MAIN) + 2)]
    for family in families:
        cells = []
        for method in MAIN + ["zstd-19", "xz-6"]:
            subset = [r["ratio"] for r in rows if r["family"] == family and r["method"] == method]
            cells.append(f"{100 * sum(subset) / len(subset):.2f}%" if subset else "—")
        lines.append(f"| {family} | " + " | ".join(cells) + " |")
    lines.append("")

    # Wins and losses against the best reference.
    lines += ["## Where SXZ3-B beats the best reference", "",
              "| Item | SXZ3-B | Best reference | Saving |", "|---|---:|---:|---:|"]
    for name in names:
        refs = {m: by[(name, m)]["bytes"] for m in REFS if (name, m) in by}
        sxz3 = by.get((name, "sxz3-B"))
        if not refs or not sxz3:
            continue
        best_method = min(refs, key=refs.get)
        saving = 1 - sxz3["bytes"] / refs[best_method]
        if saving > 0.01:
            lines.append(f"| {name} | {sxz3['bytes']:,} | {best_method}: {refs[best_method]:,} | {saving:.1%} |")
    lines.append("")

    # Detection detail.
    lines += ["## What the engine selected", "",
              "| Item | Modelled blocks | Models | Residual modes |", "|---|---:|---|---|"]
    for name in names:
        row = by.get((name, "sxz3-B"))
        if not row or "modelled" not in row:
            continue
        lines.append(f"| {name} | {row['modelled']}/{row['blocks']} | "
                     f"{', '.join(f'{k}×{v}' for k, v in row.get('models', {}).items()) or '—'} | "
                     f"{', '.join(f'{k}×{v}' for k, v in row.get('residual_modes', {}).items()) or '—'} |")
    lines.append("")

    # Ablation.
    lines += ["## Ablations (32 KiB blocks, architecture B)", "",
              "| Item | full | basic bank | exact only | adaptive gate | no composite |",
              "|---|---:|---:|---:|---:|---:|"]
    for name in names:
        cells = []
        for method in ("sxz3-B", "sxz3-B-basic", "sxz3-B-exact", "sxz3-B-adaptive", "sxz3-B-nocompose"):
            row = by.get((name, method))
            cells.append(f"{row['bytes']:,}" if row else "—")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("")

    args.save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:40]))
    print(f"wrote {args.save}")


if __name__ == "__main__":
    main()
