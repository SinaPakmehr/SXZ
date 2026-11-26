"""Compare the original model bank with the experimental codecs on the same bytes."""

from __future__ import annotations

import argparse
import io
import json.decoder
import platform
import random
import struct
import sys
import time
import wave
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sinuxz import Packer, inspect, unpack
from sinuxz.constants import find_reference, reference
from sinuxz.container import HEADER
from sinuxz.samples import make_png


def ppm(width: int, height: int, pixels: bytes) -> bytes:
    return f"P6\n{width} {height}\n255\n".encode("ascii") + pixels


def zip_bytes(data: bytes) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(zipfile.ZipInfo("data"), data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue()


def audio_sample() -> bytes:
    stream = io.BytesIO()
    rng = random.Random(198)
    with wave.open(stream, "wb") as out:
        out.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        out.writeframes(b"".join(
            struct.pack("<h", (min(i % 97, 97 - i % 97) - 24) * 520 + rng.randrange(-120, 121))
            for i in range(16000)
        ))
    return stream.getvalue()


def corpus() -> list[tuple[str, bytes]]:
    rng = random.Random(20261125)
    source = Path(json.decoder.__file__).read_bytes()
    logs = "".join(
        f'{{"frame":{i},"clock":{1_800_000_000_000 + 20 * i},'
        f'"sensor":{2400 + rng.randint(-4, 4)},"status":"{rng.choice(("ok", "ok", "lag"))}"}}\n'
        for i in range(1024)
    ).encode()
    grad = bytes(
        value
        for y in range(128)
        for x in range(128)
        for value in (x * 2, y * 2, x * y & 255)
    )
    constants = rng.randbytes(1027) + reference(5)[17:4017] + rng.randbytes(65536 - 5027)
    return [
        ("pi-decimal-control", reference(0)[11:1035]),
        ("e-base256-control", reference(3)[123:2171]),
        ("phi-in-random-control", constants),
        ("quadratic-u16le-control", b"".join(struct.pack("<H", (3 * i * i + 710 * i + 581) & 65535)
                                            for i in range(32768))),
        ("random-1KiB", rng.randbytes(1024)),
        ("random-64KiB", rng.randbytes(65536)),
        ("random-1MiB", rng.randbytes(1 << 20)),
        ("CPython-json-decoder.py", source),
        ("generated-telemetry.jsonl", logs),
        ("generated-PCM.wav", audio_sample()),
        ("gradient-128.ppm", ppm(128, 128, grad)),
        ("gradient-128.png", make_png(128, 128)),
        ("python-source.zip", zip_bytes(source)),
    ]


def photo_variants(path: Path) -> list[tuple[str, bytes]]:
    from PIL import Image  # optional, only to prepare the test corpus

    result = [(f"photo-original{path.suffix}", path.read_bytes())]
    with Image.open(path) as source:
        rgb = source.convert("RGB")
        for size in (32, 128, 512):
            img = rgb.resize((size, size), Image.Resampling.LANCZOS)
            result.append((f"photo-{size}.ppm", ppm(size, size, img.tobytes())))
            if size in (128, 512):
                stream = io.BytesIO()
                ext = "png" if size == 128 else "jpeg"
                img.save(stream, format=ext, **({"quality": 85} if ext == "jpeg" else {}))
                result.append((f"photo-{size}.{ext}", stream.getvalue()))
    return result


def measure(data: bytes, experimental: bool) -> tuple[int, float, float, dict]:
    packer = Packer(max_window=128, experimental_models=experimental)
    start = time.perf_counter()
    blob = packer.pack(data)
    packed = time.perf_counter()
    decoded = unpack(blob)
    end = time.perf_counter()
    if decoded != data:
        raise ValueError("round-trip mismatch")
    return len(blob), packed - start, end - packed, inspect(blob)


def describe(info: dict) -> str:
    details = []
    for seg in info["segments"]:
        kind = seg["codec"]
        if kind == "formula":
            detail = seg["detail"]
            kind = detail.split("@", 1)[0] if detail.startswith("constant-slice") else detail.split("/", 1)[0].split()[0]
        elif kind == "pnm-residual":
            kind = f"PNM-{seg['detail']}"
        if kind not in details:
            details.append(kind)
    return ", ".join(details)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photo", type=Path, help="optional photo; photo variants require Pillow")
    parser.add_argument("--file", type=Path, action="append", default=[], help="also test this file as-is")
    parser.add_argument("--files-only", action="store_true", help="skip the built-in corpus")
    parser.add_argument("--save", type=Path, help="write the Markdown report here")
    args = parser.parse_args()
    if args.files_only and not (args.file or args.photo):
        parser.error("--files-only requires at least one --file or --photo")
    # Warm only the common, fixed reference bank; table times exclude cold start.
    start = time.perf_counter()
    find_reference(b"1234567890123456", 0, 16, 16)
    setup = time.perf_counter() - start
    inputs = [] if args.files_only else corpus()
    if args.photo is not None:
        inputs += photo_variants(args.photo)
    inputs += [(p.name, p.read_bytes()) for p in args.file]

    lines = [
        "# Experimental model benchmark",
        "",
        f"Python {platform.python_version()}, {platform.system()}. Window=128 B; adaptive stride; zlib level 9.",
        f"Constant index cold start: {setup:.3f} s; excluded from table times.",
        "Sizes are bytes. `zlib+16` includes the SXZ header; `ZIP` is a complete one-entry ZIP.",
        "Formula B counts exact formula bytes in the selected archive, not PNM residuals.",
        "All produced SXZ files were decoded and compared byte for byte.",
        "",
        "| Input | Original | zlib+16 | ZIP | Base SXZ | Experimental SXZ | Formula B | Experimental codecs | Base/Exp pack s | Exp unpack s |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    if args.photo is not None:
        lines.insert(2, f"Photo source: `{args.photo.name}` (original file and RGB/PNG/JPEG variants).")
    for name, data in inputs:
        base = measure(data, False)
        ext = measure(data, True)
        line = (
            f"| {name} | {len(data)} | {len(zlib.compress(data, 9)) + HEADER.size} | {len(zip_bytes(data))} "
            f"| {base[0]} | {ext[0]} | {ext[3]['formula_bytes']} | {describe(ext[3])} "
            f"| {base[1]:.3f}/{ext[1]:.3f} | {ext[2]:.3f} |"
        )
        lines.append(line)
        print(line, flush=True)

    lines += [
        "",
        "## Constant matching, independent of archive selection",
        "",
        "Exact matches of at least 16 bytes at **every** input byte offset; overlapping starts count separately.",
        "",
        "| Input | Number of matching starts | Longest verified match (B) |",
        "|---|---:|---:|",
    ]
    for name, data in inputs:
        count = longest = 0
        for i in range(len(data)):
            match = find_reference(data, i, len(data), 16)
            if match is not None:
                count += 1
                longest = max(longest, match[0])
        lines.append(f"| {name} | {count} | {longest} |")
    report = "\n".join(lines) + "\n"
    if args.save is not None:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(report, encoding="utf-8")
        print(f"saved: {args.save}")
    else:
        print(report)


if __name__ == "__main__":
    main()
