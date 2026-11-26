"""Compare SXZ2 with mainstream and state-of-the-art compressors on the same bytes.

Every run is a separate process or library call on an identical input file. The
tool writes to a temporary file, the file is decompressed, and the SHA-256 of the
decoded bytes must match the input. Reported times are wall clock and include
process start-up for external tools.
"""

from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import lzma
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

import brotli
import zstandard
from sinuxz.stream import StreamOptions, pack_stream, unpack_stream

TOOLS = Path(os.environ.get("SXZ_COMPARE_TOOLS", r"datasets/tools"))
SEVEN = TOOLS / "7zr.exe"
ZPAQ = TOOLS / "zpaq" / "zpaq64.exe"
PAQ = TOOLS / "paq8px" / "paq8px.exe"


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def external(argv: list[str], out: Path, src: Path, decode_argv: list[str], work: Path,
             out_dir: Path) -> dict:
    """Run one CLI compressor, then decode and verify its output."""
    if out.exists():
        out.unlink()
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    start = time.perf_counter()
    subprocess.run(argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    encode = time.perf_counter() - start
    if not out.exists():
        raise RuntimeError(f"{argv[0]} did not create {out}")
    start = time.perf_counter()
    subprocess.run(decode_argv, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    decode = time.perf_counter() - start
    matches = [p for p in out_dir.rglob(src.name) if p.is_file() and p.stat().st_size == src.stat().st_size]
    if len(matches) != 1:
        raise RuntimeError(f"{argv[0]} decoded to {len(matches)} candidates in {out_dir}")
    if sha256(matches[0]) != sha256(src):
        raise RuntimeError(f"{argv[0]} round trip mismatch")
    size = out.stat().st_size
    out.unlink()
    return {"bytes": size, "encode": encode, "decode": decode}


def python_codec(kind: str, src: Path, level: int) -> dict:
    data = src.read_bytes()
    start = time.perf_counter()
    if kind == "zstd":
        packed = zstandard.ZstdCompressor(level=level, threads=-1).compress(data)
    elif kind == "brotli":
        packed = brotli.compress(data, quality=level, lgwin=24)
    elif kind == "xz":
        packed = lzma.compress(data, preset=level | (lzma.PRESET_EXTREME if level == 9 else 0))
    elif kind == "bz2":
        packed = bz2.compress(data, compresslevel=level)
    elif kind == "zlib":
        packed = zlib.compress(data, level)
    else:
        raise ValueError(kind)
    encode = time.perf_counter() - start
    start = time.perf_counter()
    if kind == "zstd":
        restored = zstandard.ZstdDecompressor().decompress(packed, max_output_size=len(data) * 2)
    elif kind == "brotli":
        restored = brotli.decompress(packed)
    elif kind == "xz":
        restored = lzma.decompress(packed)
    elif kind == "bz2":
        restored = bz2.decompress(packed)
    else:
        restored = zlib.decompress(packed)
    decode = time.perf_counter() - start
    if restored != data:
        raise RuntimeError(f"{kind} round trip mismatch")
    return {"bytes": len(packed), "encode": encode, "decode": decode}


def sxz(src: Path, out: Path, options: StreamOptions, work: Path, second_pass: bool) -> dict:
    start = time.perf_counter()
    with src.open("rb") as reader, out.open("wb") as writer:
        pack_stream(reader, writer, options, second_pass=second_pass, temp_dir=work)
    encode = time.perf_counter() - start
    restored = work / (out.name + ".restored")
    start = time.perf_counter()
    with out.open("rb") as reader, restored.open("wb") as writer:
        unpack_stream(reader, writer)
    decode = time.perf_counter() - start
    if sha256(restored) != sha256(src):
        raise RuntimeError("SXZ2 round trip mismatch")
    size = out.stat().st_size
    restored.unlink()
    out.unlink()
    return {"bytes": size, "encode": encode, "decode": decode}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--only", nargs="*", help="limit to these corpus names")
    parser.add_argument("--codecs", nargs="*", help="limit to these codec labels")
    parser.add_argument("--save", type=Path, default=Path("results/compare_codecs.json"))
    args = parser.parse_args()
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    if args.only:
        manifest = [row for row in manifest if row["name"] in args.only]
    results = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else {}
    done = {(row["corpus"], row["codec"]) for row in results.get("rows", [])}
    rows = list(results.get("rows", []))

    def record(corpus: str, codec: str, source_bytes: int, size: int, encode: float, decode: float,
               note: str = "") -> None:
        if (corpus, codec) in done:
            return
        row = {"corpus": corpus, "codec": codec, "source_bytes": source_bytes, "bytes": size,
               "ratio": size / source_bytes, "encode": encode, "decode": decode, "note": note}
        rows.append(row)
        args.save.write_text(json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8")
        print(f"{corpus:<16} {codec:<18} {size:>12,}  {row['ratio']:6.2%}  "
              f"{encode:8.2f}s {decode:8.2f}s", flush=True)

    codecs = args.codecs or [
        "sxz2-fast", "sxz2-tuned", "sxz2-best",
        "zstd-3", "zstd-19", "zstd-22",
        "xz-6", "xz-9e",
        "brotli-9", "brotli-11",
        "bzip2-9", "gzip-9",
        "7z-lzma2-9", "zpaq-m5",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for corpus in manifest:
            src = Path(corpus["path"])
            if not src.exists():
                print(f"missing {src}", flush=True)
                continue
            name, source = corpus["name"], corpus["bytes"]
            print(f"--- {name}: {source:,} bytes", flush=True)
            for codec in codecs:
                if (name, codec) in done:
                    continue
                try:
                    if codec == "sxz2-fast":
                        out = work / "a.sxz2"
                        r = sxz(src, out, StreamOptions(chunk_size=4 << 20, lookback=4, scan_budget=0,
                                                       level=1, fast_sample=True), work, False)
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"],
                               "4 MiB frames, Deflate 1, scan off")
                    elif codec == "sxz2-tuned":
                        out = work / "b.sxz2"
                        r = sxz(src, out, StreamOptions(chunk_size=1 << 20, lookback=8, scan_budget=8,
                                                       level=6, bridge=True), work, False)
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"],
                               "1 MiB frames, Deflate 6, scan 8, bridge")
                    elif codec == "sxz2-best":
                        out = work / "c.sxz2"
                        r = sxz(src, out, StreamOptions(chunk_size=1 << 20, lookback=8, scan_budget=16,
                                                       level=9, bridge=True), work, True)
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"],
                               "1 MiB frames, Deflate 9, scan 16, bridge, second pass")
                    elif codec.startswith("zstd-"):
                        r = python_codec("zstd", src, int(codec.split("-")[1]))
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"])
                    elif codec.startswith("xz-"):
                        level = 9 if codec == "xz-9e" else int(codec.split("-")[1])
                        r = python_codec("xz", src, level)
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"],
                               "single thread")
                    elif codec.startswith("brotli-"):
                        r = python_codec("brotli", src, int(codec.split("-")[1]))
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"])
                    elif codec.startswith("bzip2-"):
                        r = python_codec("bz2", src, int(codec.split("-")[1]))
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"])
                    elif codec.startswith("gzip-"):
                        r = python_codec("zlib", src, int(codec.split("-")[1]))
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"])
                    elif codec == "7z-lzma2-9":
                        out = work / "d.7z"
                        r = external([str(SEVEN), "a", "-t7z", "-m0=lzma2", "-mx=9", "-mmt=14",
                                      str(out), str(src)],
                                     out, src, [str(SEVEN), "x", "-y", f"-o{work / 'seven'}",
                                                str(out)], work, work / "seven")
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"],
                               "LZMA2 max, 14 threads")
                    elif codec == "zpaq-m5":
                        out = work / "e.zpaq"
                        r = external([str(ZPAQ), "a", str(out), str(src), "-m5", "-t14"],
                                     out, src, [str(ZPAQ), "x", str(out), "-to", str(work / "zpaq")],
                                     work, work / "zpaq")
                        record(name, codec, source, r["bytes"], r["encode"], r["decode"],
                               "PAQ-family, maximum method")
                    else:
                        print(f"unknown codec {codec}", flush=True)
                except Exception as exc:  # keep the remaining measurements going
                    print(f"FAILED {name} {codec}: {exc}", flush=True)
    print("saved", args.save, flush=True)


if __name__ == "__main__":
    main()
