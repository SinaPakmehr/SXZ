"""SXZ4 correctness, corruption and resource-limit tests."""

from __future__ import annotations

import random
import struct
import unittest
import zlib

from experiments.sxz4 import numeric4, residual4, spans4, transforms4


class TransformTests(unittest.TestCase):
    def test_every_chain_round_trips(self):
        data = random.Random(1).randbytes(5000) + b"tail!"
        checked = 0
        for chain in transforms4.CHAINS:
            try:
                forward, metas = transforms4.apply_chain(data, chain)
            except ValueError:
                continue
            self.assertEqual(transforms4.invert_chain(forward, chain, metas), data, chain)
            checked += 1
        self.assertGreater(checked, 40)

    def test_csv_is_byte_exact(self):
        csv = (b"ts,value,label\r\n"
               b"1,20.70,a\r\n2,17.90,b\r\n3,21.15,c\r\n4,-0.001,d\r\n")
        forward, meta = transforms4.TRANSFORMS[21].forward(csv)
        self.assertEqual(transforms4.TRANSFORMS[21].inverse(forward, meta), csv)

    def test_csv_rejects_ragged_input(self):
        with self.assertRaises(ValueError):
            transforms4.TRANSFORMS[21].forward(b"a,b\n1,2\n3,4,5\n")

    def test_bitplanes_and_float(self):
        data = random.Random(2).randbytes(4097)
        for tid in (20, 9):
            forward, meta = transforms4.TRANSFORMS[tid].forward(data)
            self.assertEqual(transforms4.TRANSFORMS[tid].inverse(forward, meta), data)


class ResidualTests(unittest.TestCase):
    def test_rice_zigzag(self):
        values = [0, 1, 2, 3, 100000, 5, 7, 9]
        k, payload = residual4._best_rice(values)
        self.assertEqual(residual4.rice_decode(payload, len(values), k), values)
        for value in (0, 1, -1, 12345, -12345, 2**40):
            self.assertEqual(residual4._unzigzag(residual4._zigzag(value)), value)

    def test_worddiff_and_causal(self):
        data = b"".join(struct.pack("<H", (1000 + 5 * i) & 0xFFFF) for i in range(2000))
        pred = b"\x00" * len(data)
        width, k, payload = residual4.worddiff(pred, data, 2, "little")
        self.assertEqual(residual4.apply_worddiff(pred, 2, "little", k, payload), data)
        for kind in (1, 2):
            encoded = residual4.causal_encode(data, 0, len(data), 2, "little", kind)
            buffer = bytearray(len(data))
            residual4.apply_causal(buffer, 0, len(data), 2, "little", kind, encoded[2])
            self.assertEqual(bytes(buffer), data)

    def test_worddiff_unaligned_tail_is_kept(self):
        """A span whose length is not a multiple of the word width must round-trip."""
        base = b"".join(struct.pack("<I", (7 + 13 * i) & 0xFFFFFFFF) for i in range(600))
        for cut, width in ((1, 4), (2, 4), (3, 8), (5, 8)):
            pred = base[: len(base) - cut]
            actual = bytearray(pred)
            actual[-1] ^= 0xFF          # the change is in the short tail
            actual = bytes(actual)
            result = residual4.worddiff(pred, actual, width, "little")
            self.assertIsNotNone(result, (cut, width))
            _, k, payload = result
            self.assertEqual(
                residual4.apply_worddiff(pred, width, "little", k, payload), actual,
                (cut, width))


class NumericTests(unittest.TestCase):
    def test_baselines_round_trip(self):
        data = random.Random(3).randbytes(4096) + b"abc"
        for pack, unpack in ((numeric4.gorilla_pack, numeric4.gorilla_unpack),
                             (numeric4.fpc_pack, numeric4.fpc_unpack),
                             (numeric4.delta_deflate_pack, numeric4.delta_deflate_unpack)):
            self.assertEqual(unpack(pack(data)), data, pack.__name__)


class ArchiveTests(unittest.TestCase):
    def _u16(self, count=8000):
        return b"".join(struct.pack("<H", (1000 + 5 * i) & 0xFFFF) for i in range(count))

    def _order2(self, count=4000):
        a, b, c, mask = 3, 5, 7, 0xFFFFFFFF
        values = [12345, 67890]
        while len(values) < count:
            values.append((a * values[-1] + b * values[-2] + c) & mask)
        return b"".join(struct.pack("<I", value) for value in values)

    def test_roundtrip_cases(self):
        cases = {
            "u16": self._u16(),
            "order2": self._order2(),
            "text": (b"the quick brown fox jumps over the lazy dog. " * 800),
            "random": random.Random(4).randbytes(65536),
        }
        for name, data in cases.items():
            blob, stats = spans4.pack(data, chain=(0,))
            self.assertEqual(spans4.unpack(blob), data, name)

    def test_formula_finds_the_law(self):
        blob, stats = spans4.pack(self._u16())
        self.assertGreaterEqual(stats.spans, 1)
        self.assertLess(len(blob), 512)

    def test_resource_limit_falls_back(self):
        data = self._u16()
        blob, stats = spans4.pack(data, max_probes=0)
        self.assertEqual(stats.spans, 0)
        self.assertEqual(spans4.unpack(blob), data)

    def test_corruption_is_rejected(self):
        data = self._u16()
        blob, _ = spans4.pack(data)
        for offset in (len(blob) - 1, len(blob) // 2):
            broken = bytearray(blob)
            broken[offset] ^= 0xFF
            with self.assertRaises(ValueError):
                spans4.unpack(bytes(broken))

    def test_truncation_is_rejected(self):
        data = self._u16()
        blob, _ = spans4.pack(data)
        with self.assertRaises((ValueError, IndexError, struct.error)):
            spans4.unpack(blob[:-20])


if __name__ == "__main__":
    unittest.main()
