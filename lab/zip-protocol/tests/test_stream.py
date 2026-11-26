from __future__ import annotations

import io
import random
import struct
import tempfile
import unittest
import wave
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from sinuxz import Packer, StreamOptions, inspect_stream, pack_stream, unpack_stream
from sinuxz.cli import main
from sinuxz.stream import FRAME, HEADER, MAGIC, RAW, SXZ1, VERSION, _encode_stream


def encode(data: bytes, options: StreamOptions, *, second: bool = False):
    dst = io.BytesIO()
    info = pack_stream(io.BytesIO(data), dst, options, second_pass=second)
    return dst.getvalue(), info


def decode(archive: bytes, limit=None) -> bytes:
    dst = io.BytesIO()
    info = unpack_stream(io.BytesIO(archive), dst, max_output=limit)
    assert info.original_size == dst.tell()
    assert info.stored_size == len(archive)
    return dst.getvalue()


class StreamTests(unittest.TestCase):
    def test_empty_random_and_repeated_chunks(self) -> None:
        opts = StreamOptions(chunk_size=256, scan_budget=0)
        rng = random.Random(12)
        a, b = rng.randbytes(256), rng.randbytes(256)
        for data in (b"", a[:31], a + b + a + b + b + b"remainder"):
            blob, report = encode(data, opts)
            self.assertEqual(report.stored_size, len(blob))
            self.assertEqual(decode(blob), data)
        self.assertEqual(report.first.codecs["copy"], 3)
        info = inspect_stream(io.BytesIO(blob), limit=2)
        self.assertEqual(info["frames"], 6)
        self.assertEqual(len(info["segments"]), 2)
        self.assertEqual(info["segments"][1]["offset"], 256)

    def test_short_reads_and_no_full_read(self) -> None:
        class Short(io.BytesIO):
            def read(self, size=-1):
                if not 0 <= size <= 128:
                    raise AssertionError("read exceeds bounded request")
                return super().read(min(17, size))

            def seekable(self):
                return False

        data = random.Random(14).randbytes(2170)
        opts = StreamOptions(chunk_size=128, scan_budget=0, experimental_models=True)
        blob = io.BytesIO()
        pack_stream(Short(data), blob, opts)
        restored = io.BytesIO()
        unpack_stream(Short(blob.getvalue()), restored)
        self.assertEqual(restored.getvalue(), data)

    def test_writes_and_reads_sxz1_formula_frames(self) -> None:
        data = bytes(range(256)) * 40
        blob, report = encode(data, StreamOptions(chunk_size=1024, lookback=0, scan_budget=5))
        self.assertEqual(report.first.codecs["sxz1"], 10)
        self.assertLessEqual(report.first.probes, 50)
        self.assertEqual(decode(blob), data)

    def test_dictionary_bridge_helps_even_without_exact_frame_duplicates(self) -> None:
        rng = random.Random(21)
        left = rng.randbytes(4096)
        data = left + left[2048:] + rng.randbytes(2048)
        normal, _ = encode(data, StreamOptions(chunk_size=4096, lookback=0, scan_budget=0))
        opts = StreamOptions(chunk_size=4096, lookback=0, scan_budget=0, bridge=True)
        bridged, report = encode(data, opts)
        self.assertEqual(report.first.codecs["deflate-dict"], 1)
        self.assertLess(len(bridged), len(normal))
        self.assertTrue(inspect_stream(io.BytesIO(bridged))["dictionary_bridge"])
        self.assertEqual(decode(bridged), data)
        # Without the feature bit, the same record cannot silently use a dictionary.
        damaged = bytearray(bridged)
        damaged[5] = 0
        with self.assertRaisesRegex(ValueError, "no enabled predecessor"):
            decode(damaged)
        wrapped = io.BytesIO()
        _encode_stream(io.BytesIO(bridged), wrapped, opts, nested=True)
        wrapped_info = inspect_stream(io.BytesIO(wrapped.getvalue()))
        self.assertTrue(wrapped_info["nested"] and wrapped_info["dictionary_bridge"])
        self.assertEqual(decode(wrapped.getvalue()), data)

    def test_typed_pcm_frames_preserve_headers_padding_and_samples(self) -> None:
        dst = io.BytesIO()
        with wave.open(dst, "wb") as wav:
            wav.setparams((2, 2, 44100, 0, "NONE", ""))
            wav.writeframes(b"".join(struct.pack("<hh", n, n + 7) for n in range(-1024, 1024)))
        base = dst.getvalue()
        data = base[:4] + struct.pack("<I", len(base) - 8 + 12) + base[8:36] + b"JUNK\x03\x00\x00\x00xyZP" + base[36:]
        opts = StreamOptions(chunk_size=1031, scan_budget=0, experimental_models=True)
        blob, report = encode(data, opts)
        self.assertGreater(report.first.codecs["pcm"], 1)
        self.assertEqual(decode(blob), data)

    def test_typed_pnm_frames_preserve_exact_rows(self) -> None:
        pixels = bytes(v for y in range(50) for x in range(64) for v in (x * 2, y * 2, x * y & 255))
        data = b"P6\n64 50\n255\n" + pixels
        opts = StreamOptions(chunk_size=3840, scan_budget=0, experimental_models=True)
        blob, report = encode(data, opts)
        self.assertGreater(report.first.codecs["pnm"], 0)
        self.assertEqual(decode(blob), data)
        # A row larger than a frame is encoded as generic data instead.
        blob, report = encode(data, StreamOptions(chunk_size=64, scan_budget=0, experimental_models=True))
        self.assertEqual(report.first.codecs["pnm"], 0)
        self.assertEqual(decode(blob), data)

    def test_second_pass_is_selected_only_when_strictly_smaller(self) -> None:
        opts = StreamOptions(chunk_size=256, lookback=0, scan_budget=0)
        staged = (b"repeatable envelope\n" * 15)[:256] * 40
        good, result = encode(staged, opts, second=True)
        self.assertTrue(result.nested)
        self.assertTrue(inspect_stream(io.BytesIO(good))["nested"])
        self.assertLess(result.stored_size, result.first.stored_size)
        self.assertEqual(decode(good, len(staged)), staged)
        with self.assertRaises(ValueError):
            decode(good, len(staged) - 1)

        data = random.Random(77).randbytes(745)
        first, _ = encode(data, opts)
        final, result = encode(data, opts, second=True)
        self.assertFalse(result.nested)
        self.assertIsNotNone(result.second)
        self.assertEqual(final, first)
        self.assertEqual(decode(final), data)

    def test_rejects_more_than_one_outer_layer(self) -> None:
        opts = StreamOptions(chunk_size=256, lookback=0, scan_budget=0)
        data = b"hello" * 2000
        inner, result = encode(data, opts, second=True)
        self.assertTrue(result.nested)
        out = io.BytesIO()
        _encode_stream(io.BytesIO(inner), out, opts, nested=True)
        with self.assertRaisesRegex(ValueError, "only one"):
            decode(out.getvalue())

    def test_integrity_length_and_nested_sxz1_limit(self) -> None:
        opts = StreamOptions(chunk_size=256, lookback=0, scan_budget=0)
        data = random.Random(45).randbytes(245)
        blob, _ = encode(data, opts)
        broken = bytearray(blob)
        broken[HEADER.size + FRAME.size] ^= 1
        footer = bytearray(blob)
        footer[-8] ^= 1
        mismatch = HEADER.pack(MAGIC, VERSION, 0, 256, 0)
        claimed = Packer().pack(bytes(1024))
        mismatch += FRAME.pack(SXZ1, 128, len(claimed), zlib.crc32(bytes(128))) + claimed
        bad_ref = HEADER.pack(MAGIC, VERSION, 0, 256, 4) + FRAME.pack(3, 32, 1, 0) + b"\1"
        oversized = HEADER.pack(MAGIC, VERSION, 0, 256, 0) + FRAME.pack(RAW, 257, 257, 0)
        for invalid in (broken, footer, blob[:-1], blob + b"tail", oversized, mismatch, bad_ref):
            with self.assertRaises(ValueError):
                decode(invalid)
        with self.assertRaises(ValueError):
            decode(blob, len(data) - 1)

    def test_cli_auto_detects_and_uses_atomic_output(self) -> None:
        with tempfile.TemporaryDirectory() as root, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            src, blob, dst = [Path(root, name) for name in ("src", "archive.sxz2", "dst")]
            src.write_bytes(b"staged" * 1300)
            self.assertEqual(main(["pack-stream", str(src), str(blob), "--chunk-kib", "1", "--second-pass"]), 0)
            self.assertEqual(main(["inspect", str(blob), "--json"]), 0)
            self.assertEqual(main(["unpack", str(blob), str(dst)]), 0)
            self.assertEqual(dst.read_bytes(), src.read_bytes())
            blob.write_bytes(blob.read_bytes()[:-1])
            self.assertEqual(main(["unpack", str(blob), str(dst)]), 1)
            self.assertEqual(dst.read_bytes(), src.read_bytes())
            self.assertEqual(main(["pack-stream", str(src), str(src)]), 1)
