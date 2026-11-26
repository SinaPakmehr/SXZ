from __future__ import annotations

import hashlib
import random
import unittest
import zlib
from math import comb

from sinuxz import Packer, inspect, unpack
from sinuxz.bitio import BitWriter, bits_to_bytes, bytes_to_bits
from sinuxz.constants import REFERENCE_SIZE, find_reference, reference
from sinuxz.container import (
    CODEC_FORMULA, CODEC_PNM, FLAG_DEFLATE, FLAG_STRUCTURED, HEADER, MAGIC, SEG_FORMULA, SEG_PNM, VERSION,
)
from sinuxz.models import QUADRATIC, REFERENCE, berlekamp_massey
from sinuxz.predictors import PREDICTORS, pnm_layout, predict_pnm


class ReferenceTests(unittest.TestCase):
    def test_all_reference_bytes_against_independent_values(self) -> None:
        # SHA-256 of streams independently computed with mpmath at 10050 digits.
        expected = (
            "4c68ac4b26a190dee1f40eb52d4b3e60e47e257136effa441fa5bb92c1f51bb4",
            "e510e33e6c9a0ae38cab52875244075f920c9f34b10548c5304bb5c6a4bff374",
            "f7bd4554441748f9277165f900c47c2692c60bde351ab8e8859496039d072801",
            "aa19b9a952e748e3c39ec33beeb95931be31f8a23c443712162b3af72861a3f8",
            "6765e4f69076cf3841563918ae9368b6849eab51abcf7e3c5569d3931fb6c6fe",
            "cf31cbeb93a8755d5ce757289a89057fea5fe81760dfe0134ce99a4f494e0908",
        )
        for mode, digest in enumerate(expected):
            with self.subTest(mode=mode):
                data = reference(mode)
                self.assertEqual(len(data), REFERENCE_SIZE)
                self.assertEqual(hashlib.sha256(data).hexdigest(), digest)
                sample = data[-256:]
                blob = Packer(experimental_models=True).pack(sample)
                self.assertEqual(unpack(blob), sample)
                self.assertEqual(inspect(blob)["formula_bytes"], len(sample))
                self.assertEqual(len(blob), 27)

    def test_anchor_is_not_a_match_and_runs_stop_at_a_mismatch(self) -> None:
        data = reference(0)[33:97]
        self.assertIsNone(find_reference(data[:8] + b"X" + data[9:], 0, len(data), 16))
        self.assertEqual(find_reference(data[:29] + b"X" + data[30:], 0, len(data), 16), (29, (0, 33)))

    def test_off_stride_slice_with_normal_fallback_on_both_sides(self) -> None:
        rng = random.Random(5)
        data = rng.randbytes(67) + reference(1)[11:1011] + rng.randbytes(173)
        packer = Packer(step=64, experimental_models=True)
        blob = packer.pack(data)
        self.assertEqual(unpack(blob), data)
        segs = inspect(blob)["segments"]
        self.assertEqual([s["offset"] for s in segs], [0, 67, 1067])
        self.assertEqual([s["size"] for s in segs], [67, 1000, 173])
        self.assertIn("pi/base256@11", segs[1]["detail"])
        self.assertLess(len(blob), len(Packer(step=64).pack(data)))

    def test_constant_slice_cannot_exceed_reference(self) -> None:
        w = BitWriter()
        REFERENCE.encode(w, (0, REFERENCE_SIZE - 1))
        blob = HEADER.pack(MAGIC, VERSION, FLAG_STRUCTURED, 16, 1, 0)
        blob += SEG_FORMULA.pack(CODEC_FORMULA, 16, 0, REFERENCE.mid, w.bit_length) + w.to_bytes()
        for parser in (inspect, unpack):
            with self.assertRaisesRegex(ValueError, "invalid constant slice"):
                parser(blob)


class QuadraticTests(unittest.TestCase):
    def test_every_width_and_endian_with_wraparound(self) -> None:
        for mode, (width, order) in enumerate(QUADRATIC.FORMATS):
            with self.subTest(width=width, order=order):
                mask = (1 << (width * 8)) - 1
                a, d, dd = mask - 7, mask - 28, 13
                data = b"".join(((a + i * d + comb(i, 2) * dd) & mask).to_bytes(width, order)
                                for i in range(257))
                params = mode, a, d, dd
                self.assertIn(params, QUADRATIC.fit(bytes_to_bits(data)))
                self.assertEqual(bits_to_bytes(QUADRATIC.gen(params, len(data) * 8)), data)
                blob = Packer(experimental_models=True).pack(data)
                self.assertEqual(unpack(blob), data)
                self.assertIn("quadratic", inspect(blob)["segments"][0]["detail"])


class ResidualTests(unittest.TestCase):
    def test_modular_prediction_preserves_header_pixels_and_boundaries(self) -> None:
        rng = random.Random(2)
        for tag, width, height, channels in ((5, 1, 1, 1), (5, 4, 3, 1), (6, 3, 2, 3)):
            for end in (b"\n", b"\r\n", b"\r"):
                header = f"P{tag}\r\n{width} {height}\r\n255".encode() + end
                source = header + b"\n" + rng.randbytes(width * height * channels - 1)
                self.assertEqual(pnm_layout(source), (len(header), width * channels, channels))
                for mode in range(len(PREDICTORS)):
                    residual = predict_pnm(source, mode)
                    self.assertEqual(residual[:len(header)], header)
                    self.assertEqual(predict_pnm(residual, mode, inverse=True), source)

    def test_pnm_predictor_selected_only_when_smaller(self) -> None:
        header = b"P6\n64 64\n255\n"
        data = header + bytes(v for y in range(64) for x in range(64)
                              for v in (x * 2, y * 2, x * y & 255))
        blob = Packer(max_window=128, experimental_models=True).pack(data)
        info = inspect(blob)
        self.assertEqual(unpack(blob), data)
        self.assertEqual(info["residual_bytes"], len(data))
        self.assertEqual(info["formula_bytes"], 0)
        self.assertLess(len(blob), len(Packer(max_window=128).pack(data)))

        noise = header + random.Random(3).randbytes(64 * 64 * 3)
        noisy_blob = Packer(max_window=128, experimental_models=True).pack(noise)
        self.assertEqual(unpack(noisy_blob), noise)
        self.assertEqual(inspect(noisy_blob)["residual_bytes"], 0)

    def test_residual_validation(self) -> None:
        data = b"P5\n2 2\n255\n\x00\xff\x02\x01"
        comp = zlib.compress(predict_pnm(data, 2))
        header = HEADER.pack(MAGIC, VERSION, FLAG_STRUCTURED, len(data), 1, zlib.crc32(data))
        illegal = header + SEG_PNM.pack(CODEC_PNM, len(data), len(comp), 3) + comp
        short = header + SEG_PNM.pack(CODEC_PNM, len(data), len(comp), 2) + comp[:-1]
        for blob in (illegal, short):
            for parser in (inspect, unpack):
                with self.assertRaises(ValueError):
                    parser(blob)


class FormatRegressionTests(unittest.TestCase):
    def test_reads_existing_sxz1_constant_run(self) -> None:
        blob = bytes.fromhex("53585a31 01 04 00100000 0100 11001cc7 02 00100000 00 01 0100 00")
        self.assertEqual(unpack(blob), b"\x00" * 4096)
        self.assertEqual(inspect(blob)["formula_bytes"], 4096)

    def test_bit_packing_honors_length_over_a_byte(self) -> None:
        self.assertEqual(bits_to_bytes([1] * 30, 10), b"\xff\xc0")

    def test_deflate_rejects_mismatched_size_and_trailing_bytes(self) -> None:
        comp = zlib.compress(b"x" * 500)
        for size, tail in ((1, b""), (500, b"extra")):
            header = HEADER.pack(MAGIC, VERSION, FLAG_DEFLATE, size, 0, 0)
            with self.assertRaises(ValueError):
                unpack(header + comp + tail, verify=False)

    def test_bit_parallel_recurrence_matches_its_input(self) -> None:
        rng = random.Random(17)
        for size in (1, 2, 25, 160, 512):
            for _ in range(5):
                bits = [rng.randrange(2) for _ in range(size)]
                c, degree = berlekamp_massey(bits)
                for j in range(degree, size):
                    self.assertEqual(bits[j], sum(c[i] * bits[j - i] for i in range(1, degree + 1)) % 2)
