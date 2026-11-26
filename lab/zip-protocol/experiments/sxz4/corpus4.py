"""Deterministic SXZ4 corpus: real, synthetic and pre-compressed, split.

Real items are slices of public files fetched into ``datasets/sxz4-data``
or of the user's own files.  Synthetic items have a known generating law.  The
three categories are reported separately on purpose.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import struct
from pathlib import Path

ROOT = Path("datasets/sxz4-data")
SXZ3 = Path("datasets/sxz3-corpus")
SIZE = 256 * 1024


def rand(seed: int, n: int) -> bytes:
    return random.Random(seed).randbytes(n)


def slice_file(path: Path, size: int, fraction: float) -> bytes:
    total = path.stat().st_size
    start = int(max(0, total - size) * fraction)
    with path.open("rb") as handle:
        handle.seek(start)
        return handle.read(size)


def order2(n: int, a: int, b: int, c: int, x0: int = 12345, x1: int = 67890,
           width: int = 4) -> bytes:
    mask = (1 << (8 * width)) - 1
    values = [x0 & mask, x1 & mask]
    while len(values) < n // width:
        values.append((a * values[-1] + b * values[-2] + c) & mask)
    return b"".join(value.to_bytes(width, "little") for value in values)[:n]


def cross(n: int, lanes: int, width: int = 2) -> bytes:
    mask = (1 << (8 * width)) - 1
    out, i = bytearray(), 0
    while len(out) < n:
        base = (100 + 3 * i) & mask
        out += base.to_bytes(width, "little")
        for lane in range(1, lanes):
            out += (((lane * 4 + 1) * base + 7 * lane) & mask).to_bytes(width, "little")
        i += 1
    return bytes(out[:n])


def piecewise(n: int) -> bytes:
    half = n // 2
    left = b"".join(struct.pack("<H", (1000 + 5 * i) & 0xFFFF) for i in range(half // 2))
    right = order2(n - half, 3, 5, 7)
    return left + right


def gorilla(n: int) -> bytes:
    """Millisecond timestamps with small irregular steps (Gorilla's target)."""
    rng = random.Random(9)
    value = 1_700_000_000_000
    out = bytearray()
    while len(out) < n:
        out += struct.pack(">q", value)
        value += 1000 + rng.randrange(0, 40)
    return bytes(out[:n])


def random_walk(n: int) -> bytes:
    """A float32 signal that is law + drift + noise; no exact formula."""
    rng = random.Random(11)
    value, out = 21.5, bytearray()
    while len(out) < n:
        value += 0.002 * (21.5 - value) + rng.gauss(0, 0.01)
        out += struct.pack("<f", value)
    return bytes(out[:n])


def csv_numeric(n: int) -> bytes:
    rng = random.Random(13)
    temp, press = 21.5, 1013.2
    lines = ["ts_ms,device,temp_c,pressure,accel"]
    t = 1_700_000_000_000
    while len("\n".join(lines)) < n:
        t += 1000
        temp += 0.002 * (21.5 - temp) + rng.gauss(0, 0.01)
        press += rng.gauss(0, 0.05)
        accel = math.sin(len(lines) / 97) * 0.4 + rng.gauss(0, 0.02)
        lines.append(f"{t},d{len(lines) % 5},{temp:.4f},{press:.3f},{accel:.4f}")
    return ("\n".join(lines) + "\n").encode()[:n]


def float64(n: int) -> bytes:
    value, out = 1.0, bytearray()
    while len(out) < n:
        out += struct.pack("<d", value)
        value *= 1.0000001
    return bytes(out[:n])


def build(out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    def add(name: str, data: bytes, family: str, category: str, law: str, heldout: bool = False):
        path = out_dir / f"{name}.bin"
        path.write_bytes(data)
        rows.append({"name": name, "path": str(path), "bytes": len(data), "family": family,
                     "category": category, "law": law, "heldout": heldout})

    n = SIZE
    add("order2-u32", order2(n, 3, 5, 7), "order2", "synthetic", "x=a*x1+b*x2+c, a=3 b=5 c=7")
    add("order2-u64", order2(n, 5, 3, 11, 10, 20, 8), "order2", "synthetic", "64-bit order-2")
    add("cross-3x-u16", cross(n, 3), "cross", "synthetic", "lane l = (4l+1)*base + 7l")
    add("cross-4x-u16", cross(n, 4), "cross", "synthetic", "4 lanes, same relation")
    add("piecewise", piecewise(n), "piecewise", "synthetic", "u16le ramp then order-2")
    add("gorilla-ts", gorilla(n), "gorilla", "synthetic", "ms timestamps, jittered steps")
    add("random-walk-f32", random_walk(n), "sensor", "synthetic", "OU drift + gaussian noise")
    add("csv-numeric", csv_numeric(n), "csv", "synthetic", "5-column telemetry with 4-decimal floats")
    add("float64-ramp", float64(n), "float64", "synthetic", "geometric float64 ramp")
    add("xorshift-5-17-13", bytes(__import__("experiments.sxz3.corpus3", fromlist=["x"]).xorshift(n, 0xDEADBEEF, (5, 17, 13))),
        "prng", "synthetic", "xorshift32 triple 5/17/13")
    add("affine-u24be", b"".join(((7 + 17 * i) & 0xFFFFFF).to_bytes(3, "big") for i in range(n // 3)),
        "affine", "synthetic", "24-bit big-endian ramp")
    noisy = bytearray(order2(n, 3, 5, 7))
    rng = random.Random(17)
    for i in range(len(noisy)):
        if rng.random() < 0.03:
            noisy[i] ^= 1 << rng.randrange(8)
    add("order2-u32-noise3", bytes(noisy), "order2", "synthetic", "order-2 with 3% byte noise")

    # Reused SXZ3 synthetic families, referenced rather than copied.
    reused = ["ramp-u16le", "quadratic-u16le", "lfsr16", "lcg32", "composite-sum",
              "float32-ramp", "pi-4096", "lanes-4x-u8"]
    manifest3 = {m["name"]: m for m in json.loads((SXZ3 / "manifest.json").read_text(encoding="utf-8"))}
    for name in reused:
        if name in manifest3:
            path = Path(manifest3[name]["path"])
            rows.append({"name": name, "path": str(path), "bytes": path.stat().st_size,
                         "family": manifest3[name]["family"], "category": "synthetic",
                         "law": manifest3[name]["law"], "heldout": False})

    # Real public data.
    eeg = ROOT / "eeg_eye_state.arff"
    if eeg.exists():
        raw = eeg.read_bytes()
        start = raw.find(b"@DATA")
        body = raw[start:] if start >= 0 else raw
        for suffix, fraction, held in (("train", 0.2, False), ("holdout", 0.7, True)):
            add(f"eeg-{suffix}", slice_file_bytes(body, n, fraction), "eeg", "real",
                f"EEG eye state ARFF, slice at {fraction:.0%}", heldout=held)
    ecg = ROOT / "mitdb_100.dat"
    if ecg.exists():
        for suffix, fraction, held in (("train", 0.2, False), ("holdout", 0.75, True)):
            add(f"ecg-{suffix}", slice_file(ecg, n, fraction), "ecg", "real",
                f"MIT-BIH record 100, slice at {fraction:.0%}", heldout=held)
    for name, family, size in (("weather_melbourne.csv", "weather", 65536),
                               ("finance_apple.csv", "finance", None),
                               ("apple_stock.csv", "finance", None),
                               ("airline_passengers.csv", "timeseries", None)):
        path = ROOT / name
        if not path.exists():
            continue
        data = path.read_bytes() if size is None else path.read_bytes()[:size]
        add(name.replace(".csv", ""), data, family, "real", f"{name}, complete file")

    # Real local files already used in earlier phases.
    local = [("text-train", Path("datasets/enwik8"), 0.15, "text", False),
             ("text-holdout", Path("datasets/enwik8"), 0.75, "text", True),
             ("weights-train", Path("datasets/compare-corpus/unavailable-weights.bin"), 0.25, "weights", False),
             ("weights-holdout", Path("datasets/compare-corpus/unavailable-weights.bin"), 0.70, "weights", True),
             ("wav-train", Path("datasets/audit-assets/audio.wav"), 0.40, "audio", False),
             ("ppm-train", Path("datasets/audit-assets/photo.ppm"), 0.30, "image", False),
             ("exe-train", Path("datasets/audit-assets/7zr.exe"), 0.0, "binary", False),
             ("tar-train", Path("datasets/compare-corpus/unavailable-mixed.tar"), 0.20, "archive", False)]
    for name, path, fraction, family, held in local:
        if not path.exists():
            continue
        data = slice_file(path, min(n, path.stat().st_size), fraction)
        add(name, data, family, "real", f"{path.name} slice at {fraction:.0%}", heldout=held)

    # Pre-compressed media: negative controls.
    flac = next(iter(Path("datasets/unavailable-inputs").rglob("*.flac")), None)
    if flac:
        add("flac-slice", slice_file(flac, n, 0.5), "compressed", "precompressed", "FLAC audio")
    jpg = next(iter(Path("datasets/unavailable-inputs").rglob("*.jpg")), None)
    if jpg:
        add("jpeg-slice", slice_file(jpg, n, 0.5), "compressed", "precompressed", "JPEG image")
    zipped = Path("datasets/enwik8.zip")
    if zipped.exists():
        add("zip-slice", slice_file(zipped, n, 0.5), "compressed", "precompressed", "ZIP archive")

    (out_dir / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows


def slice_file_bytes(data: bytes, size: int, fraction: float) -> bytes:
    start = int(max(0, len(data) - size) * fraction)
    return data[start : start + size]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = build(args.output)
    from collections import Counter

    counts = Counter(row["category"] for row in rows)
    print(f"{len(rows)} items, {sum(r['bytes'] for r in rows)/2**20:.1f} MiB, "
          f"{dict(counts)}, held out {sum(r['heldout'] for r in rows)}")


if __name__ == "__main__":
    main()
