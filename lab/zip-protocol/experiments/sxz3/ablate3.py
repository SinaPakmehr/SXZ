"""Block-size ablation and peak-allocation measurements for SXZ3."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path

from experiments.sxz3 import engine

ITEMS = ["ramp-u16le", "sensor-train", "text-train", "weights-train"]
SIZES = [8192, 32768, 131072]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("datasets/sxz3-corpus"))
    parser.add_argument("--save", type=Path, default=Path("results/sxz3_ablate.json"))
    args = parser.parse_args()
    manifest = {m["name"]: m for m in json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))}
    rows = []
    for name in ITEMS:
        data = Path(manifest[name]["path"]).read_bytes()
        for size in SIZES:
            start = time.perf_counter()
            blob, stats = engine.pack(data, arch=engine.ARCH_B, block_size=size)
            encode = time.perf_counter() - start
            if engine.unpack(blob) != data:
                raise RuntimeError(f"{name}/{size} round trip mismatch")
            rows.append({"item": name, "block": size, "bytes": len(blob), "input": len(data),
                         "encode": encode, "modelled": stats.modelled, "blocks": stats.blocks})
            print(f"{name:<16} block={size:>7} {len(blob):>8,} modelled={stats.modelled}/{stats.blocks} "
                  f"{encode:5.2f}s", flush=True)
    # Peak allocation for the default configuration, one representative item.
    for name in ("sensor-train", "weights-train"):
        data = Path(manifest[name]["path"]).read_bytes()
        tracemalloc.start()
        engine.pack(data, arch=engine.ARCH_B)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        rows.append({"item": name, "block": engine.BLOCK, "peak_kib": peak / 1024})
        print(f"{name:<16} peak allocation {peak / 1024:.0f} KiB", flush=True)
    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
