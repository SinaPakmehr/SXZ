"""Frozen candidate streams for CGMC.

Each stream is a pure deterministic function of (decoded prefix, position).
Stream 0..31 are mathematical/PRNG generators.  Streams 32..41 are
history-derived context predictors (established LZP/repeat techniques, kept
separate for attribution).  Streams 42..49 are context-independent random-table
controls.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .context import (
    GOLDEN,
    MASK64,
    ctx_hash,
    ctx_hash_batch,
    splitmix64,
    stream_seed,
    vstream_seed,
    vsplitmix,
)

ROOT = Path(__file__).resolve().parent.parent
MAXLEN = 256
CONST_DIGITS = 4096
RAND_TABLE_BYTES = 4096


@lru_cache(maxsize=1)
def constant_tables() -> dict[str, np.ndarray]:
    raw = json.loads((ROOT / "data" / "constants.json").read_text(encoding="utf8"))
    return {k: np.frombuffer(v.encode("ascii"), dtype=np.uint8).copy() for k, v in raw.items()}


@lru_cache(maxsize=1)
def random_table() -> np.ndarray:
    """Deterministic 4 KiB byte table used by the context-independent control."""
    return np.array(
        [(splitmix64(0x5EED5EED5EED5EED + i) >> 56) & 0xFF for i in range(RAND_TABLE_BYTES)],
        dtype=np.uint8,
    )


# name, family, variant, parameter
STREAM_SPECS = [
    ("sm64-0", "sm64", 0, None),
    ("sm64-1", "sm64", 1, None),
    ("sm64-2", "sm64", 2, None),
    ("sm64-3", "sm64", 3, None),
    ("xs64-0", "xs64", 0, None),
    ("xs64-1", "xs64", 1, None),
    ("pcg32-0", "pcg32", 0, None),
    ("pcg32-1", "pcg32", 1, None),
    ("lcg32-0", "lcg32", 0, None),
    ("lcg32-1", "lcg32", 1, None),
    ("rec8-0", "rec8", 0, None),
    ("rec8-1", "rec8", 1, None),
    ("pi-0", "const", 0, "pi"),
    ("pi-1", "const", 1, "pi"),
    ("e-0", "const", 0, "e"),
    ("e-1", "const", 1, "e"),
    ("phi-0", "const", 0, "phi"),
    ("phi-1", "const", 1, "phi"),
    ("golden-0", "golden", 0, None),
    ("golden-1", "golden", 1, None),
    ("hashchain-0", "hashchain", 0, None),
    ("hashchain-1", "hashchain", 1, None),
    ("qr-0", "qr", 0, None),
    ("qr-1", "qr", 1, None),
    ("sqrt2-0", "const", 0, "sqrt2"),
    ("sqrt2-1", "const", 1, "sqrt2"),
    ("sm64-4", "sm64", 4, None),
    ("sm64-5", "sm64", 5, None),
    ("xs64-2", "xs64", 2, None),
    ("xs64-3", "xs64", 3, None),
    ("pcg32-2", "pcg32", 2, None),
    ("pcg32-3", "pcg32", 3, None),
    ("rep8", "window", 0, ("rep", 8)),
    ("rep16", "window", 0, ("rep", 16)),
    ("ramp", "window", 0, ("ramp", 1)),
    ("xor8", "window", 0, ("xor", 8, 0x5A)),
    ("rev8", "window", 0, ("rev", 8)),
    ("lzp4", "lzp", 0, 4),
    ("lzp8", "lzp", 0, 8),
    ("lzp12", "lzp", 0, 12),
    ("lzp16", "lzp", 0, 16),
    ("rep32", "window", 0, ("rep", 32)),
    ("frand-0", "fixedrand", 0, None),
    ("frand-1", "fixedrand", 1, None),
    ("frand-2", "fixedrand", 2, None),
    ("frand-3", "fixedrand", 3, None),
    ("frand-4", "fixedrand", 4, None),
    ("frand-5", "fixedrand", 5, None),
    ("frand-6", "fixedrand", 6, None),
    ("frand-7", "fixedrand", 7, None),
    ("lin8", "fitted", 0, ("lin", 1, 8)),
    ("ar8", "fitted", 0, ("ar", 1, 8)),
    ("xor2", "fitted", 0, ("xor2", 1, 8)),
    ("avg8", "fitted", 0, ("avg", 1, 8)),
    ("mul8", "fitted", 0, ("mul", 1, 8)),
    ("lin16", "fitted", 0, ("lin", 2, 16)),
    ("ar16", "fitted", 0, ("ar", 2, 16)),
    ("lin32", "fitted", 0, ("lin", 4, 32)),
    ("ar32", "fitted", 0, ("ar", 4, 32)),
    ("avg16", "fitted", 0, ("avg", 2, 16)),
    ("xor16", "fitted", 0, ("xor2", 2, 16)),
    ("lin8b", "fitted", 0, ("lin", 1, 8)),
]

STREAM_IDS = {spec[0]: i for i, spec in enumerate(STREAM_SPECS)}
MATH_IDS = list(range(0, 32))
HIST_IDS = list(range(32, 42))
RAND_IDS = list(range(42, 50))
FIT_IDS = list(range(50, 62))

CONFIGS = {
    "math8": MATH_IDS[0:8],
    "math16": MATH_IDS[0:16],
    "math32": MATH_IDS[0:32],
    "hist8": HIST_IDS[0:8],
    "hist10": HIST_IDS[0:10],
    "mixed16": MATH_IDS[0:8] + HIST_IDS[0:8],
    "mixed32": MATH_IDS[0:16] + HIST_IDS[0:10] + MATH_IDS[16:22],
    "rand8": RAND_IDS[0:8],
    "fit8": FIT_IDS[0:8],
    "fit12": FIT_IDS[0:12],
    "mathfit": MATH_IDS[0:8] + FIT_IDS[0:8],
    "fitmix": FIT_IDS[0:8] + HIST_IDS[0:8],
    "allmixed24": MATH_IDS[0:8] + FIT_IDS[0:8] + HIST_IDS[0:8],
}
assert all(len(v) == len(set(v)) for v in CONFIGS.values())
assert CONFIGS["mixed32"] and len(CONFIGS["mixed32"]) == 32

LZP_KS = (4, 8, 12, 16)


def is_math(stream_id: int) -> bool:
    return stream_id < 32


def stream_class(stream_id: int) -> str:
    if stream_id < 32:
        return "math"
    if stream_id < 42:
        return "history"
    if stream_id < 50:
        return "control"
    return "fitted"


def _const_stream(table: np.ndarray, seed: int, n: int) -> bytes:
    off = seed % (CONST_DIGITS - MAXLEN)
    return table[off : off + n].tobytes()


def gen_scalar(stream_id: int, prefix: bytes, pos: int, n: int, lzp_offset: int | None = None) -> bytes:
    """Generate ``n`` bytes for one stream at ``pos`` from the decoded prefix."""
    name, family, variant, param = STREAM_SPECS[stream_id]
    n = min(n, MAXLEN)
    h = ctx_hash(prefix, pos)
    if family == "fixedrand":
        seed = splitmix64((pos ^ (variant * GOLDEN) ^ 0xF1ED) & MASK64)
        table = random_table()
        off = seed % (RAND_TABLE_BYTES - MAXLEN)
        return table[off : off + n].tobytes()
    seed = stream_seed(h, family, variant)
    if family == "sm64":
        out = bytearray(n)
        for i in range(n):
            out[i] = (splitmix64((seed + (i + 1) * GOLDEN) & MASK64) >> 56) & 0xFF
        return bytes(out)
    if family == "golden":
        out = bytearray(n)
        for i in range(n):
            out[i] = ((seed + (i + 1) * GOLDEN) & MASK64) >> 56
        return bytes(out)
    if family == "hashchain":
        out = bytearray(n)
        x = seed
        for i in range(n):
            x = splitmix64(x)
            out[i] = (x >> 56) & 0xFF
        return bytes(out)
    if family == "xs64":
        x = seed | 1
        out = bytearray(n)
        for i in range(n):
            x ^= (x << 13) & MASK64
            x ^= x >> 7
            x ^= (x << 17) & MASK64
            out[i] = ((x * 2685821657736338717) & MASK64) >> 56
        return bytes(out)
    if family == "pcg32":
        state = seed
        inc = ((0xDA3E39CB94B95BDB + variant * 0x9E3779B9) | 1) & MASK64
        out = bytearray(n)
        for i in range(n):
            state = (state * 6364136223846793005 + inc) & MASK64
            xorshifted = (((state >> 18) ^ state) >> 27) & 0xFFFFFFFF
            rot = state >> 59
            val = ((xorshifted >> rot) | (xorshifted << ((32 - rot) & 31))) & 0xFFFFFFFF
            out[i] = (val >> 24) & 0xFF
        return bytes(out)
    if family == "lcg32":
        x = seed & 0xFFFFFFFF
        out = bytearray(n)
        for i in range(n):
            x = (1664525 * x + 1013904223) & 0xFFFFFFFF
            out[i] = (x >> 24) & 0xFF
        return bytes(out)
    if family == "rec8":
        a = ((seed >> 8) | 1) & 0xFF
        c = (seed >> 16) & 0xFF
        x = seed & 0xFF
        out = bytearray(n)
        for i in range(n):
            x = (a * x + c) & 0xFF
            out[i] = x
        return bytes(out)
    if family == "qr":
        out = bytearray(n)
        for i in range(n):
            v = ((i + 1) * (i + 1) * GOLDEN + seed) & MASK64
            out[i] = (v >> 56) & 0xFF
        return bytes(out)
    if family == "const":
        return _const_stream(constant_tables()[param], seed, n)
    if family == "fitted":
        kind, width, bits = param
        if pos < 2 * width:
            return bytes(n)
        mod = 1 << bits
        prev2 = int.from_bytes(prefix[pos - 2 * width:pos - width], "little")
        prev1 = int.from_bytes(prefix[pos - width:pos], "little")
        nw = (n + width - 1) // width
        words = [0] * nw
        if kind == "lin":
            step = (prev1 - prev2) % mod
            for i in range(nw):
                words[i] = (prev1 + (i + 1) * step) % mod
        elif kind == "ar":
            a, b = prev2, prev1
            for i in range(nw):
                a, b = b, (a + b) % mod
                words[i] = b
        elif kind == "xor2":
            a, b = prev2, prev1
            for i in range(nw):
                a, b = b, (a ^ b) % mod
                words[i] = b
        elif kind == "avg":
            a, b = prev2, prev1
            for i in range(nw):
                a, b = b, (a + b) // 2
                words[i] = b
        elif kind == "mul":
            a, b = prev2, prev1
            for i in range(nw):
                a, b = b, (a * b) % mod
                words[i] = b
        else:
            raise ValueError(kind)
        out = bytearray(n)
        for i, w in enumerate(words):
            for j in range(width):
                k = i * width + j
                if k >= n:
                    break
                out[k] = (w >> (8 * j)) & 0xFF
        return bytes(out)
    if family == "window":
        kind = param[0]
        if kind == "rep":
            period = param[1]
            if pos < period:
                return bytes(n)
            ctx = prefix[pos - period : pos]
            return (ctx * (n // period + 2))[:n]
        if kind == "ramp":
            if pos == 0:
                return bytes(range(n))
            last = prefix[pos - 1]
            return bytes(((last + i + 1) & 0xFF) for i in range(n))
        if kind == "xor":
            period, const = param[1], param[2]
            if pos < period:
                return bytes(n)
            ctx = prefix[pos - period : pos]
            return bytes((ctx[i % period] ^ const) for i in range(n))
        if kind == "rev":
            period = param[1]
            if pos < period:
                return bytes(n)
            ctx = prefix[pos - period : pos][::-1]
            return (ctx * (n // period + 2))[:n]
        raise ValueError(kind)
    if family == "lzp":
        if lzp_offset is None or lzp_offset < 0 or lzp_offset >= pos:
            return b""
        avail = pos - lzp_offset
        return bytes(prefix[lzp_offset + (i % avail)] for i in range(n))
    raise ValueError(family)


def gen_batch(stream_id: int, data: np.ndarray, positions: np.ndarray, n: int,
              lzp_offset: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised generation for analysis.

    Returns ``(candidates, valid_len)`` where candidates has shape (B, n) and
    valid_len is the number of bytes that may be matched (lzp only, else n).
    """
    name, family, variant, param = STREAM_SPECS[stream_id]
    pos = np.asarray(positions, dtype=np.int64)
    b = pos.size
    n = min(n, MAXLEN)
    if family == "fixedrand":
        with np.errstate(over="ignore"):
            seed = vsplitmix((pos.astype(np.uint64) ^ np.uint64(((variant * GOLDEN) ^ 0xF1ED) & MASK64)))
        table = random_table()
        off = (seed % np.uint64(RAND_TABLE_BYTES - MAXLEN)).astype(np.int64)
        out = table[off[:, None] + np.arange(n, dtype=np.int64)[None, :]]
        return out.astype(np.uint8), np.full(b, n, dtype=np.int64)

    h = ctx_hash_batch(data, pos)
    seed = vstream_seed(h, family, variant)
    with np.errstate(over="ignore"):
        idx = np.arange(1, n + 1, dtype=np.uint64)[None, :]
        if family == "sm64":
            out = np.empty((b, n), dtype=np.uint8)
            for i in range(n):
                v = vsplitmix(seed + np.uint64(((i + 1) * GOLDEN) & MASK64))
                out[:, i] = (v >> np.uint64(56)).astype(np.uint8)
        elif family == "golden":
            out = np.empty((b, n), dtype=np.uint8)
            for i in range(n):
                out[:, i] = ((seed + np.uint64(((i + 1) * GOLDEN) & MASK64)) >> np.uint64(56)).astype(np.uint8)
        elif family == "hashchain":
            out = np.empty((b, n), dtype=np.uint8)
            x = seed.copy()
            for i in range(n):
                x = vsplitmix(x)
                out[:, i] = (x >> np.uint64(56)).astype(np.uint8)
        elif family == "xs64":
            out = np.empty((b, n), dtype=np.uint8)
            x = seed | np.uint64(1)
            for i in range(n):
                x = x ^ ((x << np.uint64(13)) & np.uint64(MASK64))
                x = x ^ (x >> np.uint64(7))
                x = x ^ ((x << np.uint64(17)) & np.uint64(MASK64))
                y = x * np.uint64(2685821657736338717)
                out[:, i] = (y >> np.uint64(56)).astype(np.uint8)
        elif family == "pcg32":
            out = np.empty((b, n), dtype=np.uint8)
            state = seed.copy()
            inc = np.uint64(((0xDA3E39CB94B95BDB + variant * 0x9E3779B9) | 1) & MASK64)
            for i in range(n):
                state = state * np.uint64(6364136223846793005) + inc
                xorshifted = (((state >> np.uint64(18)) ^ state) >> np.uint64(27)) & np.uint64(0xFFFFFFFF)
                rot = (state >> np.uint64(59)).astype(np.uint64)
                val = ((xorshifted >> rot) | (xorshifted << ((np.uint64(32) - rot) & np.uint64(31)))) & np.uint64(0xFFFFFFFF)
                out[:, i] = (val >> np.uint64(24)).astype(np.uint8)
        elif family == "lcg32":
            out = np.empty((b, n), dtype=np.uint8)
            x = seed & np.uint64(0xFFFFFFFF)
            for i in range(n):
                x = (np.uint64(1664525) * x + np.uint64(1013904223)) & np.uint64(0xFFFFFFFF)
                out[:, i] = (x >> np.uint64(24)).astype(np.uint8)
        elif family == "rec8":
            out = np.empty((b, n), dtype=np.uint8)
            a = ((seed >> np.uint64(8)) | np.uint64(1)) & np.uint64(0xFF)
            c = (seed >> np.uint64(16)) & np.uint64(0xFF)
            x = seed & np.uint64(0xFF)
            for i in range(n):
                x = (a * x + c) & np.uint64(0xFF)
                out[:, i] = x.astype(np.uint8)
        elif family == "qr":
            out = np.empty((b, n), dtype=np.uint8)
            for i in range(n):
                v = (np.uint64((i + 1) * (i + 1)) * np.uint64(GOLDEN) + seed)
                out[:, i] = (v >> np.uint64(56)).astype(np.uint8)
        elif family == "const":
            table = constant_tables()[param]
            off = (seed % np.uint64(CONST_DIGITS - MAXLEN)).astype(np.int64)
            out = table[off[:, None] + np.arange(n, dtype=np.int64)[None, :]].astype(np.uint8)
        elif family == "fitted":
            kind, width, bits = param
            mod = 1 << bits
            valid = pos >= 2 * width
            prev2 = np.zeros(b, dtype=np.uint64)
            prev1 = np.zeros(b, dtype=np.uint64)
            for j in range(width):
                idx2 = np.clip(pos - 2 * width + j, 0, len(data) - 1)
                idx1 = np.clip(pos - width + j, 0, len(data) - 1)
                prev2 |= data[idx2].astype(np.uint64) << np.uint64(8 * j)
                prev1 |= data[idx1].astype(np.uint64) << np.uint64(8 * j)
            prev2 = np.where(valid, prev2, 0)
            prev1 = np.where(valid, prev1, 0)
            nw = (n + width - 1) // width
            words = np.zeros((b, nw), dtype=np.uint64)
            if kind == "lin":
                step = (prev1 - prev2) & np.uint64(mod - 1)
                for i in range(nw):
                    words[:, i] = (prev1 + np.uint64(i + 1) * step) & np.uint64(mod - 1)
            elif kind == "ar":
                a, c = prev2.copy(), prev1.copy()
                for i in range(nw):
                    a, c = c, (a + c) & np.uint64(mod - 1)
                    words[:, i] = c
            elif kind == "xor2":
                a, c = prev2.copy(), prev1.copy()
                for i in range(nw):
                    a, c = c, (a ^ c) & np.uint64(mod - 1)
                    words[:, i] = c
            elif kind == "avg":
                a, c = prev2.copy(), prev1.copy()
                for i in range(nw):
                    a, c = c, (a + c) // np.uint64(2)
                    words[:, i] = c
            elif kind == "mul":
                a, c = prev2.copy(), prev1.copy()
                for i in range(nw):
                    a, c = c, (a * c) & np.uint64(mod - 1)
                    words[:, i] = c
            else:
                raise ValueError(kind)
            out = np.empty((b, n), dtype=np.uint8)
            for j in range(n):
                out[:, j] = ((words[:, j // width] >> np.uint64(8 * (j % width))) & np.uint64(0xFF)).astype(np.uint8)
        elif family == "window":
            kind = param[0]
            i = np.arange(n, dtype=np.int64)[None, :]
            if kind in ("rep", "xor", "rev"):
                period = int(param[1])
                valid = pos[:, None] >= period
                ctx_idx = pos[:, None] - period + (i % period)
                if kind == "rev":
                    ctx_idx = pos[:, None] - 1 - (i % period)
                src = data[np.clip(ctx_idx, 0, len(data) - 1)]
                out = np.where(valid, src, 0).astype(np.uint8)
                if kind == "xor":
                    out = (out ^ np.uint8(param[2])).astype(np.uint8)
            elif kind == "ramp":
                last = np.where(pos > 0, data[np.maximum(pos - 1, 0)], 0).astype(np.uint64)
                out = ((last[:, None] + i.astype(np.uint64) + np.uint64(1)) & np.uint64(0xFF)).astype(np.uint8)
            else:
                raise ValueError(kind)
        elif family == "lzp":
            period = int(param)
            off = lzp_offset if lzp_offset is not None else np.full(b, -1, dtype=np.int64)
            avail = pos - off
            valid = (off >= 0) & (avail > 0)
            safe = np.maximum(avail, 1)
            i = np.arange(n, dtype=np.int64)[None, :]
            src_idx = off[:, None] + (i % safe[:, None])
            src = data[np.clip(src_idx, 0, len(data) - 1)]
            out = np.where(valid[:, None], src, 0).astype(np.uint8)
            return out, np.where(valid, n, 0).astype(np.int64)
        else:
            raise ValueError(family)
    return out.astype(np.uint8), np.full(b, n, dtype=np.int64)


def longest_prefix(cand: np.ndarray, target: np.ndarray, caps: np.ndarray | None = None) -> np.ndarray:
    """Longest exact prefix of each row, capped per row."""
    eq = cand == target
    alltrue = eq.all(axis=1)
    first_false = np.argmax(~eq, axis=1)
    length = np.where(alltrue, cand.shape[1], first_false).astype(np.int64)
    if caps is not None:
        length = np.minimum(length, caps)
    return length
