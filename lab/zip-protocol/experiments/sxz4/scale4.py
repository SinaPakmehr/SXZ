"""Scaling and memory: 1, 10 and 100 MB of enwik8."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc
import zlib
from pathlib import Path

from experiments.sxz4 import spans4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path("datasets/enwik8"))
    parser.add_argument("--sizes", nargs="*", type=int, default=[1_000_000, 10_000_000, 100_000_000])
    parser.add_argument("--budget", type=float, default=30.0)
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_scaling.json"))
    args = parser.parse_args()
    data = args.source.read_bytes()
    rows = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else []
    for size in args.sizes:
        if size > len(data):
            continue
        chunk = data[:size]
        tracemalloc.start()
        start = time.perf_counter()
        blob, stats = spans4.pack(chunk, chain=(0,), time_budget=args.budget, max_probes=4000)
        encode = time.perf_counter() - start
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        start = time.perf_counter()
        assert spans4.unpack(blob) == chunk
        decode = time.perf_counter() - start
        start = time.perf_counter()
        compressed = zlib.compress(chunk, 6)
        deflate = time.perf_counter() - start
        row = {"size": size, "archive": len(blob), "ratio": len(blob) / size,
               "encode": encode, "decode": decode, "deflate_encode": deflate,
               "deflate_size": len(compressed), "peak_mb": peak / 2**20,
               "spans": stats.spans, "modelled": stats.modelled_bytes, "probes": stats.probes}
        rows = [r for r in rows if r["size"] != size] + [row]
        args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"{size/1e6:6.1f} MB archive={len(blob):>10,} ratio={row['ratio']:.3%} "
              f"enc={encode:7.2f}s dec={decode:5.2f}s deflate={deflate:5.2f}s "
              f"peak={row['peak_mb']:.0f}MB probes={stats.probes}", flush=True)


if __name__ == "__main__":
    main()
