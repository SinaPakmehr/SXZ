"""Render every validation table into one Markdown file."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

V = Path("results/sxz4_validation.json")
A = Path("results/sxz4_ablate.json")
C = Path("results/sxz4_container.json")
B8 = Path("results/sxz4_bench_8files.json")
OUT = Path("results/sxz4_tables.md")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def main() -> None:
    rows = load(V) + load(A)
    lines = ["# SXZ4 validation tables", ""]

    # Noise.
    noise = [r for r in rows if r.get("suite") == "noise"]
    if noise:
        lines += ["## Noise sweep", "",
                  "Value noise is Gaussian on the word; byte noise flips random bits.",
                  "", "| Family | Rate | Deflate | xz | SXZ4-tx | SXZ4-on | on/deflate | spans |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        for r in noise:
            d = r["rows"]
            lines.append(f"| {r['name']} | {r['rate']:.3f} | {d['deflate-6']['bytes']:,} | "
                         f"{d['xz-6']['bytes']:,} | {d['sxz4-tx']['bytes']:,} | "
                         f"{d['sxz4-on']['bytes']:,} | "
                         f"{d['sxz4-on']['bytes']/d['deflate-6']['bytes']:.1%} | "
                         f"{d['sxz4-on'].get('spans', 0)} |")
        lines.append("")

    # Planted spans.
    spans = [r for r in rows if r.get("suite") == "spans"]
    if spans:
        lines += ["## Planted spans (random base, law segments)", "",
                  "`found` is (start error, overlap fraction, span length); `None` means no overlap.",
                  "", "| Len | Count | Mode | Spans | Modelled | Bytes | Found |",
                  "|---:|---:|---|---:|---:|---:|---|"]
        for r in spans:
            found = "; ".join("—" if f is None else f"Δ{s[0]}, ov{s[1]}" for f in r["found"]
                              for s in [f] if f is not None) or "—"
            if any(f is not None for f in r["found"]):
                found = "; ".join("—" if f is None else f"Δ{f[0]}, ov{f[1]}"
                                  for f in r["found"])
            lines.append(f"| {r['length']:,} | {r['count']} | {r['mode']} | {r['spans']} | "
                         f"{(r['modelled'] or 0):,} | {(r['bytes'] or 0):,} | {found} |")
        lines.append("")

    # Unknown laws.
    unknown = [r for r in rows if r.get("suite") == "unknown"]
    if unknown:
        lines += ["## Laws outside the bank", "",
                  "| Family | Gate | has_law | Bytes | Spans | Models |", "|---|---|---|---:|---:|---|"]
        for r in unknown:
            lines.append(f"| {r['name']} | {'on' if r['gate'] else 'off'} | {r['has_law']} | "
                         f"{r['bytes']:,} | {r['spans']} | {r['models']} |")
        lines.append("")

    # Decompose.
    dec = [r for r in rows if r.get("suite") == "decompose"]
    if dec:
        lines += ["## Component decomposition", "",
                  "| File | backend | +tx | +exact | model+residual | program | full |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for r in dec:
            cells = []
            for key in ("backend-only", "backend+tx", "backend+exact",
                        "backend+model+residual", "program", "full"):
                v = r.get(key)
                cells.append("—" if not v else f"{v['bytes']:,}")
            lines.append(f"| {r['name']} | " + " | ".join(cells) + " |")
        lines.append("")

    # Tolerance.
    tol = [r for r in rows if r.get("suite") == "tolerance"]
    if tol:
        lines += ["## Expansion tolerance", "", "| File | tol | Bytes | Spans | Chain |",
                  "|---|---:|---:|---:|---|"]
        for r in tol:
            lines.append(f"| {r['name']} | {r['tolerance']} | {r['bytes']:,} | "
                         f"{r['spans']} | {r['chain']} |")
        lines.append("")

    # Gate.
    gate = [r for r in rows if r.get("suite") == "gate"]
    if gate:
        lines += ["## Cheap gate", "", "| File | gate on B | on s | gate off B | off s |",
                  "|---|---:|---:|---:|---:|"]
        for r in gate:
            lines.append(f"| {r['name']} | {r['on']['bytes']:,} | {r['on']['encode']:.2f} | "
                         f"{r['off']['bytes']:,} | {r['off']['encode']:.2f} |")
        lines.append("")

    # Global.
    glob = [r for r in rows if r.get("suite") == "global"]
    if glob:
        lines += ["## Greedy vs global selection", "",
                  "| Case | Candidates | Greedy spans | Greedy B | Global spans | Global B |",
                  "|---|---:|---:|---:|---:|---:|"]
        for r in glob:
            lines.append(f"| {r['name']} | {r['candidates']} | {r['greedy_spans']} | "
                         f"{r['greedy_bytes']:,} | {r['global_spans']} | {r['global_bytes']:,} |")
        lines.append("")

    # Backend comparison from the validation suite.
    be = [r for r in rows if r.get("suite") == "backends"]
    if be:
        lines += ["## Formula engine with three backends", "",
                  "| File | tx-deflate | on-deflate | tx-zstd | on-zstd | tx-lzma | on-lzma |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        for r in be:
            def g(key):
                v = r.get(key)
                return f"{v['bytes']:,}" if v else "—"
            lines.append(f"| {r['name']} | {g('tx-deflate')} | {g('on-deflate')} | "
                         f"{g('tx-zstd')} | {g('on-zstd')} | {g('tx-lzma')} | {g('on-lzma')} |")
        lines.append("")

    # Container.
    cont = load(C)
    if cont:
        lines += ["## Container recompression", "",
                  "`repro` counts members whose original Deflate stream could be rebuilt",
                  "from the content and a recorded zlib level; `ok` is byte-exact restore.",
                  "", "| File | Bytes | Recompressed | Ratio | xz whole | repro | ok |",
                  "|---|---:|---:|---:|---:|---|---|"]
        for r in cont:
            lines.append(f"| {r['name']} | {r['bytes']:,} | {r['total']:,} | "
                         f"{r['ratio']:.2%} | {r['xz_whole']:,} | "
                         f"{r['reproducible']}/{r.get('members', r.get('streams'))} | {r['ok']} |")
        lines.append("")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
