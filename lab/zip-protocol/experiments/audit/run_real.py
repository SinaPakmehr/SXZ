"""Run the formula engine on real local data and report where its bytes go."""

from __future__ import annotations

import argparse
import json
import zlib
from pathlib import Path

from sinuxz.container import CODEC_FORMULA, HEADER, Packer, unpack

CONFIGS = [
    ("scan-off", 0, True),
    ("budget-8", 8, True),
    ("budget-64", 64, True),
    ("dense", None, True),
    ("dense-no-exp", None, False),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assets", nargs="+", help="name=path")
    parser.add_argument("--slice-mib", type=int, default=1)
    parser.add_argument("--offset-mib", type=int, default=2)
    parser.add_argument("--save", type=Path, default=Path("results/audit_real.json"))
    args = parser.parse_args()
    size = args.slice_mib << 20
    rows = []
    for item in args.assets:
        name, _, path = item.partition("=")
        source = Path(path)
        with source.open("rb") as handle:
            handle.seek(min(args.offset_mib << 20, max(0, source.stat().st_size - size)))
            data = handle.read(size)
        baseline = HEADER.size + len(zlib.compress(data, 6))
        print(f"--- {name}: {len(data):,} B from {source.name}, deflate {baseline:,}", flush=True)
        for label, budget, experimental in CONFIGS:
            packer = Packer(max_window=128, min_formula_bytes=16, extend_bytes=65536,
                            level=6, experimental_models=experimental, scan_budget=budget)
            packer.trace = []
            blob = packer.pack(data)
            if unpack(blob) != data:
                raise RuntimeError(f"{name}/{label} round trip mismatch")
            formula = 0
            offset = 0
            for seg in packer.segments:
                if seg.codec == CODEC_FORMULA:
                    formula += seg.size
            fits = [f for event in packer.trace for f in event.get("fits", [])]
            models: dict[str, int] = {}
            for fit in fits:
                models[fit["model"]] = models.get(fit["model"], 0) + 1
            row = {
                "asset": name, "source": str(source), "config": label,
                "bytes_in": len(data), "deflate_baseline": baseline,
                "archive_bytes": len(blob), "net_bytes": len(blob) - baseline,
                "formula_bytes": formula, "formula_share": formula / len(data),
                "probes": packer.probe_count, "scan_seconds": packer.scan_seconds,
                "accepted": sum(1 for e in packer.trace if e["accepted"]),
                "evaluated_candidates": len(fits), "candidates_by_model": models,
                "segments": len(packer.segments),
            }
            rows.append(row)
            print(f"  {label:<14} archive={len(blob):>9,} net={row['net_bytes']:>+8,} "
                  f"formula={formula:>8,} probes={packer.probe_count:>6} "
                  f"accept={row['accepted']:>5} scan={row['scan_seconds']:.1f}s", flush=True)
        args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print("saved", args.save)


if __name__ == "__main__":
    main()
