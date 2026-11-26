"""Targeted probes for specific model-bank limits (period length, PRNG family, byte width)."""

from __future__ import annotations

import json
import random
from pathlib import Path

from sinuxz.bitio import bytes_to_bits
from sinuxz.container import CODEC_FORMULA, HEADER, Packer, unpack

M32 = 0xFFFFFFFF


def xorshift(data_seed: int, shifts: tuple[int, int, int]) -> bytes:
    a, b, c = shifts
    x = data_seed
    out = bytearray()
    while len(out) < 4096:
        x ^= (x << a) & M32
        x ^= x >> b
        x ^= (x << c) & M32
        x &= M32
        out += x.to_bytes(4, "big")
    return bytes(out[:4096])


def periodic(period: int) -> bytes:
    base = bytes(range(65, 65 + period)) if period <= 26 else bytes(
        (i * 37 + 11) & 0xFF for i in range(period))
    return base * (4096 // period)


def run(name: str, pattern: bytes, *, budget, experimental=True, window=128) -> dict:
    rng = random.Random(99)
    data = rng.randbytes(2048) + pattern + rng.randbytes(12000)
    start, length = 2048, len(pattern)
    packer = Packer(max_window=window, min_formula_bytes=16, extend_bytes=65536,
                    level=6, experimental_models=experimental, scan_budget=budget)
    packer.trace = []
    blob = packer.pack(data)
    assert unpack(blob) == data
    covered, offset = 0, 0
    for seg in packer.segments:
        if seg.codec == CODEC_FORMULA:
            covered += max(0, min(offset + seg.size, start + length) - max(offset, start))
        offset += seg.size
    accepted = sum(max(0, min(e["pos"] + e["span"], start + length) - max(e["pos"], start))
                   for e in packer.trace if e["accepted"])
    baseline = HEADER.size + __import__("zlib").compress(data, 6).__len__()
    return {"case": name, "budget": budget, "planted": length, "covered": covered,
            "coverage": covered / length, "accepted_cover": accepted,
            "accepted_fraction": accepted / length,
            "net": len(blob) - baseline, "probes": packer.probe_count,
            "accepted": sum(1 for e in packer.trace if e["accepted"]),
            "models": sorted({e["model"] for e in packer.trace if e["accepted"]})}


def main() -> None:
    cases = {
        "period-8-bytes": periodic(8),
        "period-16-bytes": periodic(16),
        "period-17-bytes": periodic(17),
        "period-20-bytes": periodic(20),
        "period-32-bytes": periodic(32),
        "xorshift-13-17-5": xorshift(0x12345678, (13, 17, 5)),
        "xorshift-7-9-13": xorshift(0x12345678, (7, 9, 13)),
        "xorshift-2-7-9": xorshift(0x12345678, (2, 7, 9)),
    }
    rows = []
    for name, pattern in cases.items():
        for budget in (None, 64, 8):
            row = run(name, pattern, budget=budget)
            rows.append(row)
            print(f"{name:<20} budget={str(budget):<5} accepted={row['accepted_fraction']:6.1%} "
                  f"emitted={row['coverage']:6.1%} net={row['net']:+6d} "
                  f"accept#={row['accepted']:<4} models={row['models']}", flush=True)
    Path("results/audit_extra.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
