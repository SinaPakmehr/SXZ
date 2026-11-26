from __future__ import annotations

import unittest

from sinuxz.bitio import BitReader, BitWriter, bits_to_bytes, bytes_to_bits
from sinuxz.models import (
    LfsrModel,
    XorShiftModel,
    _xorshift_step,
    _xorshift_unstep,
    berlekamp_massey,
)
from sinuxz.transforms import TRANSFORMS


class BitIoTests(unittest.TestCase):
    def test_roundtrip_bits(self) -> None:
        data = bytes(range(64))
        bits = bytes_to_bits(data)
        self.assertEqual(bits_to_bytes(bits), data)

    def test_writer_reader(self) -> None:
        w = BitWriter()
        w.write(5, 3)
        w.write(0b1010, 4)
        w.write_bit(1)
        blob = w.to_bytes()
        self.assertEqual(w.bit_length, 8)
        r = BitReader(blob, w.bit_length)
        self.assertEqual(r.read(3), 5)
        self.assertEqual(r.read(4), 0b1010)
        self.assertEqual(r.read_bit(), 1)
        self.assertEqual(r.remaining(), 0)


class TransformTests(unittest.TestCase):
    def test_inverse(self) -> None:
        data = bytes(range(256)) * 2 + b"hello world"
        for tr in TRANSFORMS:
            with self.subTest(tr.name):
                self.assertEqual(tr.inverse(tr.forward(data)), data)


class ModelTests(unittest.TestCase):
    def test_berlekamp_massey_known_lfsr(self) -> None:
        # x^8 + x^6 + x^5 + x^4 + 1 (taps bits 0,4,5,6)
        L = 8
        taps = (1 << 0) | (1 << 4) | (1 << 5) | (1 << 6)
        seed = 0b10110010
        model = LfsrModel()
        bits = list(model.gen((L, taps, seed), 200))
        C, found = berlekamp_massey(bits)
        self.assertEqual(found, L)
        found_taps = sum((1 << (j - 1)) for j in range(1, L + 1) if C[j])
        self.assertEqual(found_taps, taps)

    def test_lfsr_fit(self) -> None:
        model = LfsrModel()
        L, taps, seed = 12, (1 << 11) | (1 << 10) | (1 << 8) | 1, 0xACE
        bits = list(model.gen((L, taps, seed), 300))
        cands = model.fit(bits)
        self.assertTrue(cands)
        for params in cands:
            self.assertEqual(model.match(params, bits), len(bits))

    def test_xorshift_inverse(self) -> None:
        for seed in (0, 1, 2, 0xDEADBEEF, 0xFFFFFFFF):
            self.assertEqual(_xorshift_unstep(_xorshift_step(seed)), seed)

    def test_xorshift_fit(self) -> None:
        model = XorShiftModel()
        seed = 0x12345678
        bits = list(model.gen((seed, 0), 512))
        cands = model.fit(bits)
        self.assertTrue(any(p[0] == seed for p in cands))
        for params in cands:
            self.assertEqual(model.match(params, bits), len(bits))

    def test_param_roundtrip(self) -> None:
        from sinuxz.models import MODELS

        samples = {
            1: [(0,), (1,)],
            2: [(5, 0b10101)],
            3: [(1, 8, 7, 3)],
            4: [(12, 0b101000000001, 0xACE)],
            5: [(0xDEADBEEF, 1)],
        }
        for model in MODELS:
            for params in samples[model.mid]:
                w = BitWriter()
                model.encode(w, params)
                r = BitReader(w.to_bytes(), w.bit_length)
                self.assertEqual(model.decode(r), params)
                self.assertEqual(r.remaining(), 0)


if __name__ == "__main__":
    unittest.main()
