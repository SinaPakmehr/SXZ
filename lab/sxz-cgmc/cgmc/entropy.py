"""A real range coder and an order-2 context model with candidate mixing.

The experiment answers a narrow question: given the *same* order-2 context and
the same range coder, does adding context-derived next-byte predictions from
mathematical generators reduce the realised archive size?

Model
-----
P(s | c2) = (count2[c2, s] + A * P(s | c1)) / (n2[c2] + A)
P(s | c1) = (count1[c1, s] + B * P(s)) / (n1[c1] + B)
P(s)      = (count0[s] + 1) / (n0 + 256)

Candidate mixture: P' = (1-w) P + w Pcand, where Pcand places half its mass on
the predicted next bytes (weighted by past per-stream hit counts) and half on
the uniform distribution (escape).  All updates use only bytes already coded.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .context import GOLDEN, MASK64, ctx_hash, splitmix64
from .streams import constant_tables, random_table

TOP = 1 << 24
BOT = 1 << 16
MASK32 = 0xFFFFFFFF
TOTAL = 1 << 15
ALPHA = 24.0
BETA = 6.0


class RangeEncoder:
    def __init__(self) -> None:
        self.low = 0
        self.range = MASK32
        self.out = bytearray()

    def _normalize(self) -> None:
        while True:
            if (self.low ^ ((self.low + self.range) & MASK32)) < TOP:
                pass
            elif self.range < BOT:
                self.range = (-self.low) & (BOT - 1)
            else:
                break
            self.out.append((self.low >> 24) & 0xFF)
            self.low = (self.low << 8) & MASK32
            self.range = (self.range << 8) & MASK32

    def encode(self, cum: int, freq: int, total: int = TOTAL) -> None:
        self.range //= total
        self.low = (self.low + cum * self.range) & MASK32
        self.range *= freq
        self._normalize()

    def finish(self) -> bytes:
        for _ in range(4):
            self.out.append((self.low >> 24) & 0xFF)
            self.low = (self.low << 8) & MASK32
        return bytes(self.out)


class RangeDecoder:
    def __init__(self, blob: bytes) -> None:
        if len(blob) < 4:
            raise ValueError("short range stream")
        self.blob = blob
        self.pos = 4
        self.low = 0
        self.range = MASK32
        self.code = int.from_bytes(blob[:4], "big")

    def _normalize(self) -> None:
        while True:
            if (self.low ^ ((self.low + self.range) & MASK32)) < TOP:
                pass
            elif self.range < BOT:
                self.range = (-self.low) & (BOT - 1)
            else:
                break
            self.low = (self.low << 8) & MASK32
            self.range = (self.range << 8) & MASK32
            b = self.blob[self.pos] if self.pos < len(self.blob) else 0
            self.pos += 1
            self.code = ((self.code << 8) | b) & MASK32

    def target(self, total: int = TOTAL) -> int:
        self.range //= total
        v = (self.code - self.low) // self.range
        return min(max(v, 0), total - 1)

    def update(self, cum: int, freq: int) -> None:
        self.low = (self.low + cum * self.range) & MASK32
        self.range *= freq
        self._normalize()


def _freqs(p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    freq = np.floor(p * TOTAL).astype(np.int64)
    np.maximum(freq, 1, out=freq)
    diff = TOTAL - int(freq.sum())
    if diff:
        idx = int(np.argmax(freq))
        freq[idx] += diff
        if freq[idx] < 1:
            raise AssertionError("frequency adjustment underflow")
    cum = np.empty(257, dtype=np.int64)
    cum[0] = 0
    np.cumsum(freq, out=cum[1:])
    if int(cum[-1]) != TOTAL:
        raise AssertionError("frequency total")
    return freq, cum


class Predictors:
    """Cheap first-byte predictions from the frozen stream catalog."""

    STREAMS = [
        (0, "sm64", 0, None),
        (4, "xs64", 0, None),
        (6, "pcg32", 0, None),
        (8, "lcg32", 0, None),
        (10, "rec8", 0, None),
        (12, "const", 0, "pi"),
        (50, "fitted", 0, ("lin", 1, 8)),
        (51, "fitted", 0, ("ar", 1, 8)),
        (37, "lzp", 0, 8),
    ]

    def __init__(self, ids=None) -> None:
        self.ids = list(range(len(self.STREAMS))) if ids is None else list(ids)
        self.hits = np.ones(len(self.ids), dtype=np.float64)
        self.lzp: dict[bytes, int] = {}

    def predict(self, buf, pos: int, h: int) -> tuple[list[int], np.ndarray]:
        preds: list[int] = []
        phi_tables = constant_tables()
        for k, idx in enumerate(self.ids):
            sid, family, variant, param = self.STREAMS[idx]
            if family == "sm64":
                seed = splitmix64((h ^ 0x534D3634_00000001 ^ ((variant * GOLDEN) & MASK64)) & MASK64)
                b = (splitmix64((seed + GOLDEN) & MASK64) >> 56) & 0xFF
            elif family == "xs64":
                seed = splitmix64((h ^ 0x58533634_00000002 ^ ((variant * GOLDEN) & MASK64)) & MASK64) | 1
                x = seed
                x ^= (x << 13) & MASK64
                x ^= x >> 7
                x ^= (x << 17) & MASK64
                b = ((x * 2685821657736338717) & MASK64) >> 56
            elif family == "pcg32":
                seed = splitmix64((h ^ 0x50434733_00000003) & MASK64)
                inc = ((0xDA3E39CB94B95BDB + variant * 0x9E3779B9) | 1) & MASK64
                state = (seed * 6364136223846793005 + inc) & MASK64
                xorshifted = (((state >> 18) ^ state) >> 27) & 0xFFFFFFFF
                rot = state >> 59
                val = ((xorshifted >> rot) | (xorshifted << ((32 - rot) & 31))) & 0xFFFFFFFF
                b = (val >> 24) & 0xFF
            elif family == "lcg32":
                seed = splitmix64((h ^ 0x4C434733_00000004) & MASK64)
                x = ((1664525 * (seed & 0xFFFFFFFF)) + 1013904223) & 0xFFFFFFFF
                b = (x >> 24) & 0xFF
            elif family == "rec8":
                seed = splitmix64((h ^ 0x52454338_00000005) & MASK64)
                a = ((seed >> 8) | 1) & 0xFF
                c = (seed >> 16) & 0xFF
                b = (a * (seed & 0xFF) + c) & 0xFF
            elif family == "const":
                seed = splitmix64((h ^ 0x434F4E53_00000006 ^ ((variant * GOLDEN) & MASK64)) & MASK64)
                table = phi_tables[param]
                b = int(table[seed % (len(table) - 256)])
            elif family == "fitted":
                kind, width, bits = param
                if pos < 2 * width:
                    b = 0
                else:
                    p2 = int.from_bytes(bytes(buf[pos - 2 * width:pos - width]), "little")
                    p1 = int.from_bytes(bytes(buf[pos - width:pos]), "little")
                    mod = 1 << bits
                    b = ((2 * p1 - p2) if kind == "lin" else (p1 + p2)) % mod
            elif family == "lzp":
                q = self.lzp.get(bytes(buf[pos - 8:pos]), -1) if pos >= 8 else -1
                b = buf[q] if 0 <= q < pos else 0
            else:
                b = 0
            preds.append(int(b) & 0xFF)
        if not preds:
            return preds, np.zeros(0, dtype=np.float64)
        weights = self.hits / self.hits.sum()
        return preds, weights

    def update(self, preds: list[int], actual: int) -> None:
        for k, b in enumerate(preds):
            if b == actual:
                self.hits[k] += 1.0
            else:
                self.hits[k] *= 0.9995
        self.hits = np.maximum(self.hits, 1e-3)


@dataclass
class EntropyResult:
    bytes: int
    encode_s: float
    decode_s: float
    verified: bool
    bits_per_byte: float


def _candidate_dist(preds: list[int], weights: np.ndarray) -> np.ndarray:
    if not preds:
        return np.full(256, 1.0 / 256.0, dtype=np.float64)
    q = np.full(256, 0.5 / 256.0, dtype=np.float64)
    for k, b in enumerate(preds):
        q[b] += 0.5 * weights[k]
    return q


def _mixture(p: np.ndarray, preds: list[int], weights: np.ndarray, w: float) -> np.ndarray:
    if w <= 0:
        return p
    q = _candidate_dist(preds, weights)
    return (1.0 - w) * p + w * q


def encode(data: bytes, weight: float = 0.0, adaptive: bool = False,
           chunk_report: int = 0, pred_ids=None) -> tuple[bytes, dict]:
    import time
    t0 = time.perf_counter()
    n = len(data)
    c0 = np.zeros(256, dtype=np.int64)
    c1 = np.zeros((256, 256), dtype=np.int64)
    c2 = np.zeros((65536, 256), dtype=np.int32)
    n1 = np.zeros(256, dtype=np.int64)
    n2 = np.zeros(65536, dtype=np.int64)
    pred = Predictors(pred_ids) if (weight > 0 or adaptive) else None
    w = weight if weight > 0 else (0.0 if adaptive else 0.05)
    enc = RangeEncoder()
    buf = bytearray()
    for p, s in enumerate(data):
        if p >= 2:
            ctx = (data[p - 2] << 8) | data[p - 1]
        else:
            ctx = 0
        last = data[p - 1] if p >= 1 else 0
        n0 = p
        p0 = (c0 + 1.0) / (n0 + 256.0)
        p1 = (c1[last] + BETA * p0) / (n1[last] + BETA)
        p2 = (c2[ctx] + ALPHA * p1) / (n2[ctx] + ALPHA)
        base = p2
        q = None
        if pred is not None:
            h = ctx_hash(buf, p)
            preds, wts = pred.predict(buf, p, h)
            q = _candidate_dist(preds, wts)
            p2 = (1.0 - w) * base + w * q
        freq, cum = _freqs(p2)
        enc.encode(int(cum[s]), int(freq[s]))
        if pred is not None and adaptive:
            w = min(0.5, max(0.0, w + 0.02 * (q[s] - base[s]) / max(p2[s], 1e-9)))
        c0[s] += 1
        c1[last, s] += 1
        c2[ctx, s] += 1
        n1[last] += 1
        n2[ctx] += 1
        buf.append(s)
        if pred is not None:
            pred.update(preds, s)
            if p + 1 >= 8:
                pred.lzp[bytes(buf[p - 7:p + 1])] = p + 1
        if n2[ctx] > 1 << 20:
            c2[ctx] >>= 1
            n2[ctx] = int(c2[ctx].sum())
        if chunk_report and (p + 1) % chunk_report == 0:
            print("encoded", p + 1)
    blob = enc.finish()
    sec = time.perf_counter() - t0
    return blob, {"encode_s": sec, "bytes": len(blob), "bits_per_byte": len(blob) * 8 / max(1, n)}


def decode(blob: bytes, n: int, weight: float = 0.0, adaptive: bool = False, pred_ids=None) -> tuple[bytes, dict]:
    import time
    t0 = time.perf_counter()
    c0 = np.zeros(256, dtype=np.int64)
    c1 = np.zeros((256, 256), dtype=np.int64)
    c2 = np.zeros((65536, 256), dtype=np.int32)
    n1 = np.zeros(256, dtype=np.int64)
    n2 = np.zeros(65536, dtype=np.int64)
    pred = Predictors(pred_ids) if (weight > 0 or adaptive) else None
    w = weight if weight > 0 else (0.0 if adaptive else 0.05)
    dec = RangeDecoder(blob)
    out = bytearray()
    for p in range(n):
        if p >= 2:
            ctx = (out[p - 2] << 8) | out[p - 1]
        else:
            ctx = 0
        last = out[p - 1] if p >= 1 else 0
        p0 = (c0 + 1.0) / (p + 256.0)
        p1 = (c1[last] + BETA * p0) / (n1[last] + BETA)
        p2 = (c2[ctx] + ALPHA * p1) / (n2[ctx] + ALPHA)
        base = p2
        q = None
        if pred is not None:
            h = ctx_hash(out, p)
            preds, wts = pred.predict(out, p, h)
            q = _candidate_dist(preds, wts)
            p2 = (1.0 - w) * base + w * q
        freq, cum = _freqs(p2)
        target = dec.target()
        s = int(np.searchsorted(cum, target, side="right") - 1)
        dec.update(int(cum[s]), int(freq[s]))
        if pred is not None and adaptive:
            w = min(0.5, max(0.0, w + 0.02 * (q[s] - base[s]) / max(p2[s], 1e-9)))
        out.append(s)
        c0[s] += 1
        c1[last, s] += 1
        c2[ctx, s] += 1
        n1[last] += 1
        n2[ctx] += 1
        if pred is not None:
            pred.update(preds, s)
            if p + 1 >= 8:
                pred.lzp[bytes(out[p - 7:p + 1])] = p + 1
        if n2[ctx] > 1 << 20:
            c2[ctx] >>= 1
            n2[ctx] = int(c2[ctx].sum())
    return bytes(out), {"decode_s": time.perf_counter() - t0}
