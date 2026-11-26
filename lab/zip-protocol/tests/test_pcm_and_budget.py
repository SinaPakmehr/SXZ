from __future__ import annotations

import random
import struct
import unittest
import zlib

from sinuxz import Packer, inspect, unpack
from sinuxz.constants import reference
from sinuxz.container import CODEC_PCM, FLAG_STRUCTURED, HEADER, MAGIC, SEG_PCM, VERSION
from sinuxz.pcm import BLOCK_FRAMES, _encode_block, _mode, restore_pcm, wav_layout


def wav(samples: bytes, channels: int, *, bits: int = 16, metadata: bool = True) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack("<4sI", tag, len(data)) + data + (b"\x5a" if len(data) % 2 else b"")

    width = channels * bits // 8
    fmt = struct.pack("<HHIIHH", 1, channels, 44100, 44100 * width, width, bits)
    body = b"WAVE"
    if metadata:
        body += chunk(b"JUNK", b"odd")
    body += chunk(b"fmt ", fmt) + chunk(b"data", samples)
    if metadata:
        body += chunk(b"tail", b"exact tail!")
    return b"RIFF" + struct.pack("<I", len(body)) + body


class PCMTests(unittest.TestCase):
    def test_all_modes_across_block_boundary_and_metadata(self) -> None:
        rng = random.Random(1225)
        for channels in (1, 2):
            samples = b"\x00\x80\xff\x7f" * channels + rng.randbytes((BLOCK_FRAMES + 11) * channels * 2)
            source = wav(samples, channels)
            layout = wav_layout(source)
            self.assertIsNotNone(layout)
            view = memoryview(source)
            for mode in range(channels * 6):
                with self.subTest(channels=channels, mode=mode):
                    params = _mode(mode, channels)
                    transformed = b"".join(
                        _encode_block(view[i : min(i + layout.block_bytes, layout.end)], channels, params)
                        for i in range(layout.start, layout.end, layout.block_bytes)
                    )
                    self.assertEqual(restore_pcm(source[:layout.start] + transformed + source[layout.end:], mode), source)

    def test_correlated_stereo_uses_pcm_even_without_formula_scan(self) -> None:
        rng = random.Random(1255)
        samples = bytearray()
        for i in range(16000):
            a = (min(i % 173, 173 - i % 173) - 43) * 160 + rng.randrange(-30, 31)
            samples += struct.pack("<hh", a, a + rng.randrange(-10, 11))
        source = wav(samples, 2)
        packer = Packer(experimental_models=True, scan_budget=0)
        blob = packer.pack(source)
        self.assertEqual(unpack(blob), source)
        self.assertEqual(packer.probe_count, 0)
        self.assertEqual(inspect(blob)["codec_counts"], {"pcm-residual": 1})
        self.assertLess(len(blob), len(zlib.compress(source, 9)) + HEADER.size)

    def test_noise_and_unsupported_codec_fall_back(self) -> None:
        rng = random.Random(43)
        for source in (wav(rng.randbytes(16384), 2), wav(rng.randbytes(125), 1, bits=8)):
            with self.subTest(size=len(source)):
                blob = Packer(experimental_models=True, scan_budget=0).pack(source)
                self.assertEqual(unpack(blob), source)
                self.assertEqual(inspect(blob)["residual_bytes"], 0)

    def test_malformed_layout_and_mode_fail(self) -> None:
        source = wav(bytes(24), 1)
        comp = zlib.compress(source)
        header = HEADER.pack(MAGIC, VERSION, FLAG_STRUCTURED, len(source), 1, zlib.crc32(source))
        for mode in (6, 12, 255):
            with self.assertRaises(ValueError):
                unpack(header + SEG_PCM.pack(CODEC_PCM, len(source), len(comp), mode) + comp)
        self.assertIsNone(wav_layout(source[:-1]))


class BudgetTests(unittest.TestCase):
    def test_quadratic_recovers_odd_word_phase_and_rewinds_uncommitted_bytes(self) -> None:
        rng = random.Random(176)
        offset = 7001
        block = b"".join(struct.pack("<H", (7 * i * i + 1103 * i + 65501) & 65535) for i in range(10000))
        source = rng.randbytes(offset) + block + rng.randbytes(40000 - offset - len(block))
        packer = Packer(max_window=128, extend_bytes=32768, experimental_models=True, scan_budget=5)
        blob = packer.pack(source)
        self.assertLessEqual(packer.probe_count, 5)
        segs = inspect(blob)["segments"]
        self.assertEqual(unpack(blob), source)
        self.assertEqual(segs[1]["offset"], offset)
        self.assertEqual(segs[1]["size"], len(block))
        self.assertIn("quadratic u16le", segs[1]["detail"])

    def test_absolute_probe_bound_and_off_grid_reference(self) -> None:
        rng = random.Random(96)
        ref = reference(5)[79:2079]
        source = rng.randbytes(112345) + ref + rng.randbytes(98765)
        packer = Packer(max_window=128, experimental_models=True, scan_budget=7)
        blob = packer.pack(source)
        self.assertLessEqual(packer.probe_count, 7)
        info = inspect(blob)
        self.assertEqual(info["formula_bytes"], len(ref))
        self.assertEqual(info["segments"][1]["offset"], 112345)
        self.assertEqual(unpack(blob), source)
        self.assertGreater(packer.scan_seconds, 0)
        self.assertEqual(unpack(packer.pack(b"")), b"")
        self.assertEqual(packer.probe_count, 0)
        self.assertEqual(packer.scan_seconds, 0)

    def test_budget_zero_uses_raw_or_whole_deflate_on_generic_file(self) -> None:
        source = reference(0)[79:4079]
        packer = Packer(experimental_models=True, scan_budget=0)
        blob = packer.pack(source)
        self.assertEqual(unpack(blob), source)
        self.assertEqual(inspect(blob)["formula_bytes"], 0)
        self.assertEqual(packer.probe_count, 0)

    def test_negative_budget_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Packer(scan_budget=-1)
