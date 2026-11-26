"""Repeated timing for SXZ4 and its backend, to separate noise from cost."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import zlib
from pathlib import Path

from experiments.sxz4 import spans4, transforms4

ITEMS = ["order2-u32", "cross-3x-u16", "eeg-train", "ecg-train", "text-train", "weights-train"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("datasets/sxz4-corpus"))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_timing.json"))
    args = parser.parse_args()
    manifest = {m["name"]: m for m in json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))}
    rows = []
    for name in ITEMS:
        if name not in manifest:
            continue
        data = Path(manifest[name]["path"]).read_bytes()
        ranked = transforms4.screen(data, sample=32768)[:1]
        chain = ranked[0][1] if ranked else (0,)
        options = list(dict.fromkeys([chain, (0,)]))
        encode, decode, sizes = [], [], []
        for _ in range(args.runs):
            best = None
            total = 0.0
            for option in options:
                start = time.perf_counter()
                blob, stats = spans4.pack(data, chain=option)
                total += time.perf_counter() - start
                if best is None or len(blob) < len(best[0]):
                    best = (blob, stats, option)
            blob, stats, used = best
            encode.append(total)
            start = time.perf_counter()
            assert spans4.unpack(blob) == data
            decode.append(time.perf_counter() - start)
            sizes.append(len(blob))
        chain = used
        deflate_runs = []
        for _ in range(args.runs):
            start = time.perf_counter()
            blob = zlib.compress(data, 6)
            deflate_runs.append(time.perf_counter() - start)
            assert zlib.decompress(blob) == data
        import lzma
        import zstandard
        xz_runs, zstd_runs = [], []
        for _ in range(args.runs):
            start = time.perf_counter(); lzma.compress(data, preset=6); xz_runs.append(time.perf_counter() - start)
            start = time.perf_counter(); zstandard.ZstdCompressor(level=19).compress(data); zstd_runs.append(time.perf_counter() - start)
        row = {"item": name, "bytes": len(data), "archive": sizes[0], "chain": list(chain),
               "xz_median": statistics.median(xz_runs), "zstd_median": statistics.median(zstd_runs),
               "encode_median": statistics.median(encode), "encode_min": min(encode),
               "decode_median": statistics.median(decode), "deflate_median": statistics.median(deflate_runs),
               "spans": stats.spans, "modelled": stats.modelled_bytes}
        rows.append(row)
        print(f"{name:<18} {row['archive']:>8,} enc={row['encode_median']:.2f}s "
              f"dec={row['decode_median']:.2f}s deflate={row['deflate_median']:.3f}s "
              f"speedup={row['encode_median']/row['deflate_median']:.0f}x", flush=True)
    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
