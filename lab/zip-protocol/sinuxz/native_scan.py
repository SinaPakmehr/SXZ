"""Opt-in loader for a locally built anchor accelerator. No runtime dependency."""

from __future__ import annotations

import ctypes as C
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterator


@lru_cache(maxsize=1)
def _load():
    path = os.environ.get("SINUXZ_SCAN_DLL")
    if not path:
        return None
    library = C.CDLL(str(Path(path).resolve(strict=True)))
    library.sxz_anchor_abi.argtypes = []
    library.sxz_anchor_abi.restype = C.c_uint32
    if library.sxz_anchor_abi() != 1:
        raise ValueError("unsupported SXZ native scanner ABI")
    scan = library.sxz_anchor_scan
    scan.argtypes = [
        C.c_char_p, C.c_size_t, C.c_size_t, C.c_size_t, C.POINTER(C.c_uint64), C.c_size_t,
        C.POINTER(C.c_size_t), C.c_size_t,
    ]
    scan.restype = C.c_size_t
    return scan


@lru_cache(maxsize=1)
def _lookup_table(keys: tuple[bytes, ...]):
    slots = 1 << (max(1, len(keys) * 2) - 1).bit_length()
    table = (C.c_uint64 * slots)()
    mask = slots - 1
    for raw in keys:
        key = int.from_bytes(raw, "little")
        if not key:
            return None
        mixed = ((key ^ (key >> 33)) * 0xFF51AFD7ED558CCD) & ((1 << 64) - 1)
        index = (mixed ^ (mixed >> 33)) & mask
        while table[index]:
            index = (index + 1) & mask
        table[index] = key
    return table


@lru_cache(maxsize=1)
def _native_table():
    from .constants import _anchors

    return _lookup_table(tuple(_anchors()))


def candidate_offsets(data: bytes, start: int, stop: int) -> Iterator[int] | None:
    # Leave small ranges in Python where the ctypes call overhead dominates.
    if start < 0 or stop - start < 512:
        return None
    scan = _load()
    if scan is None:
        return None
    table = _native_table()
    if table is None:
        return None

    def offsets() -> Iterator[int]:
        position = start
        hits = (C.c_size_t * 128)()
        while position < stop:
            count = scan(data, len(data), position, stop, table, len(table), hits, len(hits))
            for i in range(count):
                yield hits[i]
            if count < len(hits):
                break
            position = hits[count - 1] + 1

    return offsets()
