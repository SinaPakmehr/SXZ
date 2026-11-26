"""SXZ3 experimental model bank.

Models are subclasses of :class:`sinuxz.models.Model`, so the same parameter
encoding can be used by the existing SXZ1/SXZ2 container and by the new SXZ3
block coder.  Every model is deterministic: its parameters plus the requested
length determine the bytes, and nothing else.

Additions over the shipped bank:

* word models for 8/16/24/32/64-bit values in both byte orders,
* an explicit byte phase, stored as a literal prefix,
* multi-lane (interleaved) sequences,
* first-order recurrences: LCG, xor-constant and xor-rotate,
* all fitters are mode-based, so sparse corruption does not hide a long law.
"""

from __future__ import annotations

from collections import Counter
from itertools import islice
from typing import Iterable, Iterator, Sequence

from sinuxz.bitio import BitReader, BitWriter, bits_to_bytes, bits_to_int, int_to_bits
from sinuxz.models import Model, Params, berlekamp_massey
from sinuxz.constants import REFERENCE_NAMES, REFERENCE_SIZE, find_reference, reference

WIDTHS = (1, 2, 3, 4, 8)
ORDER_BE, ORDER_LE = 0, 1


def _order_name(order: int) -> str:
    return "big" if order == ORDER_BE else "little"


def _emit(value: int, width: int, order: int) -> Iterator[int]:
    raw = value.to_bytes(width, "big" if order == ORDER_BE else "little")
    for byte in raw:
        for shift in range(7, -1, -1):
            yield (byte >> shift) & 1


def _bits_of_prefix(prefix: bytes) -> Iterator[int]:
    for byte in prefix:
        for shift in range(7, -1, -1):
            yield (byte >> shift) & 1


def _prefix_bytes(data: bytes, phase: int) -> int:
    return int.from_bytes(data[:phase], "big") if phase else 0


def extract_words(data: bytes, width: int, order: int, phase: int, limit: int | None = None) -> list[int]:
    end = len(data) - (len(data) - phase) % width
    if limit is not None:
        end = min(end, phase + limit * width)
    return [int.from_bytes(data[i : i + width], "big" if order == ORDER_BE else "little")
            for i in range(phase, end, width)]


def pack_words(words: Sequence[int], width: int, order: int, phase: int, size: int) -> bytes:
    out = bytearray()
    for value in words:
        out += value.to_bytes(width, "big" if order == ORDER_BE else "little")
    data = bytes(out)
    return data[:(size - phase)]


class _WordModel(Model):
    """Shared encoding: width, order, phase, literal prefix, then words."""

    BASE_BITS = 7

    def fit(self, bits) -> list[Params]:
        """Bit-level adapter so the same model can run inside SXZ1/SXZ2."""
        return self.fit_params(bits_to_bytes(bits))

    @staticmethod
    def _prefix_bytes(params: Params) -> bytes:
        phase, prefix = params[2], params[3]
        return prefix.to_bytes(phase, "big") if phase else b""

    def _prefix_len(self, params: Params) -> int:
        return params[2]

    def _write_header(self, w: BitWriter, width_code: int, order: int, phase: int, prefix: int) -> None:
        w.write(width_code, 3)
        w.write(order, 1)
        w.write(phase, 3)
        if phase:
            w.write(prefix, 8 * phase)

    def _read_header(self, r: BitReader) -> tuple[int, int, int, int]:
        code, order, phase = r.read(3), r.read(1), r.read(3)
        if code >= len(WIDTHS):
            raise ValueError("unknown word width")
        if phase >= WIDTHS[code]:
            raise ValueError("invalid word phase")
        prefix = r.read(8 * phase) if phase else 0
        return code, order, phase, prefix

    @staticmethod
    def _emit_prefix(params: Params) -> Iterator[int]:
        phase, prefix = params[2], params[3]
        if phase:
            yield from _bits_of_prefix(prefix.to_bytes(phase, "big"))


class AffineWord(_WordModel):
    """x[i] = a + i*d mod 2**(8*width), for any supported width and byte order."""

    mid = 8
    name = "affine-word"

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for code, width in enumerate(WIDTHS):
            mask = (1 << (8 * width)) - 1
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = extract_words(data, width, order, phase, limit=256)
                    if len(words) < 8:
                        continue
                    diffs = [(words[i + 1] - words[i]) & mask for i in range(len(words) - 1)]
                    d, count = Counter(diffs).most_common(1)[0]
                    if count * 2 < len(diffs) or d == 0:
                        continue
                    starts = [(words[i] - i * d) & mask for i in range(len(words))]
                    a, acount = Counter(starts).most_common(1)[0]
                    score = acount / len(words)
                    params = (code, order, phase, _prefix_bytes(data, phase), a, d)
                    if best is None or score > best[0]:
                        best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        code, order, phase, prefix, a, d = params
        width = WIDTHS[code]
        self._write_header(w, code, order, phase, prefix)
        w.write(a, 8 * width)
        w.write(d, 8 * width)

    def decode(self, r: BitReader) -> Params:
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        return code, order, phase, prefix, r.read(8 * width), r.read(8 * width)

    def bit_length(self, params: Params) -> int:
        code, _, phase, *_ = params
        return self.BASE_BITS + 8 * phase + 16 * 8 * WIDTHS[code]

    def describe(self, params: Params) -> str:
        code, order, phase, _, a, d = params
        return f"{self.name} u{8*WIDTHS[code]}{'le' if order else 'be'} p={phase} a={a} d={d}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        code, order, phase, _, a, d = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        out = bytearray(self._prefix_bytes(params))
        i = 0
        while len(out) < size:
            out += ((a + i * d) & mask).to_bytes(width, _order_name(order))
            i += 1
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        code, order, phase, _, a, d = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        produced = 0
        for bit in self._emit_prefix(params):
            if produced >= nbits:
                return
            yield bit
            produced += 1
        i = 0
        while produced < nbits:
            value = (a + i * d) & mask
            for bit in _emit(value, width, order):
                if produced >= nbits:
                    return
                yield bit
                produced += 1
            i += 1


class QuadraticWord(_WordModel):
    """x[i] = a + i*d + C(i,2)*dd mod 2**(8*width)."""

    mid = 9
    name = "quadratic-word"

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for code, width in ((0, 1), (1, 2), (3, 4), (4, 8)):
            mask = (1 << (8 * width)) - 1
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = extract_words(data, width, order, phase, limit=256)
                    if len(words) < 9:
                        continue
                    d2 = [(words[i + 2] - 2 * words[i + 1] + words[i]) & mask
                          for i in range(len(words) - 2)]
                    d2_count = Counter(d2).most_common(1)[0]
                    dd, count = d2_count
                    if count * 2 < len(d2) or dd == 0:
                        continue
                    ys = [(words[i] - (i * (i - 1) // 2) * dd) & mask for i in range(len(words))]
                    diffs = [(ys[i + 1] - ys[i]) & mask for i in range(len(ys) - 1)]
                    d, dcount = Counter(diffs).most_common(1)[0]
                    if dcount * 2 < len(diffs):
                        continue
                    starts = [(ys[i] - i * d) & mask for i in range(len(ys))]
                    a, acount = Counter(starts).most_common(1)[0]
                    score = acount / len(ys)
                    params = (code, order, phase, _prefix_bytes(data, phase), a, d, dd)
                    if best is None or score > best[0]:
                        best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        code, order, phase, prefix, a, d, dd = params
        width = WIDTHS[code]
        self._write_header(w, code, order, phase, prefix)
        for value in (a, d, dd):
            w.write(value, 8 * width)

    def decode(self, r: BitReader) -> Params:
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        return (code, order, phase, prefix) + tuple(r.read(8 * width) for _ in range(3))

    def bit_length(self, params: Params) -> int:
        code, _, phase, *_ = params
        return self.BASE_BITS + 8 * phase + 24 * 8 * WIDTHS[code]

    def describe(self, params: Params) -> str:
        code, order, phase, _, a, d, dd = params
        return f"{self.name} u{8*WIDTHS[code]}{'le' if order else 'be'} p={phase} a={a} d={d} dd={dd}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        code, order, phase, _, a, d, dd = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        out = bytearray(self._prefix_bytes(params))
        step = d
        while len(out) < size:
            out += a.to_bytes(width, _order_name(order))
            a = (a + step) & mask
            step = (step + dd) & mask
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        code, order, phase, _, a, d, dd = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        produced = 0
        for bit in self._emit_prefix(params):
            if produced >= nbits:
                return
            yield bit
            produced += 1
        i, step = 0, d
        while produced < nbits:
            for bit in _emit(a, width, order):
                if produced >= nbits:
                    return
                yield bit
                produced += 1
            a = (a + step) & mask
            step = (step + dd) & mask
            i += 1


class LanesWord(_WordModel):
    """c interleaved word sequences, each an independent affine progression."""

    mid = 10
    name = "lanes-word"

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for lanes in (2, 3, 4):
            for code, width in ((0, 1), (1, 2)):
                mask = (1 << (8 * width)) - 1
                for order in (ORDER_BE, ORDER_LE):
                    for phase in range(width):
                        stride = lanes * width
                        words = extract_words(data, width, order, phase, limit=256)
                        if len(words) < 4 * lanes:
                            continue
                        per_lane: list[tuple[int, int]] = []
                        ok = True
                        scores = []
                        for lane in range(lanes):
                            seq = words[lane::lanes]
                            if len(seq) < 4:
                                ok = False
                                break
                            diffs = [(seq[i + 1] - seq[i]) & mask for i in range(len(seq) - 1)]
                            d, count = Counter(diffs).most_common(1)[0]
                            if count * 2 < len(diffs):
                                ok = False
                                break
                            starts = [(seq[i] - i * d) & mask for i in range(len(seq))]
                            a, acount = Counter(starts).most_common(1)[0]
                            per_lane.append((a, d))
                            scores.append(acount / len(seq))
                        if not ok:
                            continue
                        score = sum(scores) / lanes
                        flat = tuple(value for pair in per_lane for value in pair)
                        params = (lanes, code, order, phase, _prefix_bytes(data, phase), flat)
                        if best is None or score > best[0]:
                            best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        lanes, code, order, phase, prefix, flat = params
        width = WIDTHS[code]
        w.write(lanes - 2, 2)
        w.write(code, 3)
        w.write(order, 1)
        w.write(phase, 3)
        if phase:
            w.write(prefix, 8 * phase)
        for value in flat:
            w.write(value, 8 * width)

    def decode(self, r: BitReader) -> Params:
        lanes = r.read(2) + 2
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        flat = tuple(r.read(8 * width) for _ in range(2 * lanes))
        return lanes, code, order, phase, prefix, flat

    def bit_length(self, params: Params) -> int:
        lanes, code, _, phase, *_ = params
        return 6 + 3 + 1 + 3 + 8 * phase + 2 * lanes * 8 * WIDTHS[code]

    def describe(self, params: Params) -> str:
        lanes, code, order, phase, _, flat = params
        return f"{self.name} {lanes}x u{8*WIDTHS[code]}{'le' if order else 'be'} p={phase}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        lanes, code, order, phase, _, flat = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        out = bytearray(self._prefix_bytes(params))
        counters = [0] * lanes
        while len(out) < size:
            for lane in range(lanes):
                a, d = flat[2 * lane], flat[2 * lane + 1]
                out += ((a + counters[lane] * d) & mask).to_bytes(width, _order_name(order))
            for lane in range(lanes):
                counters[lane] += 1
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        lanes, code, order, phase, _, flat = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        produced = 0
        for bit in self._emit_prefix(params):
            if produced >= nbits:
                return
            yield bit
            produced += 1
        counters = [0] * lanes
        while produced < nbits:
            for lane in range(lanes):
                a, d = flat[2 * lane], flat[2 * lane + 1]
                value = (a + counters[lane] * d) & mask
                for bit in _emit(value, width, order):
                    if produced >= nbits:
                        return
                    yield bit
                    produced += 1
            for lane in range(lanes):
                counters[lane] += 1


class LcgWord(_WordModel):
    """x[i] = a*x[i-1] + c mod 2**(8*width)."""

    mid = 11
    name = "lcg-word"

    @staticmethod
    def _candidates(seq: Sequence[int], mask: int, limit: int = 192) -> Counter:
        """Mode of (a, c) over every triple with an invertible difference."""
        mod = mask + 1
        found: Counter = Counter()
        for i in range(min(limit, len(seq) - 2)):
            x0, x1, x2 = seq[i], seq[i + 1], seq[i + 2]
            den = (x1 - x0) & mask
            if den % 2 == 0:
                continue
            a = ((x2 - x1) * pow(den, -1, mod)) & mask
            found[(a, (x1 - a * x0) & mask)] += 1
        return found

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for code, width in ((0, 1), (1, 2), (3, 4), (4, 8)):
            mask = (1 << (8 * width)) - 1
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = extract_words(data, width, order, phase, limit=1024)
                    if len(words) < 8:
                        continue
                    found = self._candidates(words, mask)
                    if not found:
                        continue
                    (a, c), _ = found.most_common(1)[0]
                    hits = sum(1 for i in range(len(words) - 1)
                               if ((a * words[i] + c) & mask) == words[i + 1])
                    score = hits / (len(words) - 1)
                    params = (code, order, phase, _prefix_bytes(data, phase), a, c, words[0])
                    if best is None or score > best[0]:
                        best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        code, order, phase, prefix, a, c, seed = params
        width = WIDTHS[code]
        self._write_header(w, code, order, phase, prefix)
        for value in (a, c, seed):
            w.write(value, 8 * width)

    def decode(self, r: BitReader) -> Params:
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        return (code, order, phase, prefix) + tuple(r.read(8 * width) for _ in range(3))

    def bit_length(self, params: Params) -> int:
        code, _, phase, *_ = params
        return self.BASE_BITS + 8 * phase + 24 * 8 * WIDTHS[code]

    def describe(self, params: Params) -> str:
        code, order, phase, _, a, c, seed = params
        return f"{self.name} u{8*WIDTHS[code]}{'le' if order else 'be'} a={a} c={c}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        code, order, phase, _, a, c, seed = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        out = bytearray(self._prefix_bytes(params))
        value = seed
        while len(out) < size:
            out += value.to_bytes(width, _order_name(order))
            value = (a * value + c) & mask
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        code, order, phase, _, a, c, seed = params
        width = WIDTHS[code]
        mask = (1 << (8 * width)) - 1
        produced = 0
        for bit in self._emit_prefix(params):
            if produced >= nbits:
                return
            yield bit
            produced += 1
        value = seed
        while produced < nbits:
            for bit in _emit(value, width, order):
                if produced >= nbits:
                    return
                yield bit
                produced += 1
            value = (a * value + c) & mask


class XorRotWord(_WordModel):
    """x[i] = rotl(x[i-1] ^ c, k) mod 2**(8*width); k=0 is plain xor."""

    mid = 12
    name = "xor-rotate"
    SHIFTS = (0, 1, 2, 3, 4, 5, 7, 8, 11, 12, 13, 16, 17, 24, 31, 32)

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for code, width in ((0, 1), (1, 2), (3, 4), (4, 8)):
            bits = 8 * width
            mask = (1 << bits) - 1
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = extract_words(data, width, order, phase, limit=256)
                    if len(words) < 8:
                        continue
                    for k in [s % bits for s in self.SHIFTS if s < bits]:
                        shifted = [((words[i] >> k) | (words[i] << (bits - k))) & mask if k else words[i]
                                   for i in range(len(words))]
                        rotated_c, count = Counter(
                            (shifted[i] ^ shifted[i + 1]) for i in range(len(shifted) - 1)
                        ).most_common(1)[0]
                        if count * 2 < len(shifted) - 1:
                            continue
                        c = (((rotated_c << k) | (rotated_c >> (bits - k))) & mask) if k else rotated_c
                        score = count / (len(shifted) - 1)
                        params = (code, order, phase, _prefix_bytes(data, phase), c, k, words[0])
                        if best is None or score > best[0]:
                            best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        code, order, phase, prefix, c, k, seed = params
        width = WIDTHS[code]
        self._write_header(w, code, order, phase, prefix)
        w.write(c, 8 * width)
        w.write(k, 6)
        w.write(seed, 8 * width)

    def decode(self, r: BitReader) -> Params:
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        return code, order, phase, prefix, r.read(8 * width), r.read(6), r.read(8 * width)

    def bit_length(self, params: Params) -> int:
        code, _, phase, *_ = params
        return self.BASE_BITS + 8 * phase + 16 * 8 * WIDTHS[code] + 6

    def describe(self, params: Params) -> str:
        code, order, phase, _, c, k, seed = params
        return f"{self.name} u{8*WIDTHS[code]}{'le' if order else 'be'} c={c} rot={k}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        code, order, phase, _, c, k, seed = params
        width = WIDTHS[code]
        bits = 8 * width
        mask = (1 << bits) - 1
        out = bytearray(self._prefix_bytes(params))
        value = seed
        while len(out) < size:
            out += value.to_bytes(width, _order_name(order))
            mixed = value ^ c
            value = (((mixed >> k) | (mixed << (bits - k))) & mask) if k else mixed
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        code, order, phase, _, c, k, seed = params
        width = WIDTHS[code]
        bits = 8 * width
        mask = (1 << bits) - 1
        produced = 0
        for bit in self._emit_prefix(params):
            if produced >= nbits:
                return
            yield bit
            produced += 1
        value = seed
        while produced < nbits:
            for bit in _emit(value, width, order):
                if produced >= nbits:
                    return
                yield bit
                produced += 1
            mixed = value ^ c
            value = (((mixed >> k) | (mixed << (bits - k))) & mask) if k else mixed

class PeriodBytes(_WordModel):
    """Byte-periodic data with a mode-based pattern, p in 1..64 bytes."""

    mid = 13
    name = "period-bytes"
    MAX_PERIOD = 64

    def fit_params(self, data: bytes) -> list[Params]:
        sample = data[:2048]
        best: tuple[float, Params] | None = None
        for p in range(1, min(self.MAX_PERIOD, len(sample) // 2) + 1):
            pattern = bytes(Counter(sample[j::p]).most_common(1)[0][0] for j in range(p))
            hits = sum(1 for i, byte in enumerate(sample) if byte == pattern[i % p])
            score = hits / len(sample)
            if score < 0.5:
                continue
            if best is None or score > best[0] + 1e-9 or (
                    abs(score - best[0]) <= 1e-9 and p < best[1][0]):
                best = (score, (p, int.from_bytes(pattern, "big")))
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        p, pattern = params
        w.write(p, 7)
        w.write(pattern, 8 * p)

    def decode(self, r: BitReader) -> Params:
        p = r.read(7)
        if not 1 <= p <= self.MAX_PERIOD:
            raise ValueError("invalid byte period")
        return p, r.read(8 * p)

    def bit_length(self, params: Params) -> int:
        return 7 + 8 * params[0]

    def describe(self, params: Params) -> str:
        return f"{self.name} p={params[0]}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        p, pattern = params
        raw = pattern.to_bytes(p, "big")
        return (raw * (size // p + 1))[:size]

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        p, pattern = params
        raw = pattern.to_bytes(p, "big")
        produced = 0
        i = 0
        while produced < nbits:
            for shift in range(7, -1, -1):
                if produced >= nbits:
                    return
                yield (raw[i % p] >> shift) & 1
                produced += 1
            i += 1


NEW_MODELS = [AffineWord(), QuadraticWord(), LanesWord(), LcgWord(), XorRotWord(), PeriodBytes()]

class XorShiftAny(_WordModel):
    """xorshift32 with a searched shift triple; seed is the first output word."""

    mid = 14
    name = "xorshift-any"
    TRIPLES = ((13, 17, 5), (7, 9, 13), (2, 7, 9), (5, 17, 13), (3, 5, 11), (1, 3, 10))

    @staticmethod
    def step(x: int, triple) -> int:
        a, b, c = triple
        x ^= (x << a) & 0xFFFFFFFF
        x ^= x >> b
        x ^= (x << c) & 0xFFFFFFFF
        return x & 0xFFFFFFFF

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for code, width in ((3, 4),):
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = extract_words(data, width, order, phase, limit=256)
                    if len(words) < 8:
                        continue
                    for index, triple in enumerate(self.TRIPLES):
                        state = words[0]
                        hits = 0
                        for value in words[1:]:
                            state = self.step(state, triple)
                            if state != value:
                                break
                            hits += 1
                        score = hits / (len(words) - 1)
                        params = (index, order, phase, _prefix_bytes(data, phase), words[0])
                        if best is None or score > best[0]:
                            best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        index, order, phase, prefix, seed = params
        w.write(index, 3)
        w.write(order, 1)
        w.write(phase, 3)
        if phase:
            w.write(prefix, 8 * phase)
        w.write(seed, 32)

    def decode(self, r: BitReader) -> Params:
        index, order, phase = r.read(3), r.read(1), r.read(3)
        if index >= len(self.TRIPLES):
            raise ValueError("unknown xorshift triple")
        prefix = r.read(8 * phase) if phase else 0
        return index, order, phase, prefix, r.read(32)

    def bit_length(self, params: Params) -> int:
        return 7 + 8 * params[2] + 32

    def describe(self, params: Params) -> str:
        index, order, phase, _, seed = params
        return f"{self.name} {self.TRIPLES[index]} {'le' if order else 'be'} seed={seed}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        index, order, phase, _, seed = params
        out = bytearray(self._prefix_bytes(params))
        state = seed
        triple = self.TRIPLES[index]
        while len(out) < size:
            out += state.to_bytes(4, _order_name(order))
            state = self.step(state, triple)
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        index, order, phase, _, seed = params
        produced = 0
        for bit in self._emit_prefix(params):
            if produced >= nbits:
                return
            yield bit
            produced += 1
        state = seed
        while produced < nbits:
            for bit in _emit(state, 4, order):
                if produced >= nbits:
                    return
                yield bit
                produced += 1
            state = self.step(state, self.TRIPLES[index])


NEW_MODELS.append(XorShiftAny())


def install() -> None:
    """Register the experimental models with the shipped SXZ1/SXZ2 packer."""
    import sinuxz.container as container
    import sinuxz.models as models

    for model in NEW_MODELS:
        if model not in container.MODELS:
            container.MODELS = [*container.MODELS, model]
        container.MODEL_BY_ID = {**container.MODEL_BY_ID, model.mid: model}
        models.BY_ID = {**models.BY_ID, model.mid: model}


def uninstall() -> None:
    import sinuxz.container as container
    import sinuxz.models as models

    ids = {model.mid for model in NEW_MODELS}
    container.MODELS = [m for m in container.MODELS if m.mid not in ids]
    container.MODEL_BY_ID = {mid: m for mid, m in container.MODEL_BY_ID.items() if mid not in ids}
    models.BY_ID = {mid: m for mid, m in models.BY_ID.items() if mid not in ids}

class ReferenceSlice(Model):
    """Exact slice of the fixed pi/e/phi streams, with an explicit cost."""

    mid = 15
    name = "reference-slice"

    def fit_params(self, data: bytes) -> list[Params]:
        if len(data) > REFERENCE_SIZE:
            self.last_score = 0.0
            return []
        match = find_reference(data, 0, len(data), 18)
        if match is None:
            self.last_score = 0.0
            return []
        cover, params = match
        self.last_score = cover / len(data)
        return [params]

    def fit(self, bits) -> list[Params]:
        return self.fit_params(bits_to_bytes(bits))

    def predict_bytes(self, params: Params, size: int) -> bytes:
        mode, start = params
        data = reference(mode)[start : start + size]
        if len(data) != size:
            raise ValueError("reference slice too short")
        return data

    def encode(self, w: BitWriter, params: Params) -> None:
        mode, start = params
        w.write(mode, 3)
        w.write(start, 12)

    def decode(self, r: BitReader) -> Params:
        mode = r.read(3)
        if mode >= len(REFERENCE_NAMES):
            raise ValueError("unknown reference mode")
        return mode, r.read(12)

    def bit_length(self, params: Params) -> int:
        return 15

    def describe(self, params: Params) -> str:
        mode, start = params
        return f"{self.name} {REFERENCE_NAMES[mode]}@{start}"

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        mode, start = params
        end = start + (nbits + 7) // 8
        if end > REFERENCE_SIZE:
            raise ValueError("reference slice exceeds the table")
        return (islice(
            (byte >> shift & 1 for byte in reference(mode)[start:end] for shift in range(7, -1, -1)),
            nbits))


NEW_MODELS.append(ReferenceSlice())
