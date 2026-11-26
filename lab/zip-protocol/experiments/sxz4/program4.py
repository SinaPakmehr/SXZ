"""SXZ4 algebraic and program models that go beyond a fixed linear bank.

* ``Order2Word`` - x[n] = a*x[n-1] + b*x[n-2] + c (mod 2**w)
* ``CrossChannel`` - lane l = a_l * lane0 + b_l, with lane0 itself affine
* ``ProgramWord`` - a depth-2 program discovered by bounded synthesis
"""

from __future__ import annotations

from collections import Counter
from typing import Iterator, Sequence

from sinuxz.bitio import BitReader, BitWriter, bits_to_bytes, bits_to_int, int_to_bits
from sinuxz.models import LfsrModel, Model, Params, XorShiftModel

from experiments.sxz3 import bank as bank3

WIDTHS = (1, 2, 4, 8)
ORDER_BE, ORDER_LE = 0, 1


def _order(order: int) -> str:
    return "big" if order == ORDER_BE else "little"


def extract(data: bytes, width: int, order: int, phase: int, limit: int | None = None) -> list[int]:
    end = len(data) - (len(data) - phase) % width
    if limit is not None:
        end = min(end, phase + limit * width)
    text = _order(order)
    return [int.from_bytes(data[i : i + width], text) for i in range(phase, end, width)]


def solve3(matrix: list[list[int]], rhs: list[int], mod: int) -> list[int] | None:
    """Gaussian elimination modulo 2**k; pivots must be odd (invertible)."""
    n = 3
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = None
        for row in range(col, n):
            if a[row][col] % 2:
                pivot = row
                break
        if pivot is None:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        inv = pow(a[col][col], -1, mod)
        a[col] = [(value * inv) % mod for value in a[col]]
        for row in range(n):
            if row != col and a[row][col]:
                factor = a[row][col]
                a[row] = [(value - factor * other) % mod for value, other in zip(a[row], a[col])]
    return [a[i][n] % mod for i in range(n)]


class _WordBase(Model):
    BASE_BITS = 7

    def fit(self, bits) -> list[Params]:
        return self.fit_params(bits_to_bytes(bits))

    def _write_header(self, w: BitWriter, code: int, order: int, phase: int, prefix: int) -> None:
        w.write(code, 3)
        w.write(order, 1)
        w.write(phase, 3)
        if phase:
            w.write(prefix, 8 * phase)

    def _read_header(self, r: BitReader):
        code, order, phase = r.read(3), r.read(1), r.read(3)
        if code >= len(WIDTHS) or phase >= WIDTHS[code]:
            raise ValueError("invalid word header")
        prefix = r.read(8 * phase) if phase else 0
        return code, order, phase, prefix

    @staticmethod
    def _mk_prefix(phase: int, prefix: int) -> bytes:
        return prefix.to_bytes(phase, "big") if phase else b""


class Order2Word(_WordBase):
    mid = 16
    name = "order2-word"

    def fit_params(self, data: bytes) -> list[Params]:
        best = None
        for code in (1, 2, 3):
            width = WIDTHS[code]
            bits = 8 * width
            mod = 1 << bits
            mask = mod - 1
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = extract(data, width, order, phase, limit=256)
                    if len(words) < 12:
                        continue
                    for start in range(min(8, len(words) - 6)):
                        x0, x1, x2, x3, x4 = words[start : start + 5]
                        matrix = [[x1, x0, 1], [x2, x1, 1], [x3, x2, 1]]
                        rhs = [x2, x3, x4]
                        solution = solve3(matrix, rhs, mod)
                        if solution is None:
                            continue
                        a, b, c = solution
                        if a == 0 and b == 0:
                            continue
                        # The recurrence must run from the first two words; a
                        # triple later in the sample only proposes a,b,c.
                        hits = 0
                        total = 0
                        for i in range(2, len(words)):
                            total += 1
                            if ((a * words[i - 1] + b * words[i - 2] + c) & mask) == words[i]:
                                hits += 1
                        score = hits / total
                        if score < 0.5:
                            continue
                        params = (code, order, phase, int.from_bytes(data[:phase], "big") if phase else 0,
                                  a, b, c, words[0], words[1])
                        if best is None or score > best[0]:
                            best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        code, order, phase, prefix, a, b, c, x0, x1 = params
        width = WIDTHS[code]
        self._write_header(w, code, order, phase, prefix)
        for value in (a, b, c, x0, x1):
            w.write(value, 8 * width)

    def decode(self, r: BitReader) -> Params:
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        values = tuple(r.read(8 * width) for _ in range(5))
        return (code, order, phase, prefix) + values

    def bit_length(self, params: Params) -> int:
        code, _, phase, *_ = params
        return self.BASE_BITS + 8 * phase + 40 * 8 * WIDTHS[code]

    def describe(self, params: Params) -> str:
        code, order, phase, _, a, b, c, x0, x1 = params
        return f"{self.name} u{8*WIDTHS[code]}{'le' if order else 'be'} a={a} b={b} c={c}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        code, order, phase, prefix, a, b, c, x0, x1 = params
        width = WIDTHS[code]
        bits = 8 * width
        mask = (1 << bits) - 1
        out = bytearray(self._mk_prefix(phase, prefix))
        words = [x0, x1]
        for value in words:
            out += value.to_bytes(width, _order(order))
        while len(out) < size:
            value = (a * words[-1] + b * words[-2] + c) & mask
            words.append(value)
            out += value.to_bytes(width, _order(order))
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        data = self.predict_bytes(params, (nbits + 7) // 8)
        return (bit for byte in data for bit in int_to_bits(byte, 8))


class CrossChannel(_WordBase):
    mid = 17
    name = "cross-channel"

    def fit_params(self, data: bytes) -> list[Params]:
        best = None
        for lanes in (2, 3, 4):
            for code, width in ((1, 2), (2, 4)):
                bits = 8 * width
                mask = (1 << bits) - 1
                for order in (ORDER_BE, ORDER_LE):
                    for phase in range(width):
                        words = extract(data, width, order, phase, limit=256)
                        if len(words) < 4 * lanes:
                            continue
                        base = words[0::lanes]
                        if len(base) < 4:
                            continue
                        diffs = [(base[i + 1] - base[i]) & mask for i in range(len(base) - 1)]
                        d, count = Counter(diffs).most_common(1)[0]
                        if count * 2 < len(diffs):
                            continue
                        starts = [(base[i] - i * d) & mask for i in range(len(base))]
                        a0, acount = Counter(starts).most_common(1)[0]
                        score = acount / len(base)
                        pairs = []
                        ok = True
                        for lane in range(1, lanes):
                            seq = words[lane::lanes]
                            cand = Counter()
                            for i in range(len(seq) - 1):
                                d0 = (base[i + 1] - base[i]) & mask
                                if d0 % 2 == 0:
                                    continue
                                a = ((seq[i + 1] - seq[i]) * pow(d0, -1, 1 << bits)) & mask
                                cand[(a, (seq[i] - a * base[i]) & mask)] += 1
                            if not cand:
                                ok = False
                                break
                            (a, b), hits = cand.most_common(1)[0]
                            score += hits / max(1, len(seq) - 1)
                            pairs.append((a, b))
                        if not ok:
                            continue
                        score /= lanes
                        params = (lanes, code, order, phase,
                                  int.from_bytes(data[:phase], "big") if phase else 0,
                                  a0, d, tuple(pairs))
                        if best is None or score > best[0]:
                            best = (score, params)
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []

    def encode(self, w: BitWriter, params: Params) -> None:
        lanes, code, order, phase, prefix, a0, d, pairs = params
        width = WIDTHS[code]
        w.write(lanes - 2, 2)
        self._write_header(w, code, order, phase, prefix)
        w.write(a0, 8 * width)
        w.write(d, 8 * width)
        for a, b in pairs:
            w.write(a, 8 * width)
            w.write(b, 8 * width)

    def decode(self, r: BitReader) -> Params:
        lanes = r.read(2) + 2
        code, order, phase, prefix = self._read_header(r)
        width = WIDTHS[code]
        a0 = r.read(8 * width)
        d = r.read(8 * width)
        pairs = tuple((r.read(8 * width), r.read(8 * width)) for _ in range(lanes - 1))
        return lanes, code, order, phase, prefix, a0, d, pairs

    def bit_length(self, params: Params) -> int:
        lanes, code, _, phase, *_ = params
        return 6 + 3 + 1 + 3 + 8 * phase + (2 + 2 * (lanes - 1)) * 8 * WIDTHS[code]

    def describe(self, params: Params) -> str:
        lanes, code, order, phase, *_ = params
        return f"{self.name} {lanes}x u{8*WIDTHS[code]}{'le' if order else 'be'}"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        lanes, code, order, phase, prefix, a0, d, pairs = params
        width = WIDTHS[code]
        bits = 8 * width
        mask = (1 << bits) - 1
        out = bytearray(self._mk_prefix(phase, prefix))
        step = 0
        while len(out) < size:
            base = (a0 + step * d) & mask
            out += base.to_bytes(width, _order(order))
            for a, b in pairs:
                out += ((a * base + b) & mask).to_bytes(width, _order(order))
            step += 1
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        data = self.predict_bytes(params, (nbits + 7) // 8)
        return (bit for byte in data for bit in int_to_bits(byte, 8))


class AffineWordV2(bank3.AffineWord):
    """Affine fit selected by real prediction match, not by modal differences.

    The SXZ3 fitter scores a candidate by the number of words that share the
    modal start.  On a sequence with occasional jumps that proxy can prefer a
    misaligned phase over the phase that actually predicts the stream.  This
    version enumerates candidate steps and scores every candidate by predicted
    equality on the sample.
    """

    mid = 20
    name = "affine-word-v2"

    def fit_params(self, data: bytes) -> list[Params]:
        best: tuple[float, Params] | None = None
        for code, width in enumerate(bank3.WIDTHS):
            mask = (1 << (8 * width)) - 1
            for order in (ORDER_BE, ORDER_LE):
                for phase in range(width):
                    words = bank3.extract_words(data, width, order, phase, limit=256)
                    if len(words) < 8:
                        continue
                    diffs = Counter((words[i + 1] - words[i]) & mask
                                    for i in range(len(words) - 1))
                    seen = set()
                    for d, _ in diffs.most_common(6):
                        if d in seen:
                            continue
                        seen.add(d)
                        starts = Counter((words[i] - i * d) & mask for i in range(len(words)))
                        for a, _ in starts.most_common(3):
                            hits = sum(1 for i, word in enumerate(words)
                                       if ((a + i * d) & mask) == word)
                            score = hits / len(words)
                            if best is None or score > best[0] + 1e-12:
                                best = (score, (code, order, phase,
                                                bank3._prefix_bytes(data, phase), a, d))
        self.last_score = best[0] if best else 0.0
        return [best[1]] if best else []


class LfsrBytes(LfsrModel):
    """Byte interface for the bit-oriented LFSR model (SXZ3 bank, mid 4)."""

    def fit_params(self, data: bytes) -> list[Params]:
        limit = min(len(data), 512)
        stream = [(byte >> shift) & 1 for byte in data[:limit] for shift in range(7, -1, -1)]
        fits = self.fit(stream)
        self.last_score = 1.0 if fits else 0.0
        return fits

    def predict_bytes(self, params: Params, size: int) -> bytes:
        from sinuxz.bitio import bits_to_bytes as pack_bits

        return pack_bits(self.gen(params, 8 * size), 8 * size)


class XorShiftBytes(XorShiftModel):
    """Byte interface for the 32-bit xorshift model (SXZ3 bank, mid 5)."""

    def fit_params(self, data: bytes) -> list[Params]:
        limit = min(len(data), 512)
        stream = [(byte >> shift) & 1 for byte in data[:limit] for shift in range(7, -1, -1)]
        fits = self.fit(stream)
        self.last_score = 1.0 if fits else 0.0
        return fits

    def predict_bytes(self, params: Params, size: int) -> bytes:
        from sinuxz.bitio import bits_to_bytes as pack_bits

        return pack_bits(self.gen(params, 8 * size), 8 * size)


class ProgramWord(_WordBase):
    mid = 18
    name = "program-word"

    def __init__(self):
        from experiments.sxz3.synth import OPS, ROTATIONS, FIXED

        self.ops, self.rotations, self.fixed = OPS, ROTATIONS, FIXED
        self.params_for_op: dict[str, tuple[int, ...]] = {}
        for op in OPS:
            if op in ("rotl", "rotr", "xorshr", "xorshl"):
                self.params_for_op[op] = ROTATIONS
            elif op == "mul":
                self.params_for_op[op] = tuple(c for c in FIXED if c % 2)
            else:
                self.params_for_op[op] = FIXED

    def fit_params(self, data: bytes) -> list[Params]:
        from experiments.sxz3 import synth

        self.last_score = 0.0
        if len(data) < 512:
            return []
        for order in (ORDER_LE, ORDER_BE):
            words = extract(data, 4, order, 0, limit=128)
            if len(words) < 70:
                continue
            program, matched, _ = synth.synthesize(words, verify=64)
            if program is None or matched < 60:
                continue
            # Locate the op ids and parameters inside the fixed tables.
            ops = (self.ops.index(program.op1), self.ops.index(program.op2))
            self.last_score = matched / 64
            return [(ops[0], program.p1, ops[1], program.p2, order, words[0])]
        return []

    def encode(self, w: BitWriter, params: Params) -> None:
        op1, p1, op2, p2, order, seed = params
        w.write(op1, 3)
        w.write(op2, 3)
        w.write(p1, 32)
        w.write(p2, 32)
        w.write(order, 1)
        w.write(seed, 32)

    def decode(self, r: BitReader) -> Params:
        op1, op2 = r.read(3), r.read(3)
        if op1 >= len(self.ops) or op2 >= len(self.ops):
            raise ValueError("unknown program operator")
        return op1, r.read(32), op2, r.read(32), r.read(1), r.read(32)

    def bit_length(self, params: Params) -> int:
        return 6 + 64 + 1 + 32

    def describe(self, params: Params) -> str:
        op1, p1, op2, p2, order, seed = params
        return f"{self.name} {self.ops[op2]}({p2}, {self.ops[op1]}({p1}, x))"

    def predict_bytes(self, params: Params, size: int) -> bytes:
        from experiments.sxz3.synth import apply_op

        op1, p1, op2, p2, order, seed = params
        out = bytearray()
        value = seed
        while len(out) < size:
            out += value.to_bytes(4, _order(order))
            value = apply_op(self.ops[op2], p2, apply_op(self.ops[op1], p1, value))
        return bytes(out[:size])

    def gen(self, params: Params, nbits: int) -> Iterator[int]:
        data = self.predict_bytes(params, (nbits + 7) // 8)
        return (bit for byte in data for bit in int_to_bits(byte, 8))


NEW_MODELS = [Order2Word(), CrossChannel(), ProgramWord()]
