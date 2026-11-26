"""Formula bank: parametric sequence generators searched per segment.

Every model can (a) inspect a bit string and propose a few parameter sets,
(b) emit the parameter set as a handful of bits, and (c) regenerate the bit
stream deterministically.  The container only stores the parameters.

The important one is :class:`LfsrModel`: Berlekamp-Massey gives the shortest
linear recurrence over GF(2) that reproduces the observed prefix, which is a
genuine "extract the formula" step rather than a dictionary trick.
"""

from __future__ import annotations

from itertools import islice, repeat
from typing import Iterator, Sequence

from .bitio import BitReader, BitWriter, bits_to_bytes, bits_to_int, int_to_bits
from .constants import OFFSET_BITS, REFERENCE_NAMES, REFERENCE_SIZE, reference

Params = tuple


class Model:
    mid: int = 0
    name: str = "?"

    # -- fitting -----------------------------------------------------------
    def fit(self, bits: Sequence[int]) -> list[Params]:
        """Return candidate parameter tuples for this bit prefix."""
        raise NotImplementedError

    # -- serialisation -----------------------------------------------------
    def encode(self, w: BitWriter, params: Params) -> None:
        raise NotImplementedError

    def decode(self, r: BitReader) -> Params:
        raise NotImplementedError

    def bit_length(self, params: Params) -> int:
        """Number of bits :meth:`encode` will write for ``params``."""
        raise NotImplementedError

    # -- generation --------------------------------------------------------
    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        raise NotImplementedError

    def describe(self, params: Params) -> str:
        return self.name

    def match(self, params: Params, bits: Sequence[int]) -> int:
        """Length of the longest matching prefix in bits."""
        n = len(bits)
        i = 0
        for bit in self.gen(params, n):
            if bit != bits[i]:
                return i
            i += 1
            if i >= n:
                break
        return i


# ---------------------------------------------------------------------------
# 1. constant
# ---------------------------------------------------------------------------
class ConstantModel(Model):
    mid = 1
    name = "const"

    def fit(self, bits: Sequence[int]) -> list[Params]:
        return [(0,), (1,)]

    def encode(self, w: BitWriter, params: Params) -> None:
        w.write(params[0], 1)

    def decode(self, r: BitReader) -> Params:
        return (r.read_bit(),)

    def bit_length(self, params: Params) -> int:
        return 1

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        return repeat(params[0], nbits)


# ---------------------------------------------------------------------------
# 2. period
# ---------------------------------------------------------------------------
class PeriodModel(Model):
    mid = 2
    name = "period"
    MAX_PERIOD = 128

    def fit(self, bits: Sequence[int]) -> list[Params]:
        sample = min(len(bits), 512)
        s = "".join("1" if b else "0" for b in bits[:sample])
        # The pattern must repeat at least twice inside the sample, otherwise
        # "period == sample length" would trivially match every bit string.
        for p in range(1, min(self.MAX_PERIOD, sample // 2) + 1):
            if s[p:] == s[:-p]:
                pattern = bits_to_int(bits, 0, p)
                return [(p, pattern)]
        return []

    def encode(self, w: BitWriter, params: Params) -> None:
        p, pattern = params
        w.write(p, 8)
        w.write(pattern, p)

    def decode(self, r: BitReader) -> Params:
        p = r.read(8)
        if not 1 <= p <= self.MAX_PERIOD:
            raise ValueError("invalid period")
        return (p, r.read(p))

    def bit_length(self, params: Params) -> int:
        return 8 + params[0]

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        p, pattern = params
        bits = int_to_bits(pattern, p)
        for i in range(nbits):
            yield bits[i % p]


# ---------------------------------------------------------------------------
# 3. affine progression (counters, arithmetic progressions)
# ---------------------------------------------------------------------------
WIDTHS = (4, 8, 12, 16, 24, 32)


class AffineModel(Model):
    """Chunks of ``w`` bits with ``x_i = (a + i*d) mod 2**w``."""

    mid = 3
    name = "affine"

    def fit(self, bits: Sequence[int]) -> list[Params]:
        out: list[Params] = []
        n = len(bits)
        for wi, w in enumerate(WIDTHS):
            if n < 3 * w:
                continue
            x0 = bits_to_int(bits, 0, w)
            x1 = bits_to_int(bits, w, w)
            x2 = bits_to_int(bits, 2 * w, w)
            mask = (1 << w) - 1
            d = (x1 - x0) & mask
            if (x0 + 2 * d) & mask != x2:
                continue
            out.append((wi, w, x0, d))
        return out

    def encode(self, w: BitWriter, params: Params) -> None:
        wi, width, a, d = params
        w.write(wi, 3)
        w.write(a, width)
        w.write(d, width)

    def decode(self, r: BitReader) -> Params:
        wi = r.read(3)
        if wi >= len(WIDTHS):
            raise ValueError("unknown affine word width")
        width = WIDTHS[wi]
        a = r.read(width)
        d = r.read(width)
        return (wi, width, a, d)

    def bit_length(self, params: Params) -> int:
        return 3 + 2 * params[1]

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        _, width, a, d = params
        mask = (1 << width) - 1
        produced = 0
        i = 0
        while produced < nbits:
            value = (a + i * d) & mask
            for bit in int_to_bits(value, width):
                if produced >= nbits:
                    return
                yield bit
                produced += 1
            i += 1


# ---------------------------------------------------------------------------
# 4. LFSR via Berlekamp-Massey
# ---------------------------------------------------------------------------
def berlekamp_massey(bits: Sequence[int]) -> tuple[list[int], int]:
    """Shortest LFSR over GF(2) generating ``bits``.

    Returns ``(C, L)`` where ``s[i] = XOR(C[j] * s[i-j] for j in 1..L)``.
    """
    # Bit j holds C[j] and the j-th most recent observation respectively.
    C = B = 1
    L = history = 0
    m = 1
    for i, bit in enumerate(bits):
        history = (history << 1) | bit
        if (C & history).bit_count() % 2 == 0:
            m += 1
            continue
        old = C
        C ^= B << m
        if 2 * L <= i:
            L = i + 1 - L
            B = old
            m = 1
        else:
            m += 1
    return int_to_bits(C, L + 1)[::-1], L


class LfsrModel(Model):
    mid = 4
    name = "lfsr"

    MAX_DEGREE = 48
    SAMPLE = 160

    def fit(self, bits: Sequence[int]) -> list[Params]:
        n = len(bits)
        if n < 32:
            return []
        sample = min(n, self.SAMPLE)
        C, L = berlekamp_massey(bits[:sample])
        if L < 2 or L > self.MAX_DEGREE or L >= sample // 3:
            return []
        taps = 0
        for j in range(1, L + 1):
            if j < len(C) and C[j]:
                taps |= 1 << (j - 1)
        seed = bits_to_int(bits, 0, L)
        params = (L, taps, seed)
        # BM is exact for the whole sample when enough terms were seen; verify.
        if self.match(params, bits[:sample]) != sample:
            return []
        return [params]

    def encode(self, w: BitWriter, params: Params) -> None:
        L, taps, seed = params
        w.write(L, 6)
        w.write(taps, L)
        w.write(seed, L)

    def decode(self, r: BitReader) -> Params:
        L = r.read(6)
        if not 2 <= L <= self.MAX_DEGREE:
            raise ValueError("invalid LFSR degree")
        taps = r.read(L)
        seed = r.read(L)
        return (L, taps, seed)

    def bit_length(self, params: Params) -> int:
        return 6 + 2 * params[0]

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        L, taps, seed = params
        mask = (1 << L) - 1
        for j in range(L):
            if j >= nbits:
                return
            yield (seed >> (L - 1 - j)) & 1
        state = seed
        for _ in range(L, nbits):
            feedback = (state & taps).bit_count() & 1
            yield feedback
            state = ((state << 1) | feedback) & mask


# ---------------------------------------------------------------------------
# 5. xorshift32
# ---------------------------------------------------------------------------
M32 = 0xFFFFFFFF


def _xorshift_step(x: int) -> int:
    x ^= (x << 13) & M32
    x ^= x >> 17
    x ^= (x << 5) & M32
    return x & M32


def _invert_left_shift(y: int, shift: int) -> int:
    """Invert ``y = x ^ (x << shift)`` over 32 bits."""
    x = y
    k = shift
    while k < 32:
        x ^= (y << k) & M32
        k += shift
    return x & M32


def _xorshift_unstep(y: int) -> int:
    # undo x ^= x << 5, then x ^= x >> 17, then x ^= x << 13
    y = _invert_left_shift(y, 5)
    y ^= y >> 17
    y = _invert_left_shift(y, 13)
    return y & M32


class XorShiftModel(Model):
    mid = 5
    name = "xorshift32"

    def fit(self, bits: Sequence[int]) -> list[Params]:
        if len(bits) < 64:
            return []
        out: list[Params] = []
        first4 = bytes(bits_to_int(bits, 8 * i, 8) for i in range(4))
        for mode, raw in ((0, first4), (1, first4[::-1])):
            word = int.from_bytes(raw, "big")
            seed = _xorshift_unstep(word)
            if _xorshift_step(seed) != word:
                continue
            params = (seed, mode)
            if self.match(params, bits[:64]) == 64:
                out.append(params)
        return out

    def encode(self, w: BitWriter, params: Params) -> None:
        seed, mode = params
        w.write(seed, 32)
        w.write(mode, 1)

    def decode(self, r: BitReader) -> Params:
        seed = r.read(32)
        mode = r.read(1)
        return (seed, mode)

    def bit_length(self, params: Params) -> int:
        return 33

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        seed, mode = params
        state = seed
        produced = 0
        while produced < nbits:
            state = _xorshift_step(state)
            words = [
                (state >> 24) & 0xFF,
                (state >> 16) & 0xFF,
                (state >> 8) & 0xFF,
                state & 0xFF,
            ]
            if mode == 1:
                words.reverse()
            for byte in words:
                for shift in range(7, -1, -1):
                    if produced >= nbits:
                        return
                    yield (byte >> shift) & 1
                    produced += 1


class QuadraticModel(Model):
    """Constant second differences over Z/(2**w), w in {8, 16, 32}."""

    mid = 6
    name = "quadratic"
    FORMATS = ((1, "big"), (2, "big"), (2, "little"), (4, "big"), (4, "little"))

    def fit_lanes(
        self, data: bytes, probe: int, window: int, earliest: int, max_span: int, minimum: int,
    ) -> tuple[int, int, Params] | None:
        """Try each word phase at a probe, with exact backward/forward verification."""
        best = None
        bound = min(probe + window, len(data))
        for mode, (width, order) in enumerate(self.FORMATS):
            mask = (1 << (8 * width)) - 1
            for offset in range(probe, min(probe + width, bound - 6 * width + 1)):
                first = data[offset : offset + 6 * width]
                a, b, c, d, e, f = (int.from_bytes(first[i : i + width], order)
                                     for i in range(0, len(first), width))
                step = (b - a) & mask
                dd = (c - 2 * b + a) & mask
                if not dd or any((right - 2 * middle + left) & mask != dd
                                 for left, middle, right in ((b, c, d), (c, d, e), (d, e, f))):
                    continue
                start, value, delta = offset, a, step
                while start - width >= earliest:
                    prev_delta = (delta - dd) & mask
                    prev_value = (value - prev_delta) & mask
                    if int.from_bytes(data[start - width : start], order) != prev_value:
                        break
                    start -= width
                    value, delta = prev_value, prev_delta
                params = mode, value, delta, dd
                limit = min(len(data), start + max_span)
                pos = offset + 6 * width
                value = f
                delta = (step + 5 * dd) & mask
                while pos + width <= limit:
                    value = (value + delta) & mask
                    if int.from_bytes(data[pos : pos + width], order) != value:
                        break
                    delta = (delta + dd) & mask
                    pos += width
                cover = min(pos, limit) - start
                cover -= cover % width
                if cover >= minimum and (best is None or cover > best[1]):
                    best = start, cover, params
        return best

    def fit(self, bits: Sequence[int]) -> list[Params]:
        data = bits_to_bytes(bits[: min(len(bits) // 8, 16) * 8])
        out = []
        for mode, (width, order) in enumerate(self.FORMATS):
            if len(data) < 4 * width:
                continue
            a, b, c, d = (int.from_bytes(data[i : i + width], order) for i in range(0, 4 * width, width))
            mask = (1 << (8 * width)) - 1
            step = (b - a) & mask
            dd = (c - 2 * b + a) & mask
            if dd and (d - 2 * c + b) & mask == dd:
                out.append((mode, a, step, dd))
        return out

    def encode(self, w: BitWriter, params: Params) -> None:
        mode, *values = params
        w.write(mode, 3)
        for value in values:
            w.write(value, 8 * self.FORMATS[mode][0])

    def decode(self, r: BitReader) -> Params:
        mode = r.read(3)
        if mode >= len(self.FORMATS):
            raise ValueError("unknown quadratic word format")
        width = 8 * self.FORMATS[mode][0]
        return mode, r.read(width), r.read(width), r.read(width)

    def bit_length(self, params: Params) -> int:
        return 3 + 24 * self.FORMATS[params[0]][0]

    def describe(self, params: Params) -> str:
        mode, a, d, dd = params
        width, order = self.FORMATS[mode]
        suffix = order[0] + "e" if width > 1 else ""
        return f"{self.name} u{8 * width}{suffix} a={a} d={d} dd={dd}"

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        mode, a, step, dd = params
        width, order = self.FORMATS[mode]
        mask = (1 << (8 * width)) - 1

        def bits() -> Iterator[int]:
            nonlocal a, step
            while True:
                for byte in a.to_bytes(width, order):
                    for shift in range(7, -1, -1):
                        yield (byte >> shift) & 1
                a = (a + step) & mask
                step = (step + dd) & mask

        return islice(bits(), nbits)


class ReferenceModel(Model):
    """Exact slices of fixed mathematical streams, fitted in byte space."""

    mid = 7
    name = "constant-slice"

    def encode(self, w: BitWriter, params: Params) -> None:
        mode, start = params
        w.write(mode, 3)
        w.write(start, OFFSET_BITS)

    def decode(self, r: BitReader) -> Params:
        mode, start = r.read(3), r.read(OFFSET_BITS)
        if mode >= len(REFERENCE_NAMES):
            raise ValueError("unknown constant encoding")
        return mode, start

    def bit_length(self, params: Params) -> int:
        return 3 + OFFSET_BITS

    def describe(self, params: Params) -> str:
        mode, start = params
        return f"{self.name} {REFERENCE_NAMES[mode]}@{start}"

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        mode, start = params
        end = start + (nbits + 7) // 8
        if end > REFERENCE_SIZE:
            raise ValueError("constant slice exceeds the reference")
        return islice(
            (byte >> shift & 1 for byte in reference(mode)[start:end] for shift in range(7, -1, -1)),
            nbits,
        )


MODELS: list[Model] = [
    ConstantModel(),
    PeriodModel(),
    AffineModel(),
    LfsrModel(),
    XorShiftModel(),
]

QUADRATIC = QuadraticModel()
REFERENCE = ReferenceModel()
BY_ID = {m.mid: m for m in [*MODELS, QUADRATIC, REFERENCE]}

HEADER_BITS = 72  # codec + size + transform + model + param length + slack


def formula_cost_bits(model: Model, params: Params) -> int:
    return HEADER_BITS + model.bit_length(params)
