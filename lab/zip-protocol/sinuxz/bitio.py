"""Bit-level I/O helpers (MSB-first).

Everything the container stores about formula parameters is bit packed, so a
model can be described with e.g. ``6 + 2*L`` bits instead of whole bytes.
"""

from __future__ import annotations

from itertools import islice
from typing import Iterable, Sequence


class BitWriter:
    """Accumulate bits MSB-first and flush them as bytes."""

    __slots__ = ("_out", "_cur", "_n", "bit_length")

    def __init__(self) -> None:
        self._out = bytearray()
        self._cur = 0
        self._n = 0
        self.bit_length = 0

    def write_bit(self, bit: int) -> None:
        self._cur = (self._cur << 1) | (bit & 1)
        self._n += 1
        self.bit_length += 1
        if self._n == 8:
            self._out.append(self._cur)
            self._cur = 0
            self._n = 0

    def write(self, value: int, nbits: int) -> None:
        if nbits <= 0:
            return
        if value < 0 or value >> nbits:
            raise ValueError(f"value {value} does not fit in {nbits} bits")
        for shift in range(nbits - 1, -1, -1):
            self.write_bit((value >> shift) & 1)

    def write_bitstring(self, bits: str) -> None:
        for ch in bits:
            self.write_bit(1 if ch == "1" else 0)

    def write_bytes(self, data: bytes) -> None:
        """Byte aligned fast path; only valid right after a byte boundary."""
        if self._n:
            for byte in data:
                self.write(byte, 8)
            return
        self._out.extend(data)
        self.bit_length += len(data) * 8

    def to_bytes(self) -> bytes:
        """Return padded bytes. Padding bits are zero and not counted."""
        if self._n:
            return bytes(self._out) + bytes([self._cur << (8 - self._n)])
        return bytes(self._out)

    def __len__(self) -> int:
        return self.bit_length


class BitReader:
    """Read bits MSB-first from a byte buffer."""

    __slots__ = ("data", "pos", "limit")

    def __init__(self, data: bytes, bit_length: int | None = None) -> None:
        self.data = data
        self.pos = 0
        self.limit = len(data) * 8 if bit_length is None else bit_length

    def read_bit(self) -> int:
        if self.pos >= self.limit:
            raise EOFError("bit reader exhausted")
        byte = self.data[self.pos >> 3]
        bit = (byte >> (7 - (self.pos & 7))) & 1
        self.pos += 1
        return bit

    def read(self, nbits: int) -> int:
        value = 0
        for _ in range(nbits):
            value = (value << 1) | self.read_bit()
        return value

    def read_bytes(self, nbytes: int) -> bytes:
        out = bytearray()
        for _ in range(nbytes):
            out.append(self.read(8))
        return bytes(out)

    def remaining(self) -> int:
        return self.limit - self.pos


# ---------------------------------------------------------------------------
# bytes <-> bit list helpers
# ---------------------------------------------------------------------------

_BYTE_TO_BITS = [[(b >> s) & 1 for s in range(7, -1, -1)] for b in range(256)]


def bytes_to_bits(data: bytes, nbits: int | None = None) -> list[int]:
    out: list[int] = []
    for byte in data:
        out.extend(_BYTE_TO_BITS[byte])
    if nbits is not None:
        del out[nbits:]
    return out


def bits_to_bytes(bits: Iterable[int], nbits: int | None = None) -> bytes:
    out = bytearray()
    cur = 0
    n = 0
    for bit in bits if nbits is None else islice(bits, nbits):
        cur = (cur << 1) | (bit & 1)
        n += 1
        if n == 8:
            out.append(cur)
            cur = 0
            n = 0
    if n:
        out.append(cur << (8 - n))
    return bytes(out)


def int_to_bits(value: int, nbits: int) -> list[int]:
    return [(value >> s) & 1 for s in range(nbits - 1, -1, -1)]


def bits_to_int(bits: Sequence[int], start: int = 0, nbits: int | None = None) -> int:
    end = len(bits) if nbits is None else start + nbits
    value = 0
    for i in range(start, end):
        value = (value << 1) | bits[i]
    return value
