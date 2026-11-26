from __future__ import annotations

import os
import random
import tempfile
import unittest

from sinuxz import Packer, inspect, unpack
from sinuxz.samples import build_samples


class ContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.samples_dir = os.path.join(cls.tmp.name, "samples")
        build_samples(cls.samples_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_roundtrip_samples(self) -> None:
        for name in os.listdir(self.samples_dir):
            if not name.endswith((".bin", ".txt", ".png")):
                continue
            with open(os.path.join(self.samples_dir, name), "rb") as fh:
                data = fh.read()
            with self.subTest(name=name):
                blob = Packer().pack(data)
                self.assertEqual(unpack(blob), data)
                self.assertLessEqual(len(blob), len(data) + 16, "container must never be worse than stored")

    def test_roundtrip_random_sizes(self) -> None:
        rng = random.Random(1)
        for size in (0, 1, 2, 7, 8, 9, 17, 63, 64, 255, 256, 1024, 4097):
            data = bytes(rng.getrandbits(8) for _ in range(size))
            with self.subTest(size=size):
                blob = Packer(max_window=128, extend_bytes=512).pack(data)
                self.assertEqual(unpack(blob), data)

    def test_formula_detected_for_structured_data(self) -> None:
        cases = {
            "zeros": b"\x00" * 2048,
            "counter": bytes(range(256)) * 8,
            "pattern": b"ABAB" * 512,
        }
        for name, data in cases.items():
            with self.subTest(name=name):
                blob = Packer(extend_bytes=8192).pack(data)
                info = inspect(blob)
                self.assertGreater(info["formula_bytes"], 0)
                self.assertEqual(unpack(blob), data)
                self.assertLess(len(blob), 64)

    def test_lfsr_and_xorshift_detected(self) -> None:
        for name in ("lfsr_4k.bin", "xorshift_4k.bin"):
            path = os.path.join(self.samples_dir, name)
            with open(path, "rb") as fh:
                data = fh.read()
            with self.subTest(name=name):
                blob = Packer(max_window=512, extend_bytes=8192).pack(data)
                info = inspect(blob)
                self.assertGreater(info["formula_ratio_percent"], 50.0)
                self.assertEqual(unpack(blob), data)

    def test_corrupt_crc_is_rejected(self) -> None:
        data = b"hello sinuxz" * 100
        blob = bytearray(Packer().pack(data))
        blob[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            unpack(bytes(blob))

    def test_not_a_container(self) -> None:
        with self.assertRaises(ValueError):
            unpack(b"PK\x03\x04 not ours")


if __name__ == "__main__":
    unittest.main()
