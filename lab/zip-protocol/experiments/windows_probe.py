"""Local sample benchmark for already-compressed files and packed numeric data."""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sinuxz import StreamOptions, pack_stream, unpack_stream
from sinuxz.constants import find_reference
from sinuxz.native_scan import _load, _native_table


def samples(path: Path, size: int) -> list[bytes]:
    length = path.stat().st_size
    shifts = sorted({max(0, start) // 16 * 16 for start in (0, (length - size) // 2, length - size)})
    with path.open("rb") as src:
        result = []
        for start in shifts:
            src.seek(start)
            result.append(src.read(size))
        return result


def trial(chunks: list[bytes], options: StreamOptions) -> tuple[int, float, float, str]:
    stored, seconds, scan = 0, 0.0, 0.0
    archive_sha = hashlib.sha256()
    for chunk in chunks:
        out = io.BytesIO()
        start = time.perf_counter()
        report = pack_stream(io.BytesIO(chunk), out, options)
        seconds += time.perf_counter() - start
        scan += report.first.scan_seconds
        stored += report.stored_size
        archive_sha.update(out.getbuffer())
        out.seek(0)
        restored = io.BytesIO()
        unpack_stream(out, restored)
        if restored.getvalue() != chunk:
            raise ValueError("sample round-trip mismatch")
    return stored, seconds, scan, archive_sha.hexdigest()


def byte_planes(data: bytes, width: int, *, inverse: bool = False) -> bytes:
    if not inverse:
        return b"".join(data[i::width] for i in range(width))
    out = bytearray(len(data))
    pos = 0
    for i in range(width):
        n = len(out[i::width])
        out[i::width] = data[pos:pos + n]
        pos += n
    return bytes(out)


def nibble_planes(data: bytes, *, inverse: bool = False) -> bytes:
    end = len(data) & ~1
    if not inverse:
        hi = bytes((a & 240) | (b >> 4) for a, b in zip(data[:end:2], data[1:end:2]))
        lo = bytes(((a & 15) << 4) | (b & 15) for a, b in zip(data[:end:2], data[1:end:2]))
        return hi + lo + data[end:]
    out = bytearray(len(data))
    for i, (hi, lo) in enumerate(zip(data[:end // 2], data[end // 2:end])):
        out[2*i] = (hi & 240) | (lo >> 4)
        out[2*i+1] = ((hi & 15) << 4) | (lo & 15)
    out[end:] = data[end:]
    return bytes(out)


def set_native(library: str | None) -> None:
    if library:
        os.environ["SINUXZ_SCAN_DLL"] = library
    else:
        os.environ.pop("SINUXZ_SCAN_DLL", None)
    _load.cache_clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--size-mib", type=int, choices=range(1, 17), default=2)
    parser.add_argument("--native")
    parser.add_argument("--save", type=Path)
    args = parser.parse_args()
    if args.label and len(args.label) != len(args.files):
        parser.error("pass one --label for each file")
    cap = args.size_mib << 20
    fast = StreamOptions(chunk_size=cap, level=1, scan_budget=0, fast_sample=True)
    baseline = StreamOptions(chunk_size=cap, level=1, scan_budget=0)
    scan = StreamOptions(chunk_size=cap, level=1, scan_budget=8, experimental_models=True)
    find_reference(b"1234567890123456", 0, 16, 16)
    if args.native:
        set_native(args.native)
        _load()
        _native_table()
    lines = [
        "# Windows local file samples", "",
        f"Up to three {args.size_mib} MiB windows per file (start, middle, end, 16-byte aligned). "
        "Pack times are seconds; all candidates were decoded and byte-compared. Level 1 in every column.",
        "Fast samples three 16 KiB ranges per frame before attempting Deflate. "
        "The Python and Rust formula profiles use an otherwise identical budget of eight bank probes per frame.",
        "",
        "| Sample | Sample B | Fast B / s | Full Deflate choice B / s | "
        "Formula mode: archive B / pack s / scan s (Python) | Same mode (Rust) |",
        "|---|---:|---|---|---|---|",
    ]
    transforms = []
    for path, label in zip(args.files, args.label or [p.name for p in args.files]):
        chunks = samples(path, cap)
        set_native(None)
        f, b, py = (trial(chunks, opts) for opts in (fast, baseline, scan))
        rust = "-"
        if args.native:
            set_native(args.native)
            _load()
            n = trial(chunks, scan)
            if (n[0], n[3]) != (py[0], py[3]):
                raise ValueError("Python/Rust archive bytes differ")
            rust = f"{n[0]} / {n[1]:.3f} / {n[2]:.3f}"
        line = (f"| {label} | {sum(map(len, chunks))} | {f[0]} / {f[1]:.3f} | {b[0]} / {b[1]:.3f} "
                f"| {py[0]} / {py[1]:.3f} / {py[2]:.3f} | {rust} |")
        print(line, flush=True)
        lines.append(line)
        if path.suffix.lower() in (".bin", ".blob"):
            sizes = [sum(len(zlib.compress(chunk, 1)) for chunk in chunks)]
            for fn, kwargs in [(byte_planes, {"width": i}) for i in (2, 4, 16)] + [(nibble_planes, {})]:
                total = 0
                for chunk in chunks:
                    packed = zlib.compress(fn(chunk, **kwargs), 1)
                    if fn(zlib.decompress(packed), inverse=True, **kwargs) != chunk:
                        raise ValueError("numeric transform did not invert")
                    total += len(packed)
                sizes.append(total)
            transforms.append(f"| {label} | " + " | ".join(map(str, sizes)) + " |")
    if transforms:
        lines.extend(["", "## Numeric transform probe (zlib payload only)", "",
                      "| Sample | Identity B | Byte planes 2 | Byte planes 4 | Byte planes 16 | Nibble planes |",
                      "|---|---:|---:|---:|---:|---:|", *transforms])
    result = "\n".join(lines) + "\n"
    if args.save:
        args.save.write_text(result, encoding="utf-8")
    else:
        print(result)


if __name__ == "__main__":
    main()
