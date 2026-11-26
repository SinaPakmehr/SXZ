"""SXZ4 reversible representations.

A representation is a byte permutation plus a tiny metadata blob.  Nothing is
approximated: every transform has an exact inverse, and the metadata is counted
in the archive.  The engine tries a screened subset and keeps the one with the
smallest real output.
"""

from __future__ import annotations

import struct

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


class Transform:
    tid = -1
    name = "?"

    def forward(self, data: bytes) -> tuple[bytes, bytes]:
        raise NotImplementedError

    def inverse(self, data: bytes, meta: bytes) -> bytes:
        raise NotImplementedError


class Identity(Transform):
    tid = 0
    name = "identity"

    def forward(self, data):
        return data, b""

    def inverse(self, data, meta):
        return data


class Delta(Transform):
    """Byte or word difference in place; the tail shorter than one word stays."""

    def __init__(self, width: int, tid: int, name: str, order: str = "little"):
        self.width, self.tid, self.name, self.order = width, tid, name, order

    def forward(self, data: bytes) -> tuple[bytes, bytes]:
        w = self.width
        out = bytearray(data)
        body = len(data) - len(data) % w
        if w == 1:
            prev = 0
            for i in range(body):
                current = data[i]
                out[i] = (current - prev) & 0xFF
                prev = current
        else:
            mask = (1 << (8 * w)) - 1
            prev = 0
            for i in range(0, body, w):
                current = int.from_bytes(data[i : i + w], self.order)
                out[i : i + w] = ((current - prev) & mask).to_bytes(w, self.order)
                prev = current
        return bytes(out), bytes([len(data) % w])

    def inverse(self, data: bytes, meta: bytes) -> bytes:
        w = self.width
        out = bytearray(data)
        body = len(data) - len(data) % w
        if w == 1:
            prev = 0
            for i in range(body):
                prev = (prev + data[i]) & 0xFF
                out[i] = prev
        else:
            mask = (1 << (8 * w)) - 1
            prev = 0
            for i in range(0, body, w):
                prev = (prev + int.from_bytes(data[i : i + w], self.order)) & mask
                out[i : i + w] = prev.to_bytes(w, self.order)
        return bytes(out)


class Shuffle(Transform):
    """Deinterleave bytes with a stride: all first bytes, then all second..."""

    def __init__(self, stride: int, tid: int, order: bytes | None = None):
        self.stride, self.tid = stride, tid
        self.order = order or bytes(range(stride))
        self.name = f"shuffle{stride}" + ("" if order is None else "-f32")

    def forward(self, data: bytes) -> tuple[bytes, bytes]:
        s = self.stride
        body = len(data) - len(data) % s
        out = bytearray()
        for plane in self.order:
            out += data[plane:body:s]
        out += data[body:]
        return bytes(out), bytes([len(data) % s])

    def inverse(self, data: bytes, meta: bytes) -> bytes:
        s = self.stride
        rest = meta[0] if meta else 0
        body = len(data) - rest
        count = body // s
        out = bytearray(len(data))
        pos = 0
        for plane in self.order:
            out[plane:body:s] = data[pos : pos + count]
            pos += count
        out[body:] = data[body:]
        return bytes(out)


class BitPlanes(Transform):
    tid = 20
    name = "bitplanes8"

    def forward(self, data: bytes) -> tuple[bytes, bytes]:
        n = len(data)
        out = bytearray()
        for bit in range(7, -1, -1):
            acc = 0
            count = 0
            plane = bytearray()
            for byte in data:
                acc = (acc << 1) | ((byte >> bit) & 1)
                count += 1
                if count == 8:
                    plane.append(acc)
                    acc = count = 0
            if count:
                plane.append(acc << (8 - count))
            out += plane
        return bytes(out), varint(n)

    def inverse(self, data: bytes, meta: bytes) -> bytes:
        n, _ = read_varint(meta, 0)
        size = (n + 7) // 8
        out = bytearray(n)
        for index, bit in enumerate(range(7, -1, -1)):
            plane = data[index * size : (index + 1) * size]
            for i in range(n):
                value = (plane[i >> 3] >> (7 - (i & 7))) & 1
                out[i] |= value << bit
        return bytes(out)


class CsvColumns(Transform):
    """Transpose a uniform, unquoted CSV/TSV file into column streams.

    Fields may not contain the delimiter or a newline and may not be empty; the
    original line ending and trailing newline are stored in the metadata, so the
    inverse reproduces the file byte for byte.
    """

    tid = 21
    name = "csv-columns"

    @staticmethod
    def _analyse(data: bytes):
        eol = b"\r\n" if b"\r\n" in data[:4096] else b"\n"
        text = data
        trailing = text.endswith(eol)
        if trailing:
            text = text[: -len(eol)]
        lines = text.split(eol)
        if len(lines) < 4:
            return None
        delimiter = None
        for candidate in (b",", b";", b"\t", b"|"):
            if all(candidate in line for line in lines[:32]):
                delimiter = candidate
                break
        if delimiter is None:
            return None
        rows = [line.split(delimiter) for line in lines]
        count = len(rows[0])
        if count < 2 or any(len(row) != count for row in rows):
            return None
        if any(not field for row in rows for field in row):
            return None
        if any(len(field) == 0 for row in rows for field in row):
            return None
        return delimiter, eol, rows, trailing

    def forward(self, data: bytes) -> tuple[bytes, bytes]:
        found = self._analyse(data)
        if found is None:
            raise ValueError("not a uniform CSV")
        delimiter, eol, rows, trailing = found
        ncols, nrows = len(rows[0]), len(rows)
        out = bytearray()
        for col in range(ncols):
            out += b"\n".join(row[col] for row in rows)
            out += b"\n"
        meta = bytes([delimiter[0], 1 if eol == b"\n" else 2, 1 if trailing else 0])
        meta += varint(ncols) + varint(nrows)
        return bytes(out), meta

    def inverse(self, data: bytes, meta: bytes) -> bytes:
        delimiter = bytes([meta[0]])
        eol = b"\n" if meta[1] == 1 else b"\r\n"
        trailing = meta[2] == 1
        ncols, pos = read_varint(meta, 3)
        nrows, pos = read_varint(meta, pos)
        columns = []
        offset = 0
        for _ in range(ncols):
            fields = []
            for _ in range(nrows):
                end = data.find(b"\n", offset)
                if end < 0:
                    raise ValueError("column length mismatch")
                fields.append(data[offset:end])
                offset = end + 1
            columns.append(fields)
        if offset != len(data):
            raise ValueError("unexpected CSV bytes")
        lines = [delimiter.join(columns[col][row] for col in range(ncols)) for row in range(nrows)]
        out = eol.join(lines)
        if trailing:
            out += eol
        return out


TRANSFORMS: dict[int, Transform] = {
    0: Identity(),
    1: Delta(1, 1, "delta1"),
    2: Delta(2, 2, "delta2le"),
    3: Delta(4, 3, "delta4le"),
    4: Delta(8, 4, "delta8le"),
    5: Shuffle(2, 5),
    6: Shuffle(3, 6),
    7: Shuffle(4, 7),
    8: Shuffle(8, 8),
    9: Shuffle(4, 9, bytes([3, 2, 1, 0])),
    10: Shuffle(16, 10),
    11: Delta(2, 11, "delta2be", "big"),
    12: Delta(4, 12, "delta4be", "big"),
    13: Delta(8, 13, "delta8be", "big"),
    20: BitPlanes(),
    21: CsvColumns(),
}

# Chains are applied left to right; the inverse runs in reverse order.
CHAINS: list[tuple[int, ...]] = [(0,)]
for tid in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 20):
    CHAINS.append((tid,))
for shuffle_id in (5, 6, 7, 8, 9, 10):
    for delta_id in (1, 2, 3, 4, 11, 12, 13):
        CHAINS.append((shuffle_id, delta_id))
CHAINS.append((21,))
CHAINS.append((21, 2))


def apply_chain(data: bytes, chain: tuple[int, ...]) -> tuple[bytes, list[bytes]]:
    metas = []
    for tid in chain:
        data, meta = TRANSFORMS[tid].forward(data)
        metas.append(meta)
    return data, metas


def invert_chain(data: bytes, chain: tuple[int, ...], metas: list[bytes]) -> bytes:
    for tid, meta in zip(reversed(chain), reversed(metas)):
        data = TRANSFORMS[tid].inverse(data, meta)
    return data


def encode_chain(chain: tuple[int, ...], metas: list[bytes]) -> bytes:
    out = bytearray([len(chain)])
    out += bytes(chain)
    for meta in metas:
        out += varint(len(meta)) + meta
    return bytes(out)


def decode_chain(blob: bytes) -> tuple[tuple[int, ...], list[bytes], int]:
    count = blob[0]
    chain = tuple(blob[1 : 1 + count])
    pos = 1 + count
    metas = []
    for _ in chain:
        length, pos = read_varint(blob, pos)
        metas.append(blob[pos : pos + length])
        pos += length
    return chain, metas, pos


def screen(data: bytes, sample: int = 32768) -> list[tuple[int, tuple[int, ...]]]:
    """Rank chains by Deflate size of a sample; the engine then packs top ones."""
    import zlib

    head = data[:sample]
    scored = []
    for chain in CHAINS:
        try:
            transformed, _ = apply_chain(head, chain)
        except Exception:
            continue
        scored.append((len(zlib.compress(transformed, 6)), chain))
    scored.sort()
    return [(size, chain) for size, chain in scored]
