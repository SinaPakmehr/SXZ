"""Minimal serialized model records.

The record is intentionally byte-aligned and self-contained.  It is not an
entropy-coded archive format; its size is the measured model-description cost
used in the Episode 1 economics.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .inference import bm_generate, poly_predict
from .representations import Representation, rep_from_id, rep_id

MAGIC = b"AM"
VERSION = 1
HEADER = struct.Struct("<2sBBBBBBII")  # magic, ver, family, rep, flags, order, align, start, count

FAMILY_IDS = {
    "const": 1,
    "periodic": 2,
    "poly1": 3,
    "poly2": 4,
    "poly3": 5,
    "affine1": 6,
    "affine2": 7,
    "bm": 8,
}
ID_FAMILIES = {value: key for key, value in FAMILY_IDS.items()}

FLAG_BITPLANE = 1
FLAG_EXACT = 2
FLAG_HIGH_ORDER = 4
FLAG_ALIGNMENT_PASS = 8


@dataclass(frozen=True)
class ModelRecord:
    family: str
    rep: Representation
    align: int
    start: int
    count: int
    order: int
    params: tuple
    flags: int = FLAG_EXACT

    @property
    def is_bitplane(self) -> bool:
        return self.rep.is_bit

    def payload(self) -> bytes:
        rep = self.rep
        width = rep.width
        if self.family == "const":
            value = int(self.params[0])
            return bytes([value & 1]) if rep.is_bit else value.to_bytes(width, "little")
        if self.family == "periodic":
            pattern = self.params[0]
            if rep.is_bit:
                array = np.asarray(pattern, dtype=np.uint8)
                return np.packbits(array, bitorder="big").tobytes()
            return b"".join(int(value).to_bytes(width, "little") for value in pattern)
        if self.family.startswith("poly"):
            return b"".join(int(value).to_bytes(width, "little") for value in self.params)
        if self.family == "affine1":
            return b"".join(int(value).to_bytes(width, "little") for value in self.params)
        if self.family == "affine2":
            return b"".join(int(value).to_bytes(width, "little") for value in self.params)
        if self.family == "bm":
            taps, seed = self.params
            length = (self.order + 7) // 8
            return int(taps).to_bytes(length, "little") + int(seed).to_bytes(length, "little")
        raise ValueError(f"unknown family {self.family}")

    def to_bytes(self) -> bytes:
        family = FAMILY_IDS[self.family]
        flags = self.flags
        if self.is_bitplane:
            flags |= FLAG_BITPLANE
        header = HEADER.pack(
            MAGIC,
            VERSION,
            family,
            rep_id(self.rep),
            flags,
            self.order,
            self.align,
            self.start,
            self.count,
        )
        return header + self.payload()

    def __len__(self) -> int:
        return len(self.to_bytes())

    @classmethod
    def from_bytes(cls, blob: bytes) -> "ModelRecord":
        if len(blob) < HEADER.size:
            raise ValueError("record shorter than header")
        magic, version, family_id, rep_value, flags, order, align, start, count = HEADER.unpack_from(blob)
        if magic != MAGIC:
            raise ValueError("bad record magic")
        if version != VERSION:
            raise ValueError(f"unsupported record version {version}")
        if family_id not in ID_FAMILIES:
            raise ValueError(f"unknown family id {family_id}")
        family = ID_FAMILIES[family_id]
        rep = rep_from_id(rep_value)
        if count <= 0:
            raise ValueError("record count must be positive")
        if rep.is_word:
            if not 0 <= align < rep.width:
                raise ValueError("invalid word alignment")
        elif align != 0:
            raise ValueError("bit-plane record must have alignment zero")
        body = blob[HEADER.size :]
        params, expected = _decode_payload(family, rep, order, body)
        if expected != len(body):
            raise ValueError("record has trailing or missing payload bytes")
        return cls(family, rep, align, start, count, order, params, flags)

    def reconstruct_symbols(self) -> list[int]:
        if self.family == "const":
            return [int(self.params[0])] * self.count
        if self.family == "periodic":
            pattern = [int(value) for value in self.params[0]]
            if not pattern:
                raise ValueError("empty periodic pattern")
            return [pattern[index % len(pattern)] for index in range(self.count)]
        if self.family.startswith("poly"):
            return poly_predict(self.params, self.count, self.rep.sym_bits)
        if self.family == "affine1":
            a, c, x0 = (int(value) for value in self.params)
            mask = self.rep.mask
            out = [x0 & mask]
            for _ in range(1, self.count):
                out.append((a * out[-1] + c) & mask)
            return out
        if self.family == "affine2":
            a, b, c, x0, x1 = (int(value) for value in self.params)
            mask = self.rep.mask
            out = [x0 & mask, x1 & mask]
            while len(out) < self.count:
                out.append((a * out[-1] + b * out[-2] + c) & mask)
            return out[: self.count]
        if self.family == "bm":
            taps, seed = self.params
            bits = bm_generate(_bits_from_int(seed, self.order), int(taps), self.order, self.count)
            return [int(bit) & 1 for bit in bits]
        raise ValueError(f"cannot reconstruct family {self.family}")


def _decode_payload(family: str, rep: Representation, order: int, body: bytes):
    width = rep.width
    if family == "const":
        if rep.is_bit:
            need = 1
            if len(body) < need:
                raise ValueError("short const payload")
            return (body[0] & 1,), need
        need = width
        if len(body) < need:
            raise ValueError("short const payload")
        return (int.from_bytes(body[:need], "little"),), need

    if family == "periodic":
        if order < 2 or order > 64:
            raise ValueError("invalid period")
        if rep.is_bit:
            need = (order + 7) // 8
            if len(body) < need:
                raise ValueError("short periodic payload")
            bits = np.unpackbits(np.frombuffer(body[:need], dtype=np.uint8), bitorder="big")[:order]
            return (tuple(int(value) for value in bits),), need
        need = order * width
        if len(body) < need:
            raise ValueError("short periodic payload")
        pattern = tuple(
            int.from_bytes(body[index : index + width], "little")
            for index in range(0, need, width)
        )
        return (pattern,), need

    if family.startswith("poly"):
        expected_order = int(family[-1])
        if order != expected_order:
            raise ValueError("poly order mismatch")
        if rep.is_bit:
            raise ValueError("bit-plane polynomial records are not supported")
        need = (order + 1) * width
        if len(body) < need:
            raise ValueError("short polynomial payload")
        values = tuple(
            int.from_bytes(body[index : index + width], "little")
            for index in range(0, need, width)
        )
        return values, need

    if family == "affine1":
        if rep.is_bit:
            raise ValueError("bit-plane affine records are not supported")
        need = 3 * width
        if len(body) < need:
            raise ValueError("short affine1 payload")
        values = tuple(
            int.from_bytes(body[index : index + width], "little")
            for index in range(0, need, width)
        )
        return values, need

    if family == "affine2":
        if rep.is_bit:
            raise ValueError("bit-plane affine records are not supported")
        need = 5 * width
        if len(body) < need:
            raise ValueError("short affine2 payload")
        values = tuple(
            int.from_bytes(body[index : index + width], "little")
            for index in range(0, need, width)
        )
        return values, need

    if family == "bm":
        if not rep.is_bit:
            raise ValueError("BM records require a bit-plane representation")
        if order <= 0 or order > 64:
            raise ValueError("invalid BM order")
        need = 2 * ((order + 7) // 8)
        if len(body) < need:
            raise ValueError("short BM payload")
        length = (order + 7) // 8
        taps = int.from_bytes(body[:length], "little")
        seed = int.from_bytes(body[length:need], "little")
        return (taps, seed), need

    raise ValueError(f"unknown family {family}")


def _bits_from_int(value: int, count: int) -> list[int]:
    return [(int(value) >> index) & 1 for index in range(count)]


def seed_to_int(bits: Iterable[int]) -> int:
    out = 0
    for index, bit in enumerate(bits):
        out |= (int(bit) & 1) << index
    return out


def reconstruct_record_bytes(record: ModelRecord, original: bytes) -> bytes:
    """Reconstruct exactly the bytes covered by a word record."""
    if record.is_bitplane:
        raise ValueError("bit-plane records do not reconstruct whole bytes")
    symbols = record.reconstruct_symbols()
    rep = record.rep
    begin = record.align + record.start * rep.width
    end = begin + record.count * rep.width
    if end > len(original):
        raise ValueError("record extends beyond the original data")
    return b"".join(int(value).to_bytes(rep.width, rep.order) for value in symbols)


def record_information_bits(record: ModelRecord) -> int:
    """Approximate information content of the payload, in bits."""
    if record.family == "const":
        return record.rep.sym_bits
    if record.family == "periodic":
        return record.rep.sym_bits * record.order
    if record.family.startswith("poly"):
        return record.rep.sym_bits * (record.order + 1)
    if record.family == "affine1":
        return 3 * record.rep.sym_bits
    if record.family == "affine2":
        return 5 * record.rep.sym_bits
    if record.family == "bm":
        return 2 * record.order
    return 0
