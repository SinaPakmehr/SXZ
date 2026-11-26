"""Deterministic SXZ3 research corpus with ground truth and a held-out split.

Every item is a byte file on disk plus a manifest row: family, generating law,
and whether it belongs to the held-out set.  Synthetic items use a single
seeded RNG, so the corpus is reproducible byte for byte.
"""

from __future__ import annotations

import argparse
import json
import random
import struct
from pathlib import Path

from sinuxz.constants import reference

SIZE = 256 * 1024


def _rand(seed: int, n: int) -> bytes:
    return random.Random(seed).randbytes(n)


def affine(n: int, width: int, order: str, step: int, start: int = 0, phase: int = 0) -> bytes:
    mask = (1 << (8 * width)) - 1
    head = _rand(phase + 17, phase)
    out = bytearray()
    count = (n - phase) // width
    for i in range(count):
        out += ((start + i * step) & mask).to_bytes(width, order)
    return head + bytes(out)


def quadratic(n: int, width: int, order: str, d1: int, d2: int) -> bytes:
    mask = (1 << (8 * width)) - 1
    out, value, delta = bytearray(), 0, d1
    for _ in range(n // width):
        out += value.to_bytes(width, order)
        value = (value + delta) & mask
        delta = (delta + d2) & mask
    return bytes(out[:n])


def lfsr(n: int, taps: int, degree: int, seed: int) -> bytes:
    state, mask, bits = seed, (1 << degree) - 1, []
    for _ in range(n * 8):
        bits.append(state & 1)
        feedback = (state & taps).bit_count() & 1
        state = ((state >> 1) | (feedback << (degree - 1))) & mask
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
    return bytes(out)


def xorshift(n: int, seed: int, shifts: tuple[int, int, int], order: str = "big") -> bytes:
    a, b, c = shifts
    state, out = seed, bytearray()
    while len(out) < n:
        state ^= (state << a) & 0xFFFFFFFF
        state ^= state >> b
        state ^= (state << c) & 0xFFFFFFFF
        state &= 0xFFFFFFFF
        out += state.to_bytes(4, order)
    return bytes(out[:n])


def lcg(n: int, width: int, order: str, a: int, c: int, seed: int) -> bytes:
    mask = (1 << (8 * width)) - 1
    value, out = seed, bytearray()
    while len(out) < n:
        value = (a * value + c) & mask
        out += value.to_bytes(width, order)
    return bytes(out[:n])


def xorrot(n: int, width: int, order: str, c: int, k: int, seed: int) -> bytes:
    bits = 8 * width
    mask = (1 << bits) - 1
    value, out = seed, bytearray()
    while len(out) < n:
        out += value.to_bytes(width, order)
        mixed = value ^ c
        value = (((mixed >> k) | (mixed << (bits - k))) & mask) if k else mixed
    return bytes(out[:n])


def lanes(n: int, counts: int, width: int, order: str, starts: list[int], steps: list[int]) -> bytes:
    mask = (1 << (8 * width)) - 1
    out = bytearray()
    i = 0
    while len(out) < n:
        for lane in range(counts):
            out += ((starts[lane] + i * steps[lane]) & mask).to_bytes(width, order)
        i += 1
    return bytes(out[:n])


def period(n: int, record: bytes) -> bytes:
    return (record * (n // len(record) + 1))[:n]


def floats(n: int) -> bytes:
    out, value = bytearray(), 1.0
    while len(out) < n:
        out += struct.pack("<f", value)
        value *= 1.0000003
    return bytes(out[:n])


def corrupt(data: bytes, fraction: float, seed: int) -> bytes:
    rng = random.Random(seed)
    out = bytearray(data)
    for i in range(len(out)):
        if rng.random() < fraction:
            out[i] ^= 1 << rng.randrange(8)
    return bytes(out)


def slice_file(path: Path, size: int, fraction: float) -> bytes:
    total = path.stat().st_size
    start = int((total - size) * fraction)
    with path.open("rb") as handle:
        handle.seek(max(0, start))
        return handle.read(size)


def build(out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    def add(name: str, data: bytes, family: str, law: str, heldout: bool = False) -> None:
        path = out_dir / f"{name}.bin"
        path.write_bytes(data)
        rows.append({"name": name, "path": str(path), "bytes": len(data), "family": family,
                     "law": law, "heldout": heldout})

    n = SIZE
    add("ramp-u8", affine(n, 1, "little", 1), "affine", "u8 counter")
    add("ramp-u16le", affine(n, 2, "little", 5, 1000), "affine", "u16le step 5")
    add("ramp-u32be", affine(n, 4, "big", 17, 7), "affine", "u32be step 17")
    add("ramp-u64le", affine(n, 8, "little", 1, 1_700_000_000_000_000), "affine", "u64le microseconds")
    add("quadratic-u16le", quadratic(n, 2, "little", 1, 3), "quadratic", "u16le d2=3")
    add("lfsr16", lfsr(n, 0xB400, 16, 0xACE1), "lfsr", "maximal LFSR-16")
    add("xorshift-13-17-5", xorshift(n, 0x12345678, (13, 17, 5)), "prng", "xorshift32 classic")
    add("xorshift-7-9-13", xorshift(n, 0x12345678, (7, 9, 13)), "prng", "xorshift32 alt")
    add("lcg32", lcg(n, 4, "little", 1664525, 1013904223, 12345), "recurrence", "Numerical Recipes LCG")
    add("xorrot16", xorrot(n, 2, "little", 0x00FF, 5, 0x1234), "recurrence", "xor+rotl16")
    add("lanes-4x-u8", lanes(n, 4, 1, "little", [1, 90, 180, 250], [1, 3, 5, 7]), "multichannel", "4 interleaved ramps")
    add("period-20", period(n, _rand(7, 20)), "period", "20-byte record")
    add("float32-ramp", floats(n), "float", "IEEE-754 ramp")
    add("composite-sum", bytes((a + b) & 0xFF for a, b in zip(
        affine(n, 2, "little", 3, 100), affine(n, 2, "little", 5, 7))), "composite", "sum of two u16le ramps")
    add("pi-4096", reference(1)[:4096], "reference", "pi base256")
    base = affine(n, 2, "little", 5, 1000)
    for fraction in (0.01, 0.05, 0.10, 0.20):
        add(f"ramp-u16le-noise-{int(fraction*100)}", corrupt(base, fraction, 11),
            "noise", f"u16le with {fraction:.0%} corrupted bytes")
    add("random-control", _rand(99, n), "random", "seeded random")

    assets = Path("datasets/audit-assets")
    corpus = Path("datasets/compare-corpus")
    enwik = Path("datasets/enwik8")
    real = [
        ("text-train", enwik, 0.15, "text"), ("weights-train", corpus / "unavailable-weights.bin", 0.25, "weights"),
        ("exe-train", assets / "7zr.exe", 0.0, "binary"), ("ppm-train", assets / "photo.ppm", 0.30, "image"),
        ("wav-train", assets / "audio.wav", 0.40, "audio"), ("sensor-train", assets / "sensor.csv", 0.10, "sensor"),
        ("tar-train", corpus / "unavailable-mixed.tar", 0.20, "archive"),
        ("text-holdout", enwik, 0.75, "text"), ("weights-holdout", corpus / "unavailable-weights.bin", 0.70, "weights"),
        ("sensor-holdout", assets / "sensor.csv", 0.60, "sensor"),
    ]
    for name, path, fraction, family in real:
        if not path.exists():
            continue
        size = min(n, path.stat().st_size)
        add(name, slice_file(path, size, fraction), family,
            f"{path.name} slice at {fraction:.0%}", heldout=name.endswith("holdout"))

    # Held-out synthetic laws: different parameters, never used for tuning.
    add("ramp-u16le-h1", affine(n, 2, "little", 9, 4321), "affine", "u16le step 9, held out", True)
    add("lcg32-h1", lcg(n, 4, "big", 1103515245, 12345, 999), "recurrence", "glibc LCG, held out", True)
    add("xorshift-h1", xorshift(n, 0xDEADBEEF, (5, 17, 13)), "prng", "xorshift32 third, held out", True)

    # Mixed files: formula blocks interleaved with text/binary, the case where
    # architecture A's split streams actually lose cross-block history.
    law = affine(n, 2, "little", 5, 1000)
    text = slice_file(enwik, n, 0.55)
    exe = (assets / "7zr.exe").read_bytes()
    exe = (exe * (n // len(exe) + 1))[:n]
    for name, filler in (("mixed-law-text", text), ("mixed-law-exe", exe)):
        chunk = 16384
        parts = []
        for index in range(n // chunk):
            parts.append(law[index * chunk : (index + 1) * chunk] if index % 3 == 0
                         else filler[index * chunk : (index + 1) * chunk])
        add(name, b"".join(parts), "mixed", "every third 16 KiB block is a u16le law")

    (out_dir / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = build(args.output)
    print(f"{len(rows)} items, {sum(r['bytes'] for r in rows)/2**20:.1f} MiB, "
          f"{sum(r['heldout'] for r in rows)} held out")


if __name__ == "__main__":
    main()
