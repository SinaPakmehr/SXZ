"""Reversible byte transforms tried before formula fitting.

A formula often only becomes visible after a simple derivative, e.g. an
incrementing byte counter ``00 01 02 03 ...`` turns into ``00 01 01 01 ...``
under a delta transform, which the constant/period model can describe with a
handful of bits.

All transforms are length preserving and byte aligned so segment boundaries
never move.
"""

from __future__ import annotations


class Transform:
    tid: int
    name: str

    def forward(self, data: bytes) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError

    def inverse(self, data: bytes) -> bytes:  # pragma: no cover - interface
        raise NotImplementedError


class Identity(Transform):
    tid = 0
    name = "identity"

    def forward(self, data: bytes) -> bytes:
        return data

    def inverse(self, data: bytes) -> bytes:
        return data


class XorPrevious(Transform):
    tid = 1
    name = "xor-prev"

    def forward(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        prev = 0
        for i, byte in enumerate(data):
            out[i] = byte ^ prev
            prev = byte
        return bytes(out)

    def inverse(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        prev = 0
        for i, byte in enumerate(data):
            byte ^= prev
            out[i] = byte
            prev = byte
        return bytes(out)


class Delta(Transform):
    tid = 2
    name = "delta"

    def forward(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        prev = 0
        for i, byte in enumerate(data):
            out[i] = (byte - prev) & 0xFF
            prev = byte
        return bytes(out)

    def inverse(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        prev = 0
        for i, byte in enumerate(data):
            prev = (prev + byte) & 0xFF
            out[i] = prev
        return bytes(out)


class XorStride(Transform):
    """XOR each byte with the byte ``stride`` positions back.

    Exposes interleaved structures such as 16 bit samples where the high and
    low bytes follow separate sequences.
    """

    tid = 3
    name = "xor-stride2"

    def forward(self, data: bytes) -> bytes:
        out = bytearray(data)
        for i in range(len(data) - 1, 1, -1):
            out[i] ^= data[i - 2]
        return bytes(out)

    def inverse(self, data: bytes) -> bytes:
        out = bytearray(data)
        for i in range(2, len(out)):
            out[i] ^= out[i - 2]
        return bytes(out)


TRANSFORMS: list[Transform] = [
    Identity(),
    XorPrevious(),
    Delta(),
    XorStride(),
]

BY_ID = {t.tid: t for t in TRANSFORMS}
