"""Benchmark every SXZ variant against Deflate, Zstandard and LZMA2.

All codecs receive the same bytes and every output is decoded and compared
byte-for-byte.  Reported sizes are complete outputs, headers included.
"""

from __future__ import annotations

import argparse
import io
import json
import lzma
import time
import tracemalloc
import zlib
from pathlib import Path

import zstandard

from sinuxz.stream import StreamOptions, pack_stream, unpack_stream
from sinuxz.models import LfsrModel, XorShiftModel
from experiments.sxz3 import bank, engine

BASIC_MODELS = [bank.PeriodBytes(), LfsrModel(), XorShiftModel()]
NO_COMPOSE = [bank.PeriodBytes(), LfsrModel(), XorShiftModel(), bank.AffineWord(),
              bank.QuadraticWord(), bank.LanesWord(), bank.ReferenceSlice()]

SXZ3_VARIANTS = {
    "sxz3-A": {"arch": engine.ARCH_A},
    "sxz3-B": {"arch": engine.ARCH_B},
    "sxz3-C": {"arch": engine.ARCH_C},
    # Ablations: one change at a time.
    "sxz3-B-basic": {"arch": engine.ARCH_B, "models": BASIC_MODELS},
    "sxz3-B-exact": {"arch": engine.ARCH_B, "use_residual": False},
    "sxz3-B-adaptive": {"arch": engine.ARCH_B, "adaptive": True},
    "sxz3-B-nocompose": {"arch": engine.ARCH_B, "models": NO_COMPOSE},
}

METHODS = ["deflate-6", "deflate-9", "zstd-3", "zstd-19", "xz-6",
           "sxz2", "sxz2-scan", "sxz2+models", *SXZ3_VARIANTS]


def timed(function, data: bytes, memory: bool = False) -> tuple[bytes, float, float]:
    """Clean wall-clock encode time; peak Python allocation only when asked."""
    start = time.perf_counter()
    blob = function(data)
    encode = time.perf_counter() - start
    peak = 0.0
    if memory:
        tracemalloc.start()
        function(data)
        peak = tracemalloc.get_traced_memory()[1] / 1024
        tracemalloc.stop()
    return blob, encode, peak


def deflate6(data: bytes) -> bytes:
    return zlib.compress(data, 6)


def deflate9(data: bytes) -> bytes:
    return zlib.compress(data, 9)


def zstd3(data: bytes) -> bytes:
    return zstandard.ZstdCompressor(level=3).compress(data)


def zstd19(data: bytes) -> bytes:
    return zstandard.ZstdCompressor(level=19).compress(data)


def xz6(data: bytes) -> bytes:
    return lzma.compress(data, preset=6)


SIMPLE = {"deflate-6": (deflate6, zlib.decompress),
          "deflate-9": (deflate9, zlib.decompress),
          "zstd-3": (zstd3, lambda b: zstandard.ZstdDecompressor().decompress(b, max_output_size=1 << 31)),
          "zstd-19": (zstd19, lambda b: zstandard.ZstdDecompressor().decompress(b, max_output_size=1 << 31)),
          "xz-6": (xz6, lzma.decompress)}

SXZ2_OPTIONS = {
    "sxz2": StreamOptions(chunk_size=256 << 10, lookback=4, scan_budget=0, level=6),
    "sxz2-scan": StreamOptions(chunk_size=256 << 10, lookback=4, scan_budget=64, level=6),
    "sxz2+models": StreamOptions(chunk_size=256 << 10, lookback=4, scan_budget=64, level=6),
}


def sxz2_compress(options: StreamOptions, data: bytes) -> bytes:
    out = io.BytesIO()
    pack_stream(io.BytesIO(data), out, options)
    return out.getvalue()


def sxz2_decompress(blob: bytes) -> bytes:
    out = io.BytesIO()
    unpack_stream(io.BytesIO(blob), out)
    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--save", type=Path, default=Path("results/sxz3_bench.json"))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--methods", nargs="*", default=METHODS)
    args = parser.parse_args()
    rows = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else []
    done = {(r["name"], r["method"]) for r in rows}
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    if args.only:
        manifest = [m for m in manifest if m["name"] in args.only]

    for item in manifest:
        data = Path(item["path"]).read_bytes()
        for method in args.methods:
            if (item["name"], method) in done:
                continue
            extra: dict = {}
            if method in SXZ3_VARIANTS:
                kwargs = SXZ3_VARIANTS[method]
                holder = {}

                def run(d, kwargs=kwargs, holder=holder):
                    blob, stats = engine.pack(d, **kwargs)
                    holder["stats"] = stats
                    return blob

                blob, encode, peak = timed(run, data)
                stats = holder["stats"]
                start = time.perf_counter()
                restored = engine.unpack(blob)
                decode = time.perf_counter() - start
                extra = {"modelled": stats.modelled, "blocks": stats.blocks,
                         "models": stats.models, "residual_modes": stats.modes}
            elif method in SIMPLE:
                packer, unpacker = SIMPLE[method]
                blob, encode, peak = timed(packer, data)
                start = time.perf_counter()
                restored = unpacker(blob)
                decode = time.perf_counter() - start
            else:
                options = SXZ2_OPTIONS[method]
                if method == "sxz2+models":
                    bank.install()
                try:
                    blob, encode, peak = timed(lambda d: sxz2_compress(options, d), data)
                    start = time.perf_counter()
                    restored = sxz2_decompress(blob)
                    decode = time.perf_counter() - start
                finally:
                    if method == "sxz2+models":
                        bank.uninstall()
            if restored != data:
                raise RuntimeError(f"{item['name']}/{method} round trip mismatch")
            row = {"name": item["name"], "family": item["family"], "heldout": item["heldout"],
                   "law": item["law"], "bytes_in": len(data), "method": method,
                   "bytes": len(blob), "ratio": len(blob) / len(data),
                   "encode": encode, "decode": decode, "peak_kib": peak, **extra}
            rows.append(row)
            done.add((item["name"], method))
            args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            print(f"{item['name']:<26} {method:<12} {row['bytes']:>9,} {row['ratio']:6.2%} "
                  f"enc={encode:6.2f}s dec={decode:5.2f}s", flush=True)
    print("saved", args.save)


if __name__ == "__main__":
    main()
