"""Direct algebraic inference for AMRD Episode 1.

The routines here are deliberately small and deterministic:

* finite differences up to order three,
* first-order affine recurrences ``x[n] = a*x[n-1] + c``,
* second-order affine recurrences ``x[n] = a*x[n-1] + b*x[n-2] + c``,
* Berlekamp-Massey over GF(2).

No routine searches a coefficient grid.  Coefficients come from equations,
modular inverses, or the BM update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .config import AFFINE_BUDGET, PERIOD_MAX, POLY_MAX_ORDER


@dataclass(frozen=True)
class Candidate:
    family: str
    shape: tuple
    start: int
    window: int
    order: int
    fit_len: int
    val_len: int


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def all_equal(values) -> bool:
    array = np.asarray(values)
    return array.size == 0 or bool(np.all(array == array[0]))


def bit_v2(value: int) -> int:
    """2-adic valuation of a positive integer."""
    value = int(value)
    if value == 0:
        return 0
    return (value & -value).bit_length() - 1


def poly_predict(initials: Iterable[int], n: int, bits: int) -> list[int]:
    """Generate ``n`` symbols from initial finite differences.

    ``initials`` is ``[X[0], D1[0], D2[0], ...]``.  Reconstruction is repeated
    modular addition; no floating point is used.
    """
    mask = (1 << bits) - 1
    levels = [int(value) & mask for value in initials]
    if n <= 0:
        return []
    if not levels:
        return [0] * n
    out = [levels[0]]
    while len(out) < n:
        for index in range(len(levels) - 1):
            levels[index] = (levels[index] + levels[index + 1]) & mask
        out.append(levels[0])
    return out


def poly_initials(train: np.ndarray, order: int, bits: int) -> list[int]:
    mask = (1 << bits) - 1
    values = [int(train[0])]
    current = train.copy()
    for _ in range(order):
        current = (current[1:] - current[:-1]) & mask
        values.append(int(current[0]))
    return values


def _periodic_shape(train: np.ndarray, val: np.ndarray) -> tuple | None:
    if train.size < 4 or all_equal(train):
        return None
    maximum = min(PERIOD_MAX, train.size // 2)
    first = int(train[0])
    for period in range(2, maximum + 1):
        # Cheap necessary condition; rejects most random periods at one byte.
        if int(train[period]) != first:
            continue
        if not np.array_equal(train[period:], train[:-period]):
            continue
        pattern = train[:period]
        phase = train.size % period
        repeats = (phase + val.size) // period + 1
        val_tile = np.tile(pattern, repeats)[phase : phase + val.size]
        if np.array_equal(val, val_tile):
            return (period, tuple(int(value) for value in pattern))
    return None


# ---------------------------------------------------------------------------
# Word detectors
# ---------------------------------------------------------------------------
def detect_const(train: np.ndarray, val: np.ndarray) -> tuple | None:
    if all_equal(train) and all_equal(val) and int(train[0]) == int(val[0]):
        return (int(train[0]),)
    return None


def detect_periodic(train: np.ndarray, val: np.ndarray) -> tuple | None:
    return _periodic_shape(train, val)


def detect_poly(train: np.ndarray, val: np.ndarray, bits: int) -> tuple | None:
    """Return ``(family, shape)`` for a constant finite difference."""
    mask = (1 << bits) - 1
    if train.size < 2 or all_equal(train):
        return None

    d1 = (train[1:] - train[:-1]) & mask
    if all_equal(d1):
        if int(d1[0]) != 0:
            initials = [int(train[0]), int(d1[0])]
            if _poly_matches(initials, train, val, bits):
                return "poly1", (int(d1[0]),)
        return None

    if d1.size < 2:
        return None
    d2 = (d1[1:] - d1[:-1]) & mask
    if all_equal(d2) and int(d2[0]) != 0:
        initials = [int(train[0]), int(d1[0]), int(d2[0])]
        if _poly_matches(initials, train, val, bits):
            return "poly2", (int(d1[0]), int(d2[0]))

    if d2.size < 2:
        return None
    d3 = (d2[1:] - d2[:-1]) & mask
    if all_equal(d3) and int(d3[0]) != 0 and POLY_MAX_ORDER >= 3:
        initials = [int(train[0]), int(d1[0]), int(d2[0]), int(d3[0])]
        if _poly_matches(initials, train, val, bits):
            return "poly3", (int(d1[0]), int(d2[0]), int(d3[0]))
    return None


def _poly_matches(initials: list[int], train: np.ndarray, val: np.ndarray, bits: int) -> bool:
    predicted = poly_predict(initials, train.size + val.size, bits)
    return (
        np.array_equal(np.asarray(predicted[: train.size], dtype=np.uint64), train)
        and np.array_equal(
            np.asarray(predicted[train.size :], dtype=np.uint64), val
        )
    )


def detect_affine1(
    train: np.ndarray, val: np.ndarray, bits: int, stats: dict
) -> tuple | None:
    """Infer ``x[n] = a*x[n-1] + c`` from differences.

    ``D[n] = a*D[n-1]``.  A common power of two is removed from all
    differences before taking the inverse; this is exact and lets the method
    handle differences that are all even.  If the reduced difference sequence
    still has no odd entry, the window is left unresolved.
    """
    mask = (1 << bits) - 1
    mod = 1 << bits
    if train.size < 3:
        return None
    differences = (train[1:] - train[:-1]) & mask
    nonzero = differences[differences != 0]
    if nonzero.size == 0:
        return None
    stats["affine1_windows"] = stats.get("affine1_windows", 0) + 1

    valuation = min(bit_v2(int(value)) for value in nonzero)
    if valuation:
        stats["affine1_even_diff_windows"] = stats.get("affine1_even_diff_windows", 0) + 1
    reduced = differences >> valuation
    odd_positions = np.flatnonzero((reduced & 1) == 1)
    stats["affine1_odd_pairs"] = stats.get("affine1_odd_pairs", 0) + int(odd_positions.size)
    if odd_positions.size == 0:
        stats["affine1_unresolved"] = stats.get("affine1_unresolved", 0) + 1
        return None

    tried = 0
    for position in odd_positions[:AFFINE_BUDGET]:
        position = int(position)
        if position + 1 >= reduced.size:
            continue
        tried += 1
        a = (int(reduced[position + 1]) * pow(int(reduced[position]), -1, mod)) & mask
        if a == 1:
            continue  # arithmetic progression; poly1 owns this case
        c = (int(train[1]) - a * int(train[0])) & mask
        if not _affine1_matches(train, a, c, mask):
            continue
        if not _affine1_matches(val, a, c, mask, seed=int(train[-1])):
            continue
        if all_equal(val):
            stats["affine1_degenerate_tail"] = stats.get("affine1_degenerate_tail", 0) + 1
            continue
        stats["affine1_solved"] = stats.get("affine1_solved", 0) + 1
        stats["affine1_attempts"] = stats.get("affine1_attempts", 0) + tried
        return a, c

    stats["affine1_attempts"] = stats.get("affine1_attempts", 0) + tried
    stats["affine1_unresolved"] = stats.get("affine1_unresolved", 0) + 1
    return None


def _affine1_matches(values: np.ndarray, a: int, c: int, mask: int, seed: int | None = None) -> bool:
    if values.size == 0:
        return True
    current = int(values[0]) if seed is None else seed
    begin = 0 if seed is None else 0
    if seed is None:
        begin = 1
    for index in range(begin, values.size):
        current = (a * current + c) & mask
        if current != int(values[index]):
            return False
    return True


def _solve2_odd(
    m00: int, m01: int, m10: int, m11: int, r0: int, r1: int, mod: int
) -> tuple[int, int] | None:
    determinant = (m00 * m11 - m01 * m10) % mod
    if determinant % 2 == 0:
        return None
    inverse = pow(determinant, -1, mod)
    a = ((r0 * m11 - m01 * r1) * inverse) % mod
    b = ((m00 * r1 - r0 * m10) * inverse) % mod
    return a, b


def detect_affine2(
    train: np.ndarray, val: np.ndarray, bits: int, stats: dict
) -> tuple | None:
    """Infer ``x[n] = a*x[n-1] + b*x[n-2] + c`` from the difference system."""
    mask = (1 << bits) - 1
    mod = 1 << bits
    if train.size < 6:
        return None
    differences = [int(value) for value in ((train[1:] - train[:-1]) & mask)]
    if len(differences) < 5:
        return None
    first = differences[0]
    if all(value == first for value in differences):
        return None

    stats["affine2_windows"] = stats.get("affine2_windows", 0) + 1
    nmax = len(differences) - 2
    if nmax < 2:
        return None
    positions = np.unique(
        np.linspace(2, nmax, min(AFFINE_BUDGET, nmax - 1), dtype=int)
    )
    singular = 0
    tried = 0
    for position in positions:
        n = int(position)
        m00, m01 = differences[n - 1], differences[n - 2]
        m10, m11 = differences[n], differences[n - 1]
        r0, r1 = differences[n], differences[n + 1]
        solution = _solve2_odd(m00, m01, m10, m11, r0, r1, mod)
        tried += 1
        if solution is None:
            singular += 1
            continue
        a, b = solution
        if b == 0:
            continue  # first-order case; affine1 owns it
        c = (int(train[2]) - a * int(train[1]) - b * int(train[0])) & mask
        if not _affine2_matches(train, a, b, c, mask):
            continue
        if not _affine2_matches(val, a, b, c, mask, seed=(int(train[-2]), int(train[-1]))):
            continue
        if all_equal(val):
            stats["affine2_degenerate_tail"] = stats.get("affine2_degenerate_tail", 0) + 1
            continue
        stats["affine2_singular_systems"] = stats.get("affine2_singular_systems", 0) + singular
        stats["affine2_attempts"] = stats.get("affine2_attempts", 0) + tried
        stats["affine2_solved"] = stats.get("affine2_solved", 0) + 1
        return a, b, c

    stats["affine2_singular_systems"] = stats.get("affine2_singular_systems", 0) + singular
    stats["affine2_attempts"] = stats.get("affine2_attempts", 0) + tried
    if singular == tried:
        stats["affine2_all_singular_windows"] = stats.get("affine2_all_singular_windows", 0) + 1
    stats["affine2_unresolved"] = stats.get("affine2_unresolved", 0) + 1
    return None


def _affine2_matches(
    values: np.ndarray,
    a: int,
    b: int,
    c: int,
    mask: int,
    seed: tuple[int, int] | None = None,
) -> bool:
    if values.size == 0:
        return True
    if seed is None:
        previous2, previous1 = int(values[0]), int(values[1])
        begin = 2
    else:
        previous2, previous1 = seed
        begin = 0
    for index in range(begin, values.size):
        current = (a * previous1 + b * previous2 + c) & mask
        if current != int(values[index]):
            return False
        previous2, previous1 = previous1, current
    return True


# ---------------------------------------------------------------------------
# Berlekamp-Massey over GF(2)
# ---------------------------------------------------------------------------
def bm_fit(bits: Iterable[int], max_order: int = 64) -> tuple[int, int]:
    """Return ``(order, taps)`` for the shortest binary linear recurrence.

    ``taps`` bit ``j-1`` is the coefficient of ``s[n-j]``.
    """
    polynomial = 1
    previous = 1
    order = 0
    shift = 1
    history = 0
    for index, raw in enumerate(bits):
        bit = int(raw) & 1
        history = (history << 1) | bit
        if (polynomial & history).bit_count() % 2 == 0:
            shift += 1
            continue
        old = polynomial
        polynomial ^= previous << shift
        if 2 * order <= index:
            order = index + 1 - order
            previous = old
            shift = 1
        else:
            shift += 1
        if order > max_order:
            return order, 0
    taps = 0
    for j in range(1, order + 1):
        if (polynomial >> j) & 1:
            taps |= 1 << (j - 1)
    return order, taps


def bm_generate(seed: Iterable[int], taps: int, order: int, n: int) -> list[int]:
    """Generate ``n`` bits from a recurrence and the first ``order`` bits."""
    if n <= 0:
        return []
    if order == 0:
        return [0] * n
    seed_list = [int(value) & 1 for value in seed]
    if len(seed_list) < order:
        raise ValueError("BM seed shorter than recurrence order")
    state = 0
    for index in range(order):
        state |= (seed_list[order - 1 - index] & 1) << index
    state_mask = (1 << order) - 1
    out = seed_list[:order]
    while len(out) < n:
        bit = (state & taps).bit_count() & 1
        out.append(bit)
        state = ((state << 1) | bit) & state_mask
    return out[:n]


def detect_bm(
    train: np.ndarray, val: np.ndarray, stats: dict, max_order: int = 64
) -> tuple | None:
    if train.size < 8:
        return None
    stats["bm_windows"] = stats.get("bm_windows", 0) + 1
    order, taps = bm_fit(train.tolist(), max_order=max_order)
    if order == 0:
        return None
    if order > max_order or order > train.size:
        return None
    if order == 1 and taps == 1:
        return None  # constant, owned by the constant detector
    generated = bm_generate(train[-order:], taps, order, order + val.size)
    predicted = generated[order:]
    if predicted != [int(value) for value in val]:
        return None
    if all_equal(val):
        stats["bm_degenerate_tail"] = stats.get("bm_degenerate_tail", 0) + 1
        return None
    if order > train.size // 2:
        stats["bm_high_order"] = stats.get("bm_high_order", 0) + 1
    stats["bm_solved"] = stats.get("bm_solved", 0) + 1
    return order, taps


# ---------------------------------------------------------------------------
# Window dispatch
# ---------------------------------------------------------------------------
def detect_word_window(
    symbols: np.ndarray, start: int, window: int, bits: int, stats: dict
) -> Candidate | None:
    half = window // 2
    train = symbols[start : start + half]
    val = symbols[start + half : start + window]
    fit_len, val_len = half, window - half
    stats["windows_word"] = stats.get("windows_word", 0) + 1

    shape = detect_const(train, val)
    if shape is not None:
        stats["const"] = stats.get("const", 0) + 1
        return Candidate("const", shape, start, window, 0, fit_len, val_len)

    shape = detect_periodic(train, val)
    if shape is not None:
        stats["periodic"] = stats.get("periodic", 0) + 1
        return Candidate("periodic", shape, start, window, int(shape[0]), fit_len, val_len)

    poly = detect_poly(train, val, bits)
    if poly is not None:
        family, shape = poly
        stats[family] = stats.get(family, 0) + 1
        order = int(family[-1])
        return Candidate(family, shape, start, window, order, fit_len, val_len)

    shape = detect_affine1(train, val, bits, stats)
    if shape is not None:
        stats["affine1"] = stats.get("affine1", 0) + 1
        return Candidate("affine1", shape, start, window, 1, fit_len, val_len)

    shape = detect_affine2(train, val, bits, stats)
    if shape is not None:
        stats["affine2"] = stats.get("affine2", 0) + 1
        return Candidate("affine2", shape, start, window, 2, fit_len, val_len)
    return None


def detect_bit_window(
    bits: np.ndarray, start: int, window: int, stats: dict, max_order: int = 64
) -> Candidate | None:
    half = window // 2
    train = bits[start : start + half]
    val = bits[start + half : start + window]
    fit_len, val_len = half, window - half
    stats["windows_bit"] = stats.get("windows_bit", 0) + 1

    shape = detect_const(train, val)
    if shape is not None:
        stats["const"] = stats.get("const", 0) + 1
        return Candidate("const", shape, start, window, 0, fit_len, val_len)

    shape = _periodic_shape(train, val)
    if shape is not None:
        stats["periodic"] = stats.get("periodic", 0) + 1
        return Candidate("periodic", shape, start, window, int(shape[0]), fit_len, val_len)

    bm = detect_bm(train, val, stats, max_order=max_order)
    if bm is not None:
        order, taps = bm
        stats["bm"] = stats.get("bm", 0) + 1
        return Candidate("bm", (order, taps), start, window, order, fit_len, val_len)
    return None
