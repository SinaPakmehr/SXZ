"""Residual channels for SXZ3.

The engine never assumes a model is exact.  Given a prediction it measures
four representations and keeps the cheapest:

0. exact       - no residual bytes
1. xor         - actual XOR predicted, Deflate-compressed
2. moddiff     - (actual - predicted) mod 256, Deflate-compressed
3. exceptions  - delta-coded positions and literal values, Deflate-compressed

Every payload is stored Deflate-compressed, and every payload carries the
information needed to decompress it independently.  The caller adds one mode
byte and one varint length.
"""

from __future__ import annotations

import zlib

EXACT, XOR, MODDIFF, EXCEPTIONS = 0, 1, 2, 3
NAMES = ("exact", "xor", "moddiff", "exceptions")


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


def encode_exceptions(pred: bytes, actual: bytes) -> bytes:
    out = bytearray()
    previous = count = 0
    for index, (p, a) in enumerate(zip(pred, actual)):
        if p != a:
            out += varint(index - previous)
            out.append(a)
            previous = index
            count += 1
    return varint(count) + bytes(out)


def decode_exceptions(pred: bytearray, blob: bytes) -> None:
    count, pos = read_varint(blob, 0)
    index = 0
    for _ in range(count):
        delta, pos = read_varint(blob, pos)
        if pos >= len(blob):
            raise ValueError("truncated exception")
        index += delta
        if index >= len(pred):
            raise ValueError("exception outside block")
        pred[index] = blob[pos]
        pos += 1


def best(pred: bytes, actual: bytes, level: int = 6) -> tuple[int, bytes, int]:
    """Return (mode, payload, stored_cost) for the cheapest representation."""
    if pred == actual:
        return EXACT, b"", 1
    xor = bytes(a ^ p for p, a in zip(pred, actual))
    diff = bytes((a - p) & 0xFF for p, a in zip(pred, actual))
    exceptions = encode_exceptions(pred, actual)
    options = [
        (XOR, zlib.compress(xor, level)),
        (MODDIFF, zlib.compress(diff, level)),
        # The decoder needs the uncompressed exception length.
        (EXCEPTIONS, varint(len(exceptions)) + zlib.compress(exceptions, level)),
    ]
    mode, payload = min(options, key=lambda item: len(item[1]))
    return mode, payload, 1 + len(varint(len(payload))) + len(payload)


def apply(pred: bytes, mode: int, payload: bytes) -> bytes:
    if mode == EXACT:
        return pred
    if mode == XOR:
        residual = zlib.decompress(payload)
        if len(residual) != len(pred):
            raise ValueError("xor residual size mismatch")
        return bytes(p ^ r for p, r in zip(pred, residual))
    if mode == MODDIFF:
        residual = zlib.decompress(payload)
        if len(residual) != len(pred):
            raise ValueError("moddiff residual size mismatch")
        return bytes((p + r) & 0xFF for p, r in zip(pred, residual))
    if mode == EXCEPTIONS:
        size, pos = read_varint(payload, 0)
        blob = zlib.decompress(payload[pos:])
        if len(blob) != size:
            raise ValueError("exception blob size mismatch")
        out = bytearray(pred)
        decode_exceptions(out, blob)
        return bytes(out)
    raise ValueError(f"unknown residual mode {mode}")
