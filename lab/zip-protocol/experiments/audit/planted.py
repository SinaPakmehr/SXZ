"""Deterministic planted-pattern corpus with ground truth.

Every case is a random background with one known byte pattern inserted at a
known offset.  The manifest is the answer key: a detector either recovers the
planted span or it does not, and partial coverage is measurable.
"""

from __future__ import annotations

import random
import struct
from dataclasses import dataclass, field

from sinuxz.constants import reference
from sinuxz.models import _xorshift_step


@dataclass
class Case:
    name: str
    data: bytes
    start: int
    length: int
    family: str
    expected: bool          # should the current model bank be able to express it
    note: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def end(self) -> int:
        return self.start + self.length


def _background(rng: random.Random, n: int) -> bytes:
    return bytes(rng.getrandbits(8) for _ in range(n))


def affine_u8(n: int, step: int = 1, start: int = 0) -> bytes:
    return bytes((start + i * step) & 0xFF for i in range(n))


def affine_word(n: int, width: int, order: str, step: int = 1, start: int = 0) -> bytes:
    mask = (1 << (8 * width)) - 1
    return b"".join(((start + i * step) & mask).to_bytes(width, order) for i in range(n // width))


def quadratic_word(n: int, width: int, order: str, d1: int = 1, d2: int = 3) -> bytes:
    mask = (1 << (8 * width)) - 1
    out, value, delta = bytearray(), 0, d1
    for _ in range(n // width):
        out += value.to_bytes(width, order)
        value = (value + delta) & mask
        delta = (delta + d2) & mask
    return bytes(out)


def lfsr_bytes(n: int, taps: int = 0xB400, degree: int = 16, seed: int = 0xACE1) -> bytes:
    """Maximal-length Fibonacci LFSR, bits packed MSB first."""
    state, mask, bits = seed, (1 << degree) - 1, []
    for _ in range(n * 8):
        bit = state & 1
        bits.append(bit)
        fb = (state & taps).bit_count() & 1
        state = (state >> 1) | (fb << (degree - 1))
        state &= mask
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for bit in bits[i : i + 8]:
            byte = (byte << 1) | bit
        out.append(byte)
    return bytes(out)


def xorshift_bytes(n: int, seed: int = 0x12345678, order: str = "big") -> bytes:
    out, state = bytearray(), seed
    while len(out) < n:
        state = _xorshift_step(state)
        out += state.to_bytes(4, order)
    return bytes(out[:n])


def float_ramp(n: int) -> bytes:
    out = bytearray()
    value = 1.0
    while len(out) < n:
        out += struct.pack("<f", value)
        value *= 1.0000001
    return bytes(out[:n])


def timestamp_u64(n: int, step_us: int = 1000) -> bytes:
    out = bytearray()
    base = 1_700_000_000_000_000
    for i in range(n // 8):
        out += struct.pack("<Q", base + i * step_us)
    return bytes(out)


def stereo_u16(n: int) -> bytes:
    left = affine_word(n // 4, 2, "little", step=3, start=100)
    right = affine_word(n // 4, 2, "little", step=7, start=90_000)
    out = bytearray()
    for i in range(0, len(left), 2):
        out += left[i : i + 2] + right[i : i + 2]
    return bytes(out[:n])


def add_noise(pattern: bytes, fraction: float, rng: random.Random) -> bytes:
    out = bytearray(pattern)
    for i in range(len(out)):
        if rng.random() < fraction:
            out[i] ^= 1 << rng.randrange(8)
    return bytes(out)


def build(background_size: int = 16384, pattern_size: int = 4096, seed: int = 20261125) -> list[Case]:
    rng = random.Random(seed)
    cases: list[Case] = []

    def add(name: str, pattern: bytes, alignment: int, family: str, expected: bool,
            note: str = "", meta: dict | None = None) -> None:
        head = _background(rng, alignment)
        tail = _background(rng, max(0, background_size - alignment - len(pattern)))
        cases.append(Case(name, head + pattern + tail, alignment, len(pattern), family,
                          expected, note, meta or {}))

    add("affine-u8-step1", affine_u8(pattern_size), 0, "affine", True, "byte counter from 0")
    add("affine-u8-step7-offset13", affine_u8(pattern_size, 7, 3), 13, "affine", True, "unaligned start")
    add("affine-u16le", affine_word(pattern_size, 2, "little", 5, 1000), 0, "affine", True,
        "little-endian words")
    add("affine-u16be", affine_word(pattern_size, 2, "big", 5, 1000), 0, "affine", True)
    add("affine-u32le", affine_word(pattern_size, 4, "little", 17, 7), 0, "affine", True)
    add("affine-u32be", affine_word(pattern_size, 4, "big", 17, 7), 0, "affine", True)
    add("affine-u64le", affine_word(pattern_size, 8, "little", 1, 0), 0, "affine", False,
        "WIDTHS stops at 32 bits")
    add("quadratic-u16le", quadratic_word(pattern_size, 2, "little"), 0, "quadratic", True,
        "needs experimental_models")
    add("quadratic-u32be", quadratic_word(pattern_size, 4, "big"), 1, "quadratic", True,
        "odd byte phase, needs experimental_models")
    add("lfsr-16", lfsr_bytes(pattern_size), 0, "lfsr", True)
    add("xorshift32-be", xorshift_bytes(pattern_size, order="big"), 0, "xorshift", True)
    add("xorshift32-le", xorshift_bytes(pattern_size, order="little"), 0, "xorshift", True)
    add("period-3", b"abc" * (pattern_size // 3), 0, "period", True)
    add("constant-aa", b"\xaa" * pattern_size, 0, "constant", True)
    add("pi-decimal-0", reference(0)[:pattern_size], 0, "reference", True,
        "needs experimental_models")
    add("pi-base256-600", reference(1)[600 : 600 + pattern_size], 5, "reference", True,
        "unaligned, needs experimental_models")
    add("float-ramp", float_ramp(pattern_size), 0, "float", False, "no float model")
    add("timestamp-u64us", timestamp_u64(pattern_size), 0, "timestamp", False,
        "64-bit LE, no model")
    add("stereo-u16le", stereo_u16(pattern_size), 0, "multichannel", False,
        "needs a stride transform; only xor-stride2 exists")

    base = affine_word(pattern_size, 2, "little", 3, 500)
    for fraction in (0.001, 0.01, 0.05, 0.20):
        add(f"affine-u16le-noise-{fraction:g}", add_noise(base, fraction, rng), 0,
            "noisy", False, "exact match required; any flip breaks the run")

    # Two independent ramps added byte-wise: expressible only as a sum of models.
    left = affine_word(pattern_size, 2, "little", 3, 100)
    right = affine_word(pattern_size, 2, "little", 5, 7)
    composite = bytes((a + b) & 0xFF for a, b in zip(left, right))
    add("composite-sum-u16le", composite, 0, "composite", False,
        "no model composes two sequences")

    return cases


def boundary_cases(frame: int = 65536) -> list[Case]:
    """Patterns that start just before a frame boundary and continue past it."""
    rng = random.Random(7)
    pattern = affine_word(8192, 2, "little", 3, 0)
    align = frame - 300
    data = _background(rng, align) + pattern + _background(rng, frame - len(pattern) + 4096)
    crossing = Case("cross-frame-affine-u16le", data, align, len(pattern), "crossing", True,
                    f"starts 300 bytes before a {frame}-byte frame boundary")
    pi = reference(0)[:8192]
    data2 = _background(rng, frame - 100) + pi + _background(rng, frame)
    crossing_pi = Case("cross-frame-pi", data2, frame - 100, len(pi), "crossing", True,
                       "reference slice crosses a frame boundary")
    return [crossing, crossing_pi]
