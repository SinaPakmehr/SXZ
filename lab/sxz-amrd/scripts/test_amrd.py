"""Unit and integration checks for AMRD Episode 1.

Run from phases/12-amrd:

    python -B -m unittest scripts.test_amrd -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

PHASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_ROOT))

from amrd import controls
from amrd.economics import simple_sizes
from amrd.inference import (
    bm_fit,
    bm_generate,
    detect_affine2,
    detect_word_window,
    poly_predict,
)
from amrd.records import ModelRecord, record_information_bits, reconstruct_record_bytes
from amrd.representations import REP_BY_NAME, extract_symbols
from amrd.scanner import scan_file


class TestInference(unittest.TestCase):
    def test_poly_cubic(self):
        values = poly_predict([1000, 17, 5, 3], 256, 16)
        self.assertEqual(values[:4], [1000, 1017, 1039, 1069])
        self.assertEqual(
            [values[index + 1] - values[index] for index in range(3)],
            [17, 22, 30],
        )

    def test_affine1_recovery(self):
        control = controls.make_affine1(n=512)
        result = scan_file(
            control["data"],
            "affine1",
            reps=[REP_BY_NAME["u16le"]],
            windows=(64,),
        )
        models = [model for model in result.models if model.family == "affine1"]
        self.assertTrue(models)
        self.assertEqual(models[0].params[:2], (16645, 12345))
        self.assertTrue(models[0].exact)

    def test_affine2_recovery(self):
        control = controls.make_affine2(n=512)
        result = scan_file(
            control["data"],
            "affine2",
            reps=[REP_BY_NAME["u32le"]],
            windows=(64,),
        )
        models = [model for model in result.models if model.family == "affine2"]
        self.assertTrue(models)
        self.assertEqual(models[0].params[:3], (5, 11, 1234567))
        self.assertTrue(models[0].exact)

    def test_bm_lfsr(self):
        control = controls.make_lfsr(n=1024)
        result = scan_file(
            control["data"],
            "lfsr",
            reps=[REP_BY_NAME["bit0"]],
            windows=(64,),
        )
        models = [model for model in result.models if model.family == "bm"]
        self.assertTrue(models)
        self.assertEqual(models[0].order, 16)
        self.assertEqual(models[0].params[0], control["taps"])
        self.assertTrue(models[0].exact)

    def test_bm_matches_existing_sxz(self):
        sys.path.insert(0, str(PHASE_ROOT.parents[1] / "lab" / "zip-protocol"))
        try:
            from sinuxz.models import berlekamp_massey
        except ImportError:
            self.skipTest("legacy sinuxz package unavailable")

        rng = np.random.default_rng(7)
        for _ in range(200):
            bits = rng.integers(0, 2, 80, dtype=np.uint8)
            ours = bm_fit(bits.tolist())
            polynomial, order = berlekamp_massey(bits.tolist())
            taps = 0
            for j in range(1, order + 1):
                if polynomial[j] & 1:
                    taps |= 1 << (j - 1)
            self.assertEqual(ours, (order, taps))

    def test_singular_affine2_is_unresolved(self):
        # All differences are even; the 2x2 determinant is always even.
        values = [1, 4, 10, 22, 46, 94, 190, 382, 766, 1534, 3070, 6142]
        array = np.asarray(values, dtype=np.uint16)
        stats = {}
        result = detect_affine2(array[:8], array[8:], 16, stats)
        self.assertIsNone(result)
        self.assertGreaterEqual(stats.get("affine2_singular_systems", 0), 1)


class TestRecords(unittest.TestCase):
    def _roundtrip(self, model: ModelRecord, symbols):
        blob = model.to_bytes()
        decoded = ModelRecord.from_bytes(blob)
        reconstructed = decoded.reconstruct_symbols()
        self.assertEqual(reconstructed, list(symbols))
        self.assertEqual(len(blob), model.record_bytes if hasattr(model, "record_bytes") else len(blob))
        self.assertGreaterEqual(record_information_bits(decoded), 0)

    def test_records_all_families(self):
        cases = [
            controls.make_poly_cubic(n=128),
            controls.make_affine1(n=128),
            controls.make_affine2(n=128),
        ]
        expected = {
            "poly3": "u16le",
            "affine1": "u16le",
            "affine2": "u32le",
        }
        for case in cases:
            rep = REP_BY_NAME[case["rep"]]
            symbols = extract_symbols(case["data"], rep)
            result = scan_file(case["data"], case["name"], reps=[rep], windows=(64,))
            models = [model for model in result.models if model.family == case["family"]]
            self.assertTrue(models, case["name"])
            model = models[0]
            record = ModelRecord(
                model.family,
                rep,
                model.align,
                model.start,
                model.count,
                model.order,
                model.params,
            )
            decoded = ModelRecord.from_bytes(record.to_bytes())
            self.assertEqual(decoded.reconstruct_symbols(), [int(v) for v in symbols[model.start : model.start + model.count]])
            if rep.is_word:
                self.assertEqual(
                    reconstruct_record_bytes(record, case["data"]),
                    case["data"][model.start_byte : model.end_byte],
                )

    def test_bm_record(self):
        case = controls.make_lfsr(n=512)
        rep = REP_BY_NAME["bit0"]
        bits = extract_symbols(case["data"], rep)
        result = scan_file(case["data"], case["name"], reps=[rep], windows=(64,))
        model = [item for item in result.models if item.family == "bm"][0]
        record = ModelRecord(
            model.family,
            rep,
            model.align,
            model.start,
            model.count,
            model.order,
            model.params,
        )
        decoded = ModelRecord.from_bytes(record.to_bytes())
        self.assertEqual(decoded.reconstruct_symbols(), [int(v) for v in bits[model.start : model.start + model.count]])

    def test_corrupt_control(self):
        case = controls.make_corrupt(n=1024, rate=0.01)
        fit = controls.robust_affine2(case["values"], case["bits"])
        self.assertIsNotNone(fit)
        self.assertEqual((fit["a"], fit["b"], fit["c"]), case["params"][:3])
        self.assertGreater(fit["accuracy"], 0.95)
        self.assertLess(fit["accuracy"], 1.0)


class TestSimpleSizes(unittest.TestCase):
    def test_constant_and_periodic(self):
        self.assertEqual(simple_sizes(b"\x00" * 100)["const"], 6)
        periodic = simple_sizes(b"ab" * 50)
        self.assertEqual(periodic["period"], 2)
        self.assertEqual(periodic["periodic"], 8)
        self.assertIsNone(periodic["const"])


if __name__ == "__main__":
    unittest.main()
