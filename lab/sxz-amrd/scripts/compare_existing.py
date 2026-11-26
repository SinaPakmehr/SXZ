"""Compare AMRD detectors with the existing SXZ3/SXZ4 model fitters."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PHASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_ROOT))
sys.path.insert(0, str(PHASE_ROOT.parents[1] / "phases" / "00-06-sinuxz"))

import numpy as np

from amrd import controls
from amrd.config import RESULTS
from amrd.inference import bm_fit, poly_predict

from sinuxz.models import LfsrModel, berlekamp_massey
from experiments.sxz3.bank import AffineWord, LcgWord, QuadraticWord
from experiments.sxz4.program4 import Order2Word


def main():
    output = {"capabilities": [], "panel_nontrivial": []}

    # First-order affine: SXZ3 LcgWord.
    case = controls.make_affine1(n=2048)
    params = LcgWord().fit_params(case["data"])
    first = params[0] if params else None
    output["capabilities"].append(
        {
            "family": "affine1",
            "existing": "SXZ3 LcgWord (experiments/sxz3/bank.py, mid 11)",
            "amrd": "affine1",
            "existing_params": list(first) if first else None,
            "expected": [case["params"][0], case["params"][1], case["params"][2]],
            "match": bool(first and first[4] == case["params"][0] and first[5] == case["params"][1]),
        }
    )

    # Second-order affine: SXZ4 Order2Word.
    case2 = controls.make_affine2(n=2048)
    params2 = Order2Word().fit_params(case2["data"])
    first2 = params2[0] if params2 else None
    output["capabilities"].append(
        {
            "family": "affine2",
            "existing": "SXZ4 Order2Word (experiments/sxz4/program4.py, mid 16)",
            "amrd": "affine2",
            "existing_params": list(first2) if first2 else None,
            "expected": [case2["params"][2], case2["params"][0], case2["params"][1]],
            "match": bool(first2 and first2[4] == case2["params"][0] and first2[5] == case2["params"][1] and first2[6] == case2["params"][2]),
        }
    )

    # Arithmetic progression: SXZ3 AffineWord.
    sequence = poly_predict([1000, 17], 2048, 16)
    data = b"".join(int(value).to_bytes(2, "little") for value in sequence)
    params3 = AffineWord().fit_params(data)
    first3 = params3[0] if params3 else None
    output["capabilities"].append(
        {
            "family": "poly1 (arithmetic)",
            "existing": "SXZ3 AffineWord (experiments/sxz3/bank.py, mid 8)",
            "amrd": "poly1",
            "existing_params": list(first3) if first3 else None,
            "expected": [1000, 17],
            "match": bool(first3 and first3[4] == 1000 and first3[5] == 17),
        }
    )

    # Quadratic: SXZ3 QuadraticWord.
    sequence = poly_predict([1000, 17, 5], 2048, 16)
    data = b"".join(int(value).to_bytes(2, "little") for value in sequence)
    params4 = QuadraticWord().fit_params(data)
    first4 = params4[0] if params4 else None
    output["capabilities"].append(
        {
            "family": "poly2 (quadratic)",
            "existing": "SXZ3 QuadraticWord (experiments/sxz3/bank.py, mid 9)",
            "amrd": "poly2",
            "existing_params": list(first4) if first4 else None,
            "expected": [1000, 17, 5],
            "match": bool(first4 and first4[4] == 1000 and first4[5] == 17 and first4[6] == 5),
        }
    )

    # Binary LFSR: SXZ3 LfsrModel.
    lfsr = controls.make_lfsr(n=2048)
    params5 = LfsrModel().fit(lfsr["values"])
    first5 = params5[0] if params5 else None
    output["capabilities"].append(
        {
            "family": "bm (LFSR)",
            "existing": "SXZ3 LfsrModel / sinuxz.models.berlekamp_massey (mid 4)",
            "amrd": "bm",
            "existing_params": list(first5) if first5 else None,
            "expected": [lfsr["order"], lfsr["taps"]],
            "match": bool(first5 and first5[0] == lfsr["order"] and first5[1] == lfsr["taps"]),
        }
    )

    # Order-3 is not in SXZ3/SXZ4.
    output["capabilities"].append(
        {
            "family": "poly3",
            "existing": "none (SXZ3 stops at quadratic; SXZ4 adds order2 recurrence, not cubic differences)",
            "amrd": "poly3",
            "existing_params": None,
            "expected": [1000, 17, 5, 3],
            "match": None,
        }
    )

    # BM parity on random bit strings.
    rng = np.random.default_rng(20261203)
    parity = 0
    for _ in range(500):
        bits = rng.integers(0, 2, 96, dtype=np.uint8).tolist()
        ours = bm_fit(bits)
        polynomial, order = berlekamp_massey(bits)
        taps = 0
        for j in range(1, order + 1):
            if polynomial[j] & 1:
                taps |= 1 << (j - 1)
        if ours == (order, taps):
            parity += 1
    output["bm_parity"] = {"cases": 500, "identical": parity}

    # Any nontrivial real-file models to compare?  The Episode 1 panel found none.
    panel = json.loads((RESULTS / "panel.json").read_text(encoding="utf8"))
    for file in panel["files"]:
        for model in file["models"]:
            if model["family"] in {"poly1", "poly2", "poly3", "affine1", "affine2"}:
                output["panel_nontrivial"].append(
                    {
                        "file": file["name"],
                        "family": model["family"],
                        "rep": model["rep"],
                        "start": model["start"],
                        "count": model["count"],
                    }
                )

    target = RESULTS / "existing-compare.json"
    target.write_text(json.dumps(output, indent=1) + "\n", encoding="utf8")
    print(json.dumps(output, indent=1))


if __name__ == "__main__":
    main()
