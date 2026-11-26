"""Synthetic controls for AMRD Episode 1.

The controls test discovery accuracy.  They are not evidence of general
compression superiority.
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .inference import _solve2_odd, bm_generate, poly_predict


def make_poly_cubic(bits: int = 16, n: int = 2048):
    initials = [1000, 17, 5, 3]
    values = poly_predict(initials, n, bits)
    data = b"".join(int(value).to_bytes(bits // 8, "little") for value in values)
    return {
        "name": "synthetic-cubic-u16le",
        "family": "poly3",
        "rep": "u16le",
        "bits": bits,
        "n": n,
        "initials": initials,
        "values": values,
        "data": data,
        "description": "cubic finite-difference sequence, u16 little-endian",
    }


def make_affine1(bits: int = 16, n: int = 2048):
    a, c, x0 = 16645, 12345, 7
    mask = (1 << bits) - 1
    values = [x0]
    for _ in range(n - 1):
        values.append((a * values[-1] + c) & mask)
    data = b"".join(int(value).to_bytes(bits // 8, "little") for value in values)
    return {
        "name": "synthetic-affine1-u16le",
        "family": "affine1",
        "rep": "u16le",
        "bits": bits,
        "n": n,
        "params": (a, c, x0),
        "values": values,
        "data": data,
        "description": "first-order affine recurrence, u16 little-endian",
    }


def make_affine2(bits: int = 32, n: int = 2048):
    a, b, c, x0, x1 = 5, 11, 1234567, 1, 2
    mask = (1 << bits) - 1
    values = [x0, x1]
    for _ in range(n - 2):
        values.append((a * values[-1] + b * values[-2] + c) & mask)
    data = b"".join(int(value).to_bytes(bits // 8, "little") for value in values)
    return {
        "name": "synthetic-affine2-u32le",
        "family": "affine2",
        "rep": "u32le",
        "bits": bits,
        "n": n,
        "params": (a, b, c, x0, x1),
        "values": values,
        "data": data,
        "description": "second-order affine recurrence, u32 little-endian",
    }


def make_lfsr(n: int = 4096):
    taps = (1 << 15) | (1 << 13) | (1 << 12) | (1 << 10)
    seed = [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 1, 0, 0, 1, 0, 1]
    bits = bm_generate(seed, taps, 16, n)
    data = bytes(bits)
    return {
        "name": "synthetic-lfsr16-bit0",
        "family": "bm",
        "rep": "bit0",
        "bits": 1,
        "n": n,
        "order": 16,
        "taps": taps,
        "seed": seed,
        "values": bits,
        "data": data,
        "description": "16-bit LFSR stored in bit plane 0; other planes zero",
    }


def make_corrupt(bits: int = 16, n: int = 4096, rate: float = 0.01):
    a, b, c, x0, x1 = 5, 11, 12345, 1, 2
    mask = (1 << bits) - 1
    values = [x0, x1]
    for _ in range(n - 2):
        values.append((a * values[-1] + b * values[-2] + c) & mask)
    clean = list(values)
    rng = np.random.default_rng(20261201)
    count = max(1, int(round(n * rate)))
    positions = sorted(int(value) for value in rng.choice(n, size=count, replace=False))
    for position in positions:
        delta = int(rng.integers(1, 1 << bits))
        values[position] = (values[position] + delta) & mask
    data = b"".join(int(value).to_bytes(bits // 8, "little") for value in values)
    return {
        "name": "synthetic-corrupt-affine2-u16le",
        "family": "affine2",
        "rep": "u16le",
        "bits": bits,
        "n": n,
        "params": (a, b, c, x0, x1),
        "corrupt_positions": positions,
        "corrupt_count": count,
        "clean": clean,
        "values": values,
        "data": data,
        "description": "second-order affine recurrence with 1% symbol corruption",
    }


def make_random(n: int = 256 * 1024):
    rng = np.random.default_rng(20261202)
    values = rng.integers(0, 256, n, dtype=np.uint8)
    data = values.tobytes()
    return {
        "name": "synthetic-uniform-random",
        "family": "none",
        "rep": "u8",
        "bits": 8,
        "n": n,
        "data": data,
        "description": "independent uniform random bytes",
    }


def robust_affine2(values, bits: int):
    """Recover a corrupted order-2 affine law by voting over all equations."""
    mask = (1 << bits) - 1
    mod = 1 << bits
    differences = [(int(values[index + 1]) - int(values[index])) & mask for index in range(len(values) - 1)]
    votes = Counter()
    for n in range(2, len(differences) - 1):
        m00, m01 = differences[n - 1], differences[n - 2]
        m10, m11 = differences[n], differences[n - 1]
        r0, r1 = differences[n], differences[n + 1]
        solution = _solve2_odd(m00, m01, m10, m11, r0, r1, mod)
        if solution is None:
            continue
        a, b = solution
        if b == 0:
            continue
        c = (
            int(values[n + 2])
            - a * int(values[n + 1])
            - b * int(values[n])
        ) & mask
        votes[(a, b, c)] += 1
    if not votes:
        return None
    (a, b, c), support = votes.most_common(1)[0]
    predicted = [int(values[0]), int(values[1])]
    for _ in range(2, len(values)):
        predicted.append((a * predicted[-1] + b * predicted[-2] + c) & mask)
    matches = sum(1 for actual, want in zip(values, predicted) if int(actual) == int(want))
    residuals = [(int(actual) - int(want)) & mask for actual, want in zip(values, predicted)]
    nonzero = [value for value in residuals if value]
    packed = b"".join(int(value).to_bytes(bits // 8, "little") for value in residuals)
    histogram = Counter(packed)
    total = len(packed)
    entropy = 0.0
    for count in histogram.values():
        p = count / total
        entropy -= p * math.log2(p)
    return {
        "a": a,
        "b": b,
        "c": c,
        "support": support,
        "votes": sum(votes.values()),
        "accuracy": matches / len(values),
        "matches": matches,
        "mismatches": len(values) - matches,
        "nonzero_residuals": len(nonzero),
        "unique_residuals": len(set(nonzero)),
        "first_residual_positions": [
            index for index, value in enumerate(residuals) if value
        ][:32],
        "residual_entropy_bits_per_byte": entropy,
        "residual_bytes": total,
        "residual_zstd19": None,
        "residual_lzma2": None,
        "residuals": residuals,
    }
