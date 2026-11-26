"""Deterministic context hashing shared by the encoder analysis and decoder.

The context of byte position ``p`` is the sixteen preceding bytes (positions
p-16 .. p-1, missing positions read as zero) mixed with ``p`` itself using a
64-bit FNV-1a hash.  Both the vectorised analysis path and the scalar decoder
path must produce the identical hash; ``tests`` checks that property.
"""
from __future__ import annotations

import numpy as np

MASK64 = (1 << 64) - 1
GOLDEN = 0x9E3779B97F4A7C15
FNV_OFFSET = 14695981039346656037
FNV_PRIME = 1099511628211
CTX_BYTES = 16

# Stable family tags; never renumber after a stream has been frozen.
TAGS = {
    "sm64": 0x534D3634_00000001,
    "xs64": 0x58533634_00000002,
    "pcg32": 0x50434733_00000003,
    "lcg32": 0x4C434733_00000004,
    "rec8": 0x52454338_00000005,
    "const": 0x434F4E53_00000006,
    "golden": 0x474F4C44_00000007,
    "hashchain": 0x4843484E_00000008,
    "qr": 0x51554144_00000009,
    "fixedrand": 0x46584C52_0000000A,
    "window": 0x57494E44_0000000B,
    "lzp": 0x4C5A5031_0000000C,
    "fitted": 0x46495431_0000000D,
}


def splitmix64(x: int) -> int:
    x = (x + GOLDEN) & MASK64
    z = x
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return (z ^ (z >> 31)) & MASK64


def vsplitmix(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.uint64)
    with np.errstate(over="ignore"):
        x = x + np.uint64(GOLDEN)
        z = x.copy()
        z = (z ^ (z >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        z = (z ^ (z >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        z = z ^ (z >> np.uint64(31))
    return z


def ctx_hash(prefix: bytes, pos: int) -> int:
    h = FNV_OFFSET
    for k in range(CTX_BYTES, 0, -1):
        idx = pos - k
        b = prefix[idx] if idx >= 0 else 0
        h = ((h ^ b) * FNV_PRIME) & MASK64
    h = ((h ^ (pos & MASK64)) * FNV_PRIME) & MASK64
    return h


def ctx_hash_batch(data: np.ndarray, positions: np.ndarray) -> np.ndarray:
    pos = np.asarray(positions, dtype=np.int64)
    n = pos.size
    h = np.full(n, np.uint64(FNV_OFFSET), dtype=np.uint64)
    with np.errstate(over="ignore"):
        for k in range(CTX_BYTES, 0, -1):
            idx = pos - k
            valid = idx >= 0
            b = np.zeros(n, dtype=np.uint64)
            b[valid] = data[idx[valid]].astype(np.uint64)
            h = (h ^ b) * np.uint64(FNV_PRIME)
        h = (h ^ pos.astype(np.uint64)) * np.uint64(FNV_PRIME)
    return h


def stream_seed(h: int, family: str, variant: int) -> int:
    tag = TAGS[family]
    return splitmix64((h ^ tag ^ ((variant * GOLDEN) & MASK64)) & MASK64)


def vstream_seed(h: np.ndarray, family: str, variant: int) -> np.ndarray:
    tag = np.uint64(TAGS[family])
    with np.errstate(over="ignore"):
        x = h ^ tag ^ np.uint64((variant * GOLDEN) & MASK64)
    return vsplitmix(x)


class ContextTable:
    """Last grid position of each k-byte context, rebuilt from decoded bytes.

    The table deliberately advances over every ``stride`` grid point below the
    current position, independent of token boundaries, so encoder and decoder
    agree even when a token skips grid points.
    """

    def __init__(self, ks=(4, 8, 12, 16), stride: int = 8):
        self.ks = tuple(ks)
        self.stride = stride
        self.tables = {k: {} for k in self.ks}
        self.next = 0

    def advance(self, buf, pos: int) -> None:
        p = self.next
        while p < pos:
            if p >= max(self.ks):
                for k in self.ks:
                    self.tables[k][bytes(buf[p - k:p])] = p
            p += self.stride
        self.next = p

    def lookup(self, buf, pos: int, k: int) -> int:
        self.advance(buf, pos)
        if pos < k:
            return -1
        return self.tables[k].get(bytes(buf[pos - k:pos]), -1)


def lzp_offsets(data: np.ndarray, positions: np.ndarray, ks=(4, 8, 12, 16), stride: int = 8):
    """Offsets of the previous occurrence of each context, one array per k.

    Mirrors ``ContextTable.advance``: only grid positions strictly below the
    query position are inserted, and ties keep the most recent occurrence.
    """
    pos = np.asarray(positions, dtype=np.int64)
    out = {k: np.full(pos.size, -1, dtype=np.int64) for k in ks}
    tables = {k: {} for k in ks}
    cursor = 0
    for i, p in enumerate(pos.tolist()):
        while cursor < p:
            if cursor >= max(ks):
                for k in ks:
                    tables[k][bytes(data[cursor - k:cursor])] = cursor
            cursor += stride
        for k in ks:
            if p >= k:
                out[k][i] = tables[k].get(bytes(data[p - k:p]), -1)
    return out
