"""Numerical representations used by AMRD Episode 1.

Only byte-aligned representations are implemented.  A representation is a
view of the original bytes; it never changes the bytes that are reconstructed.

Word values are held in ``uint64`` arrays.  For widths below eight bytes every
operation is masked with ``(1 << (8*width)) - 1`` so Python/numpy wrapping is
explicit.  For ``u64`` the hardware/numpy wrap is already modulo 2**64.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Representation:
    name: str
    kind: str          # "word" or "bit"
    width: int         # bytes per word; 0 for a bit plane
    order: str         # "little", "big", or "" for bits
    bit: int           # 0..7 for a bit plane, -1 for a word
    sym_bits: int      # bits per numerical symbol

    @property
    def is_word(self) -> bool:
        return self.kind == "word"

    @property
    def is_bit(self) -> bool:
        return self.kind == "bit"

    @property
    def mask(self) -> int:
        if self.is_bit:
            return 1
        return (1 << (8 * self.width)) - 1

    @property
    def mod(self) -> int:
        return 1 << self.sym_bits


WORD_REPRESENTATIONS = (
    Representation("u8", "word", 1, "little", -1, 8),
    Representation("u16le", "word", 2, "little", -1, 16),
    Representation("u16be", "word", 2, "big", -1, 16),
    Representation("u32le", "word", 4, "little", -1, 32),
    Representation("u32be", "word", 4, "big", -1, 32),
    Representation("u64le", "word", 8, "little", -1, 64),
    Representation("u64be", "word", 8, "big", -1, 64),
)

BIT_REPRESENTATIONS = tuple(
    Representation(f"bit{bit}", "bit", 0, "", bit, 1) for bit in range(8)
)

ALL_REPRESENTATIONS = WORD_REPRESENTATIONS + BIT_REPRESENTATIONS
REP_BY_NAME = {rep.name: rep for rep in ALL_REPRESENTATIONS}
REP_NAMES = tuple(rep.name for rep in ALL_REPRESENTATIONS)


def rep_id(rep: Representation) -> int:
    return REP_NAMES.index(rep.name)


def rep_from_id(value: int) -> Representation:
    if not 0 <= value < len(REP_NAMES):
        raise ValueError(f"unknown representation id {value}")
    return REP_BY_NAME[REP_NAMES[value]]


def extract_symbols(data: bytes, rep: Representation, align: int = 0) -> np.ndarray:
    """Return the numerical sequence for ``rep`` at byte offset ``align``.

    For a bit plane the result has one symbol per source byte (eight symbols per
    input byte), in bit-index order within each byte.  ``bit0`` is the least
    significant bit of each byte.
    """
    if rep.is_bit:
        raw = np.frombuffer(data, dtype=np.uint8)
        return ((raw >> rep.bit) & 1).astype(np.uint8)

    width = rep.width
    if not 0 <= align < width:
        raise ValueError(f"alignment {align} outside u{8*width} word")
    count = (len(data) - align) // width
    if count <= 0:
        return np.empty(0, dtype=np.uint64)
    raw = np.frombuffer(data, dtype=np.uint8, count=count * width, offset=align)
    raw = raw.reshape(count, width)
    if width == 1:
        return raw[:, 0].astype(np.uint64)
    out = np.zeros(count, dtype=np.uint64)
    if rep.order == "little":
        for column in range(width):
            out |= raw[:, column].astype(np.uint64) << (8 * column)
    else:
        for column in range(width):
            out |= raw[:, column].astype(np.uint64) << (8 * (width - 1 - column))
    return out


def pack_symbols(values, rep: Representation) -> bytes:
    """Pack numerical symbols back to their original byte representation."""
    array = np.asarray(values, dtype=np.uint64)
    if rep.is_bit:
        return np.packbits(array.astype(np.uint8), bitorder="big").tobytes()
    if rep.width == 1:
        return array.astype(np.uint8).tobytes()
    out = bytearray()
    order = rep.order
    width = rep.width
    for value in array:
        out += int(value).to_bytes(width, order)
    return bytes(out)


def span_bytes(rep: Representation, count: int) -> int:
    if rep.is_bit:
        return (count + 7) // 8
    return count * rep.width


def symbol_byte_span(rep: Representation, align: int, start: int, count: int) -> tuple[int, int]:
    """Absolute byte interval covered by a word model."""
    if rep.is_bit:
        raise ValueError("bit-plane spans are not byte intervals")
    begin = align + start * rep.width
    return begin, begin + count * rep.width
