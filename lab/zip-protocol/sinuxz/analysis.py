"""Statistical forensics: what mathematical structure, if any, is in this data?

The compressor only stores a formula when it reproduces bits exactly.  When no
formula is found it is useful to know *why*: high linear complexity, no small
period, or simply high entropy.  This module reports those numbers per bit
plane, which is where byte oriented structure usually hides.
"""

from __future__ import annotations

import math
from collections import Counter

from .models import berlekamp_massey

PLANE_NAMES = ["bit7(msb)", "bit6", "bit5", "bit4", "bit3", "bit2", "bit1", "bit0(lsb)"]


def _entropy(symbols: Counter, total: int) -> float:
    if total == 0:
        return 0.0
    h = 0.0
    for count in symbols.values():
        p = count / total
        h -= p * math.log2(p)
    return h


def longest_run(bits: list[int]) -> int:
    best = 0
    run = 1
    for i in range(1, len(bits)):
        if bits[i] == bits[i - 1]:
            run += 1
            if run > best:
                best = run
        else:
            run = 1
    return max(best, min(1, len(bits)))


def smallest_period(bits: list[int], limit: int = 4096) -> int | None:
    s = "".join("1" if b else "0" for b in bits[:limit])
    for p in range(1, min(len(s) // 2, 2048) + 1):
        if s[p:] == s[:-p]:
            return p
    return None


def analyze(data: bytes, sample_bits: int = 8192) -> dict:
    if sample_bits < 1:
        raise ValueError("sample_bits must be positive")
    n = len(data)
    out: dict = {
        "size": n,
        "byte_entropy": _entropy(Counter(data), n),
        "unique_bytes": len(set(data)),
        "linear_complexity": 0,
        "linear_complexity_ratio": 0.0,
        "planes": [],
    }
    if n == 0:
        return out

    sample = min(n * 8, sample_bits)
    all_bits = []
    for byte in data[: (sample + 7) // 8]:
        all_bits.extend((byte >> s) & 1 for s in range(7, -1, -1))
    all_bits = all_bits[:sample]
    _, degree = berlekamp_massey(all_bits)
    out["linear_complexity"] = degree
    out["linear_complexity_ratio"] = degree / max(len(all_bits), 1)

    for p in range(7, -1, -1):
        bits = [((byte >> p) & 1) for byte in data]
        ones = sum(bits)
        plane_sample = min(len(bits), 1024)
        _, deg = berlekamp_massey(bits[:plane_sample])
        out["planes"].append(
            {
                "plane": PLANE_NAMES[7 - p],
                "ones_percent": 100 * ones / n,
                "entropy": _entropy(Counter(bits), n),
                "linear_complexity": deg,
                "linear_complexity_ratio": deg / max(plane_sample, 1),
                "longest_run": longest_run(bits),
                "smallest_period": smallest_period(bits, plane_sample),
            }
        )
    return out


def format_report(info: dict) -> str:
    lines = [
        f"size            : {info['size']} bytes",
        f"byte entropy    : {info['byte_entropy']:.3f} bits/byte  (ignores byte order)",
        f"unique bytes    : {info['unique_bytes']}",
        f"linear complexity (whole stream): {info['linear_complexity']} "
        f"({info['linear_complexity_ratio'] * 100:.1f}% of sample bits)",
        "",
        "| plane | ones % | entropy | LinComplex | /sample | longest run | period |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for p in info["planes"]:
        period = p["smallest_period"]
        lines.append(
            f"| {p['plane']} | {p['ones_percent']:.1f} | {p['entropy']:.3f} | "
            f"{p['linear_complexity']} | {p['linear_complexity_ratio'] * 100:.1f}% | "
            f"{p['longest_run']} | {period if period is not None else '-'} |"
        )
    return "\n".join(lines)
