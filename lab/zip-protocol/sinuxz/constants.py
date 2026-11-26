"""Bounded, reproducible reference streams for the experimental model.

Each reference is the first 4096 fractional digits in base 10 (ASCII) or
base 256 (one byte per digit, most significant first). No floating point,
external digit tables, or platform-dependent rounding enters the format.
"""

from functools import lru_cache
from math import isqrt
from typing import Iterator

from .native_scan import candidate_offsets

REFERENCE_SIZE = 4096
OFFSET_BITS = 12
ANCHOR = 8
REFERENCE_NAMES = ("pi/decimal", "pi/base256", "e/decimal", "e/base256", "phi/decimal", "phi/base256")


def _atan_inverse(x: int, scale: int) -> tuple[int, int]:
    """Fixed-point approximation to atan(1/x), with an absolute error bound."""
    power = scale // x
    total = n = 0
    sign = 1
    while power:
        total += sign * (power // (2 * n + 1))
        power //= x * x
        sign = -sign
        n += 1
    # Each integer division loses <1 unit per term; the alternating tail <1.
    return total, n + 1


def _fraction_floor(which: int, scale: int) -> int:
    if which == 2:
        # floor(scale * (sqrt(5) - 1) / 2)
        return (isqrt(5 * scale * scale) - scale) // 2
    guard = 32
    while True:
        big = scale << guard
        if which == 0:
            a, ea = _atan_inverse(5, big)
            b, eb = _atan_inverse(239, big)
            value, error = 16 * a - 4 * b - 3 * big, 16 * ea + 4 * eb
        else:
            # e - 2 = sum(1/k!, k >= 2). First omitted term <1 unit;
            # the sum of that term and the rest of the tail is <2 units.
            q, k, value = big // 2, 2, 0
            while q:
                value += q
                k += 1
                q //= k
            error = k
        low, high = (value - error) >> guard, (value + error) >> guard
        if low == high:
            return low
        guard *= 2


@lru_cache(maxsize=len(REFERENCE_NAMES))
def reference(mode: int) -> bytes:
    if not 0 <= mode < len(REFERENCE_NAMES):
        raise ValueError("unknown constant encoding")
    if mode & 1:
        value = _fraction_floor(mode // 2, 1 << (8 * REFERENCE_SIZE))
        return value.to_bytes(REFERENCE_SIZE, "big")

    value = _fraction_floor(mode // 2, 10 ** REFERENCE_SIZE)
    # Convert in groups to avoid depending on Python's int-to-string limit.
    groups = []
    for _ in range((REFERENCE_SIZE + 7) // 8):
        value, group = divmod(value, 10 ** 8)
        groups.append(f"{group:08d}")
    return "".join(reversed(groups))[-REFERENCE_SIZE:].encode("ascii")


@lru_cache(maxsize=1)
def _anchors() -> dict[bytes, list[tuple[int, int]]]:
    result: dict[bytes, list[tuple[int, int]]] = {}
    for mode in range(len(REFERENCE_NAMES)):
        stream = reference(mode)
        for start in range(len(stream) - ANCHOR + 1):
            result.setdefault(stream[start : start + ANCHOR], []).append((mode, start))
    return result


def find_reference(
    data: bytes, start: int, end: int, minimum: int,
) -> tuple[int, tuple[int, int]] | None:
    """Find the longest verified reference match beginning at ``start``."""
    minimum = max(ANCHOR, minimum)
    if end - start < minimum:
        return None
    positions = _anchors().get(data[start : start + ANCHOR])
    return _match(data, start, end, minimum, positions) if positions else None


def reference_hits(
    data: bytes, start: int, stop: int, max_span: int, minimum: int,
) -> Iterator[tuple[int, int, tuple[int, int]]]:
    """Find verified starts in [start, stop), using one cached lookup per byte."""
    minimum = max(ANCHOR, minimum)
    if max_span < minimum:
        return
    stop = min(stop, len(data) - minimum + 1)
    if stop <= start:
        return
    lookup = _anchors().get
    positions_to_check = candidate_offsets(data, start, stop)
    for pos in range(start, stop) if positions_to_check is None else positions_to_check:
        positions = lookup(data[pos : pos + ANCHOR])
        if positions:
            end = min(pos + max_span, len(data))
            match = _match(data, pos, end, minimum, positions)
            if match:
                yield pos, *match


def _match(
    data: bytes, start: int, end: int, minimum: int, positions: list[tuple[int, int]],
) -> tuple[int, tuple[int, int]] | None:
    best = None
    best_length = minimum - 1
    for mode, offset in positions:
        limit = min(end - start, REFERENCE_SIZE - offset)
        stream = reference(mode)
        if limit <= best_length or not data.startswith(stream[offset : offset + best_length + 1], start, end):
            continue
        length = best_length + 1
        while length < limit and data[start + length] == stream[offset + length]:
            length += 1
        best_length = length
        best = length, (mode, offset)
    return best
