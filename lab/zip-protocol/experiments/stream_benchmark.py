"""Benchmark SXZ2 streaming, its optional second pass, and a solid zlib reference."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sinuxz import StreamOptions, pack_stream, unpack_stream
from sinuxz.constants import find_reference, reference

MIB = 1 << 20


def peak_bytes() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD),
                        ("peak", ctypes.c_size_t), ("unused", ctypes.c_size_t * 7)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        query = psapi.GetProcessMemoryInfo
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        stats = Counters()
        stats.size = ctypes.sizeof(stats)
        if not query(kernel.GetCurrentProcess(), ctypes.byref(stats), stats.size):
            raise ctypes.WinError(ctypes.get_last_error())
        return stats.peak
    import resource
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return raw if sys.platform == "darwin" else raw * 1024


def measure(path: Path, options: StreamOptions, temp_dir: Path | None) -> dict:
    sha = hashlib.sha256()
    solid = zlib.compressobj(options.level)
    solid_bytes = 0
    start = time.perf_counter()
    with path.open("rb") as src:
        while data := src.read(MIB):
            sha.update(data)
            solid_bytes += len(solid.compress(data))
    solid_bytes += len(solid.flush())
    solid_seconds = time.perf_counter() - start
    # Warm the fixed reference index separately from the measured passes.
    find_reference(b"1234567890123456", 0, 16, 16)
    with tempfile.TemporaryFile(dir=temp_dir) as archive, tempfile.TemporaryFile(dir=temp_dir) as decoded:
        with path.open("rb") as src:
            start = time.perf_counter()
            packed = pack_stream(src, archive, options, second_pass=True, temp_dir=temp_dir)
            pack_seconds = time.perf_counter() - start
        assert archive.tell() == packed.stored_size
        archive.seek(0)
        start = time.perf_counter()
        actual = unpack_stream(archive, decoded, max_output=packed.first.original_size, temp_dir=temp_dir)
        decode_seconds = time.perf_counter() - start
        if actual.original_size != packed.first.original_size or actual.stored_size != packed.stored_size:
            raise ValueError("SXZ2 statistics mismatch")
        decoded.seek(0)
        with path.open("rb") as src:
            while block := src.read(MIB):
                if block != decoded.read(len(block)):
                    raise ValueError(f"byte mismatch: {path.name}")
            if decoded.read(1):
                raise ValueError(f"unexpected trailing decoded bytes: {path.name}")
        return {
            "name": path.name, "sha256": sha.hexdigest(), "input": packed.first.original_size,
            "solid": solid_bytes, "solid_seconds": solid_seconds, "chunk_kib": options.chunk_size // 1024,
            "lookback": options.lookback, "frames": packed.first.frames, "first": packed.first.stored_size,
            "second": packed.second.stored_size, "nested": packed.nested,
            "first_seconds": packed.first_seconds, "second_seconds": packed.second_seconds,
            "pack_seconds": pack_seconds, "decode_seconds": decode_seconds,
            "probes": packed.first.probes, "scan_seconds": packed.first.scan_seconds,
            "formula_bytes": packed.first.formula_bytes, "codecs": dict(packed.first.codecs),
            "outer_formula_bytes": packed.second.formula_bytes, "outer_codecs": dict(packed.second.codecs),
            "peak_rss": peak_bytes(),
        }


def make_controls(root: Path) -> list[Path]:
    noise = root / "random-64MiB.bin"
    repeat = root / "repeated-32MiB.bin"
    mixed = root / "math-in-noise-32MiB.bin"
    random64 = random.Random(63)
    with noise.open("xb") as dst:
        for _ in range(64):
            dst.write(random64.randbytes(MIB))
    sample = random.Random(66).randbytes(512) * (MIB // 512)
    with repeat.open("xb") as dst:
        for _ in range(32):
            dst.write(sample)
    with mixed.open("xb") as dst:
        for data in math_control_frames():
            dst.write(data)
    return [noise, repeat, mixed]


def math_control_frames():
    """The fixture has a 600,000 B polynomial span in frame 5, and 4,000 B of e in 17."""
    rng = random.Random(69)
    for i in range(32):
        data = bytearray(rng.randbytes(MIB))
        if i == 5:
            body = b"".join(struct.pack("<H", (43 * n * n + 113 * n + 15) & 65535)
                            for n in range(300000))
            data[12347 : 12347 + len(body)] = body
        if i == 17:
            data[70891:74891] = reference(3)[33:4033]
        yield bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--controls", action="store_true")
    parser.add_argument("--chunk-kib", type=int, default=1024)
    parser.add_argument("--scan-budget", type=int, default=16)
    parser.add_argument("--lookback", type=int, default=4)
    parser.add_argument("--level", type=int, default=6)
    parser.add_argument("--bridge", action="store_true", help="try a Deflate dictionary from the preceding frame")
    parser.add_argument("--sweep-file", type=Path, help="also try 256 KiB and 4 MiB on this input")
    parser.add_argument("--work-dir", type=Path, help="temporary workspace must already exist")
    parser.add_argument("--save", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        opts = StreamOptions(args.chunk_kib * 1024, args.lookback, args.scan_budget, args.level, True, args.bridge)
        print(json.dumps(measure(args.files[0], opts, args.work_dir)))
        return
    if not args.files and not args.controls and args.sweep_file is None:
        parser.error("specify files or --controls")

    lines = [
        "# SXZ2 streaming and second-pass benchmark", "",
        f"Python {platform.python_version()}, {platform.system()} {platform.machine()}, zlib {zlib.ZLIB_RUNTIME_VERSION}.",
        f"Deflate level {args.level}, at most {args.scan_budget} heavy probes per generic frame.",
        f"32 KiB dictionary bridge: {'enabled' if args.bridge else 'disabled'}.",
        "All sizes are bytes. Solid zlib is one continuous Deflate stream without framing. "
        "The second-pass size is the full candidate; it is discarded unless strictly smaller.",
        "Both compression pass times include I/O to temporary files; the final copy is not included "
        "in either individual pass. Decode time is for the chosen archive. Every chosen output is verified "
        "byte by byte without reading the file all at once.",
        "Peak RSS is per fresh worker (Python, pack, decode and verification); OS disk caches are not process RSS.",
        "",
        "| Input | Input B | Frame KiB / lookback | Solid zlib B | First B | Second B | Kept pass | "
        "First / second s | Decode s | Peak MiB |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    rows = []

    def run(path: Path, chunk: int, lookback: int) -> None:
        cmd = [sys.executable, str(Path(__file__).resolve()), "--worker", "--chunk-kib", str(chunk),
               "--scan-budget", str(args.scan_budget), "--lookback", str(lookback), "--level", str(args.level)]
        if args.work_dir:
            cmd += ["--work-dir", str(args.work_dir)]
        if args.bridge:
            cmd.append("--bridge")
        row = json.loads(subprocess.run(
            cmd + [str(path.resolve())], check=True, capture_output=True, text=True, timeout=600,
        ).stdout)
        rows.append(row)
        line = (
            f"| {row['name']} | {row['input']} | {chunk} / {lookback} | {row['solid']} | {row['first']} "
            f"| {row['second']} | {2 if row['nested'] else 1} | {row['first_seconds']:.3f} / "
            f"{row['second_seconds']:.3f} | {row['decode_seconds']:.3f} | {row['peak_rss'] / MIB:.2f} |"
        )
        print(line, flush=True)
        lines.append(line)

    for path in args.files:
        run(path, args.chunk_kib, args.lookback)
    if args.controls:
        with tempfile.TemporaryDirectory(dir=args.work_dir) as folder:
            for path in make_controls(Path(folder)):
                run(path, args.chunk_kib, args.lookback)
                if path.name.startswith("repeated-") and args.lookback:
                    run(path, args.chunk_kib, 0)
    if args.sweep_file:
        for chunk in (256, 4096):
            if args.sweep_file not in args.files or chunk != args.chunk_kib:
                run(args.sweep_file, chunk, args.lookback)

    lines += ["", "## Formula scans and container details", "",
              "| Input | Frame KiB / lookback | First-pass scan s / probes | First-pass formula B | "
              "First codecs | Second-pass formula B | Second codecs | Total pack s |",
              "|---|---|---:|---:|---|---:|---|---:|"]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['chunk_kib']} / {r['lookback']} | {r['scan_seconds']:.3f} / {r['probes']} "
            f"| {r['formula_bytes']} | {r['codecs']} | {r['outer_formula_bytes']} | {r['outer_codecs']} "
            f"| {r['pack_seconds']:.3f} |"
        )
    lines += ["", "## Input SHA-256", "", *dict.fromkeys(f"- `{r['name']}`: `{r['sha256']}`" for r in rows), ""]
    report = "\n".join(lines)
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(report, encoding="utf-8")
        print(f"saved: {args.save}")
    else:
        print(report)


if __name__ == "__main__":
    main()
