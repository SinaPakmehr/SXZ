"""Small, honest numeric baselines: Gorilla-style, FPC-style, delta+Deflate.

These are not the official implementations; they are compact re-implementations
of the published encodings, included so numeric data has a domain reference.
"""

from __future__ import annotations

import struct
import zlib


class BitWriter:
    def __init__(self):
        self.out = bytearray()
        self.acc = self.n = 0

    def bit(self, value: int) -> None:
        self.acc = (self.acc << 1) | (value & 1)
        self.n += 1
        if self.n == 8:
            self.out.append(self.acc)
            self.acc = self.n = 0

    def bits(self, value: int, count: int) -> None:
        for shift in range(count - 1, -1, -1):
            self.bit((value >> shift) & 1)

    def finish(self) -> bytes:
        if self.n:
            self.out.append(self.acc << (8 - self.n))
        return bytes(self.out)


class BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def bit(self) -> int:
        index = self.pos
        if index >= len(self.data) * 8:
            raise ValueError("truncated bit stream")
        self.pos += 1
        return (self.data[index >> 3] >> (7 - (index & 7))) & 1

    def bits(self, count: int) -> int:
        value = 0
        for _ in range(count):
            value = (value << 1) | self.bit()
        return value


def _words(data: bytes, width: int = 8) -> list[int]:
    return [int.from_bytes(data[i : i + width], "big")
            for i in range(0, len(data) - len(data) % width, width)]


def gorilla_pack(data: bytes) -> bytes:
    words = _words(data)
    if not words:
        return struct.pack("<I", 0) + data
    writer = BitWriter()
    previous = words[0]
    writer.bits(previous, 64)
    for value in words[1:]:
        xor = value ^ previous
        if xor == 0:
            writer.bit(0)
        else:
            writer.bit(1)
            trailing = (xor & -xor).bit_length() - 1
            leading = min(64 - xor.bit_length(), 31)
            meaningful = 64 - leading - trailing
            writer.bits(leading, 5)
            writer.bits(meaningful - 1, 6)
            writer.bits(xor >> trailing, meaningful)
        previous = value
    tail = data[len(words) * 8 :]
    return struct.pack("<IHB", len(words), len(data) % 8, len(tail)) + tail + writer.finish()


def gorilla_unpack(blob: bytes) -> bytes:
    count, rest, tail_len = struct.unpack_from("<IHB", blob, 0)
    tail = blob[7 : 7 + tail_len]
    if count == 0:
        return tail
    reader = BitReader(blob[7 + tail_len:])
    out = bytearray()
    value = reader.bits(64)
    out += value.to_bytes(8, "big")
    for _ in range(count - 1):
        if reader.bit() == 0:
            value = value
        else:
            leading = reader.bits(5)
            meaningful = reader.bits(6) + 1
            payload = reader.bits(meaningful)
            value ^= payload << (64 - leading - meaningful)
        out += value.to_bytes(8, "big")
    return bytes(out[: count * 8]) + tail


def fpc_pack(data: bytes) -> bytes:
    words = _words(data)
    if not words:
        return struct.pack("<I", 0) + data
    writer = BitWriter()
    writer.bits(words[0], 64)
    if len(words) > 1:
        writer.bits(words[1], 64)
    for index in range(2, len(words)):
        prediction = (2 * words[index - 1] - words[index - 2]) & 0xFFFFFFFFFFFFFFFF
        xor = words[index] ^ prediction
        if xor == 0:
            writer.bits(0, 4)
            continue
        leading = (64 - xor.bit_length()) // 8
        remaining = 8 - leading
        writer.bits(remaining, 4)
        writer.bits(xor & ((1 << (8 * remaining)) - 1), 8 * remaining)
    tail = data[len(words) * 8 :]
    return struct.pack("<IHB", len(words), len(data) % 8, len(tail)) + tail + writer.finish()


def fpc_unpack(blob: bytes) -> bytes:
    count, rest, tail_len = struct.unpack_from("<IHB", blob, 0)
    tail = blob[7 : 7 + tail_len]
    if count == 0:
        return tail
    reader = BitReader(blob[7 + tail_len:])
    values = []
    if count >= 1:
        values.append(reader.bits(64))
    if count >= 2:
        values.append(reader.bits(64))
    for _ in range(2, count):
        remaining = reader.bits(4)
        if remaining == 0:
            values.append((2 * values[-1] - values[-2]) & 0xFFFFFFFFFFFFFFFF)
        else:
            payload = reader.bits(8 * remaining)
            prediction = (2 * values[-1] - values[-2]) & 0xFFFFFFFFFFFFFFFF
            values.append(prediction ^ payload)
    return b"".join(value.to_bytes(8, "big") for value in values) + tail


def delta_deflate_pack(data: bytes) -> bytes:
    words = _words(data)
    out = bytearray()
    previous = 0
    for value in words:
        delta = (value - previous) & 0xFFFFFFFFFFFFFFFF
        previous = value
        signed = delta - (1 << 64) if delta >= (1 << 63) else delta
        zigzag = (signed << 1) if signed >= 0 else ((-signed << 1) - 1)
        while True:
            byte = zigzag & 0x7F
            zigzag >>= 7
            out.append(byte | (0x80 if zigzag else 0))
            if not zigzag:
                break
    tail = data[len(words) * 8 :]
    return struct.pack("<IHB", len(words), len(data) % 8, len(tail)) + tail + zlib.compress(bytes(out), 9)


def delta_deflate_unpack(blob: bytes) -> bytes:
    count, rest, tail_len = struct.unpack_from("<IHB", blob, 0)
    tail = blob[7 : 7 + tail_len]
    payload = zlib.decompress(blob[7 + tail_len:])
    out = bytearray()
    pos = 0
    previous = 0
    for _ in range(count):
        shift = value = 0
        while True:
            byte = payload[pos]
            pos += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        signed = (value >> 1) if not value & 1 else -((value + 1) >> 1)
        previous = (previous + signed) & 0xFFFFFFFFFFFFFFFF
        out += previous.to_bytes(8, "big")
    return bytes(out) + tail
