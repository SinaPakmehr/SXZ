from __future__ import annotations

import io
import os
import random
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sinuxz import Packer, StreamOptions, pack_stream, unpack, unpack_stream
from sinuxz.constants import reference, reference_hits
from sinuxz.folder import pack_folder, restore_folder
from sinuxz.native_scan import _load, candidate_offsets


class FolderTests(unittest.TestCase):
    def test_archive_contains_unicode_names_empty_directory_and_exact_file_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "Unicode folder é"
            (root / "empty é").mkdir(parents=True)
            nested = root / ("é" * 72)
            nested.mkdir()
            payload = random.Random(47).randbytes(18239)
            (nested / "data é.bin").write_bytes(payload)
            (root / "empty").write_bytes(b"")
            out = base / "backup.tar.sxz2"
            r = pack_folder(root, out, StreamOptions(chunk_size=1024, scan_budget=0))
            self.assertEqual(r["files"], 2)
            self.assertEqual(r["directories"], 3)
            self.assertEqual(r["input_bytes"], len(payload))
            decoded = io.BytesIO()
            with out.open("rb") as src:
                unpack_stream(src, decoded)
            decoded.seek(0)
            with tarfile.open(fileobj=decoded) as tar:
                self.assertTrue(tar.getmember(f"{root.name}/empty é").isdir())
                self.assertEqual(tar.extractfile(f"{root.name}/{nested.name}/data é.bin").read(), payload)
                self.assertEqual(tar.extractfile(f"{root.name}/empty").read(), b"")
            with self.assertRaises(FileExistsError):
                pack_folder(root, out, StreamOptions())
            self.assertEqual(out.stat().st_size, r["archive_bytes"])
            restored = base / "restored"
            result = restore_folder(out, restored)
            self.assertEqual(result["files"], 2)
            self.assertEqual((restored / root.name / nested.name / "data é.bin").read_bytes(), payload)
            self.assertTrue((restored / root.name / "empty é").is_dir())
            with self.assertRaisesRegex(ValueError, "exceeds"):
                restore_folder(out, base / "too-small", max_output=len(payload) - 1)
            self.assertFalse((base / "too-small").exists())
            with self.assertRaisesRegex(ValueError, "outside"):
                pack_folder(root, root / "recursive.sxz2", StreamOptions())

    def test_directory_restore_rejects_unsafe_members_without_publishing_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            for name in ("../outside", "/absolute", "x" + chr(92) + ".." + chr(92) + "outside", "file:stream"):
                raw = io.BytesIO()
                with tarfile.open(fileobj=raw, mode="w") as tar:
                    item = tarfile.TarInfo(name)
                    item.size = 4
                    tar.addfile(item, io.BytesIO(b"test"))
                archive = base / "bad.sxz2"
                with archive.open("wb") as dst:
                    pack_stream(io.BytesIO(raw.getvalue()), dst, StreamOptions(scan_budget=0))
                with self.assertRaisesRegex(ValueError, "unsafe"):
                    restore_folder(archive, base / "restored")
                self.assertFalse((base / "restored").exists())
                self.assertFalse((base / "outside").exists())

    def test_numeric_size_field_is_not_limited_to_four_gib(self) -> None:
        entry = tarfile.TarInfo("big.bin")
        entry.size = (5 << 30) + 77
        entry.uid = entry.gid = 0
        header = entry.tobuf(format=tarfile.PAX_FORMAT)
        with tarfile.open(fileobj=io.BytesIO(header + bytes(1024))) as tar:
            self.assertEqual(tar.next().size, entry.size)

    def test_fast_sample_profile_retains_exact_bytes(self) -> None:
        noise = random.Random(592).randbytes(1 << 20)
        data = noise + bytes(1 << 20)
        out = io.BytesIO()
        opts = StreamOptions(scan_budget=0, fast_sample=True)
        info = pack_stream(io.BytesIO(data), out, opts)
        self.assertEqual(info.first.codecs["raw"], 1)
        self.assertEqual(info.first.codecs["deflate"], 1)
        restored = io.BytesIO()
        out.seek(0)
        unpack_stream(out, restored)
        self.assertEqual(restored.getvalue(), data)


@unittest.skipUnless(os.environ.get("SINUXZ_SCAN_DLL"), "optional Rust scanner is not configured")
class NativeParityTests(unittest.TestCase):
    def test_dense_anchors_and_binary_data_have_identical_hits_and_archives(self) -> None:
        rng = random.Random(15)
        data = bytearray(rng.randbytes(26000))
        for mode in range(6):
            start = 101 + mode * 3851
            data[start:start + 1600] = reference(mode)[27:1627]
        data = bytes(data)
        self.assertIsNotNone(candidate_offsets(data, 7, len(data) - 7))
        native_hits = list(reference_hits(data, 7, len(data), 4096, 16))
        native = Packer(max_window=128, experimental_models=True, scan_budget=7).pack(data)
        try:
            with patch.dict(os.environ, {"SINUXZ_SCAN_DLL": ""}):
                _load.cache_clear()
                python_hits = list(reference_hits(data, 7, len(data), 4096, 16))
                python = Packer(max_window=128, experimental_models=True, scan_budget=7).pack(data)
        finally:
            _load.cache_clear()
        self.assertGreater(len(native_hits), 128)
        self.assertEqual(native_hits, python_hits)
        self.assertEqual(native, python)
        self.assertEqual(unpack(native), data)
