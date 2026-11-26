"""Measure file-size scaling, formula-probe budgets, and PCM/PNM residuals."""

from __future__ import annotations

import argparse
import hashlib
import platform
import random
import shutil
import struct
import subprocess
import sys
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sinuxz import Packer, inspect, unpack
from sinuxz.constants import find_reference, reference
from sinuxz.container import HEADER
from sinuxz.pcm import wav_layout

MIB = 1 << 20


@dataclass
class Input:
    name: str
    data: bytes
    path: Path | None = None
    planted: tuple[tuple[int, int], ...] = ()


def controls() -> Iterator[Input]:
    for mib in (1, 4, 16, 32):
        yield Input(f"random-{mib}MiB", random.Random(5923 + mib).randbytes(mib * MIB))
    yield planted_control()


def planted_control() -> Input:
    def quadratic(count: int, width: int) -> bytes:
        typ = "<H" if width == 2 else "<I"
        mask = (1 << (width * 8)) - 1
        return b"".join(struct.pack(typ, (181 * i * i + 1539 * i + 64021) & mask) for i in range(count))

    patches = [
        (123457, quadratic(163840, 2)),
        (1665559, reference(3)[29:3029]),
        (2100003, quadratic(2190, 4)),
        (3999919, quadratic(511, 2)),
    ]
    data = bytearray(random.Random(177).randbytes(4 * MIB))
    for start, patch in patches:
        data[start : start + len(patch)] = patch
    return Input("planted-mix-4MiB", bytes(data), planted=tuple((x, len(y)) for x, y in patches))


def flac_size(ffmpeg: str, item: Input) -> int | None:
    layout = wav_layout(item.data)
    if item.path is None or layout is None:
        return None
    ffmpeg_flags = [ffmpeg, "-nostdin", "-v", "error"]
    encoded = subprocess.run([
        *ffmpeg_flags, "-i", str(item.path), "-map", "0:a:0", "-map_metadata", "-1",
        "-c:a", "flac", "-compression_level", "8", "-f", "flac", "pipe:1",
    ], check=True, stdout=subprocess.PIPE, timeout=180).stdout
    samples = subprocess.run([
        *ffmpeg_flags, "-f", "flac", "-i", "pipe:0", "-c:a", "pcm_s16le", "-f", "s16le", "pipe:1",
    ], input=encoded, check=True, stdout=subprocess.PIPE, timeout=180).stdout
    if samples != item.data[layout.start:layout.end]:
        raise ValueError(f"FLAC audio round-trip mismatch: {item.name}")
    return len(encoded)


def coverage(info: dict, planted: tuple[tuple[int, int], ...]) -> str:
    if not planted:
        return "-"
    hit = sum(
        max(0, min(start + length, seg["offset"] + seg["size"]) - max(start, seg["offset"]))
        for start, length in planted
        for seg in info["segments"] if seg["codec"] == "formula"
    )
    return f"{hit}/{sum(length for _, length in planted)}"


def measure(item: Input, budget: int | None, repeat: int, level: int = 9) -> tuple:
    times = []
    expected = None
    for _ in range(repeat):
        packer = Packer(max_window=128, extend_bytes=65536, level=level, experimental_models=True, scan_budget=budget)
        start = time.perf_counter()
        blob = packer.pack(item.data)
        packed = time.perf_counter()
        recovered = unpack(blob)
        unpacked = time.perf_counter()
        if recovered != item.data:
            raise ValueError(f"SXZ byte round-trip mismatch: {item.name}")
        del recovered
        times.append((packer.scan_seconds, packer.predict_seconds, packed - start, unpacked - packed))
        info = inspect(blob)
        residual = [s["detail"] for s in info["segments"] if s["codec"].endswith("-residual")]
        kinds = "+".join(info["codec_counts"])
        if residual:
            kinds += " (" + ", ".join(dict.fromkeys(residual)) + ")"
        row = len(blob), packer.probe_count, info["formula_bytes"], coverage(info, item.planted), kinds
        if expected is not None and row != expected:
            raise ValueError(f"non-deterministic benchmark output: {item.name}")
        expected = row
        del blob
    return (*expected, *(median(x) for x in zip(*times)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--controls", action="store_true", help="add generated random and planted formula files")
    parser.add_argument("--budget", type=int, default=512, help="max bank probes in bounded profile")
    parser.add_argument("--level", type=int, choices=range(10), default=9, help="Deflate level")
    parser.add_argument("--full-max-mib", type=float, default=0, help="also try uncapped bank scan up to this size")
    parser.add_argument("--full-mixed", action="store_true", help="also try uncapped scan on planted 4 MiB control")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--flac", action="store_true", help="optional FFmpeg FLAC reference for PCM audio samples")
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    if not args.files and not args.controls:
        parser.error("supply files and/or --controls")
    if args.budget < 1 or args.repeat < 1 or args.full_max_mib < 0:
        parser.error("expected a positive budget and repeat count, and a nonnegative size threshold")
    ffmpeg = shutil.which("ffmpeg") if args.flac else None
    if args.flac and ffmpeg is None:
        parser.error("--flac requires FFmpeg on PATH")

    # Exclude fixed reference-bank setup from individual pack times and report it separately.
    start = time.perf_counter()
    find_reference(b"0123456789012345", 0, 16, 16)
    warm_seconds = time.perf_counter() - start
    lines = [
        "# SXZ scaling benchmark",
        "",
        f"Python {platform.python_version()}, {platform.system()} {platform.machine()}; zlib {zlib.ZLIB_RUNTIME_VERSION}.",
        f"Probe window 128 B; maximum verified span 65536 B; Deflate level {args.level}. "
        f"{args.repeat} run(s) per profile; times are medians in seconds.",
        f"Fixed reference index cold start: {warm_seconds:.3f} s (not included in rows).",
        "All sizes are in bytes. `zlib+16` is Deflate with SXZ header; `FLAC` uses FFmpeg level 8 "
        "and verifies PCM samples only, not original WAV bytes.",
        "Each SXZ row verifies the complete input byte for byte. Times exclude file I/O, SHA-256 and FLAC. "
        "Scan and prediction are subdivisions of pack time; they are not extra time.",
        "`predict` means no formula scan; `full` is the usual adaptive stride with no fixed probe cap, not every byte.",
        "With a positive cap the cheap pi/e/phi lookup still checks skipped positions in uncommitted ranges.",
        "",
        "| Input | Input B | zlib+16 | FLAC | Profile | SXZ B | Probes | Formula B | Known hit/planted B | Codec | Scan s | Predict s | Pack s | Unpack s |",
        "|---|---:|---:|---:|---|---:|---:|---:|---:|---|---:|---:|---:|---:|",
    ]
    records = []

    def run(items: Iterator[Input]) -> None:
        for item in items:
            size = len(item.data)
            base = len(zlib.compress(item.data, args.level)) + HEADER.size
            specialist = flac_size(ffmpeg, item) if ffmpeg else None
            profiles = [("predict", 0), (f"budget {args.budget}", args.budget)]
            if item.planted and args.budget != 64:
                profiles.append(("budget 64", 64))
            if size <= args.full_max_mib * MIB or (item.planted and args.full_mixed):
                profiles.append(("full", None))
            name = item.name.replace("|", r"\|")
            for profile, budget in profiles:
                out, probes, formula, known, kinds, scan, pred, pack, decode = measure(item, budget, args.repeat, args.level)
                line = (
                    f"| {name} | {size} | {base} | {specialist if specialist is not None else '-'} | {profile} "
                    f"| {out} | {probes} | {formula} | {known} | {kinds} | {scan:.3f} | {pred:.3f} "
                    f"| {pack:.3f} | {decode:.3f} |"
                )
                print(line, flush=True)
                lines.append(line)
            records.append(f"- `{name}`: `{hashlib.sha256(item.data).hexdigest()}`")

    run(Input(path.name, path.read_bytes(), path) for path in args.files)
    if args.controls:
        run(controls())
    report = "\n".join([*lines, "", "## Input SHA-256", "", *records, ""])
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(report, encoding="utf-8")
        print(f"saved: {args.save}")
    else:
        print(report)


if __name__ == "__main__":
    main()
