"""Generate and scan the six Episode 1 synthetic controls."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

PHASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_ROOT))

from amrd import controls
from amrd.config import RESULTS, SYNTHETIC, rel
from amrd.economics import lzma2_size, zstd19_size
from amrd.perf import peak_working_set_mb
from amrd.representations import REP_BY_NAME
from amrd.scanner import scan_file


def model_dict(model):
    return {
        "family": model.family,
        "rep": model.rep,
        "align": model.align,
        "start": model.start,
        "count": model.count,
        "order": model.order,
        "params": list(model.params),
        "record_bytes": model.record_bytes,
        "information_bits": model.information_bits,
        "window": model.window,
        "fit_len": model.fit_len,
        "val_len": model.val_len,
        "span_bytes": model.span_bytes,
        "start_byte": model.start_byte,
        "end_byte": model.end_byte,
        "start_bit": model.start_bit,
        "bit_count": model.bit_count,
        "exact": model.exact,
    }


def save_case(case):
    path = SYNTHETIC / f"{case['name']}.bin"
    path.write_bytes(case["data"])
    return path


def expected_match(case, models):
    family = case["family"]
    rep = case["rep"]
    candidates = [model for model in models if model.family == family and model.rep == rep]
    if not candidates:
        return None
    return max(candidates, key=lambda model: (model.count, model.record_bytes))


def params_match(case, model):
    if model is None:
        return False
    if case["family"] == "poly3":
        return tuple(int(value) for value in model.params[1:]) == tuple(case["initials"][1:])
    if case["family"] == "affine1":
        return tuple(int(value) for value in model.params[:2]) == tuple(case["params"][:2])
    if case["family"] == "affine2":
        return tuple(int(value) for value in model.params[:3]) == tuple(case["params"][:3])
    if case["family"] == "bm":
        return model.order == case["order"] and int(model.params[0]) == case["taps"]
    return False


def main():
    started = time.perf_counter()
    SYNTHETIC.mkdir(parents=True, exist_ok=True)
    cases = [
        controls.make_poly_cubic(),
        controls.make_affine1(),
        controls.make_affine2(),
        controls.make_lfsr(),
        controls.make_corrupt(),
        controls.make_random(),
    ]
    output = []
    for case in cases:
        path = save_case(case)
        print(f"scanning {case['name']} ({len(case['data'])} bytes)", flush=True)
        result = scan_file(case["data"], case["name"])
        matched = expected_match(case, result.models)
        record = {
            "name": case["name"],
            "description": case["description"],
            "file": rel(path),
            "bytes": len(case["data"]),
            "sha256": hashlib.sha256(case["data"]).hexdigest(),
            "family_expected": case["family"],
            "rep_expected": case["rep"],
            "params_expected": [int(value) for value in case.get("params", case.get("initials", []))],
            "values_head": [int(value) for value in case.get("values", case["data"])[:16]],
            "scan": {
                "windows": result.windows,
                "elapsed_s": result.elapsed_s,
                "throughput_mb_s": result.throughput_mb_s,
                "models": len(result.models),
                "models_by_family": result.models_by_family,
                "success_by_rep": result.success_by_rep,
                "stats": result.stats,
            },
            "matched": model_dict(matched) if matched else None,
            "params_match": params_match(case, matched),
            "record_verified": bool(matched.exact) if matched else False,
        }
        if case["family"] == "none":
            record["false_positive_models"] = [model_dict(model) for model in result.models]
            record["false_positive_count"] = len(result.models)
        if case["name"].startswith("synthetic-corrupt"):
            robust = controls.robust_affine2(case["values"], case["bits"])
            residual_bytes = b"".join(
                int(value).to_bytes(case["bits"] // 8, "little")
                for value in robust["residuals"]
            )
            robust["residual_zstd19"] = zstd19_size(residual_bytes)
            robust["residual_lzma2"] = lzma2_size(residual_bytes)
            robust["true_params"] = [int(value) for value in case["params"]]
            robust["corrupt_count"] = case["corrupt_count"]
            robust["corrupt_positions"] = case["corrupt_positions"]
            robust["true_params_match"] = (
                robust["a"],
                robust["b"],
                robust["c"],
            ) == tuple(case["params"][:3])
            record["robust_fit"] = robust
            record["scanner_exact_models"] = [model_dict(model) for model in result.models]
        output.append(record)
        print(
            f"  models={len(result.models)} matched={matched.family if matched else None} "
            f"windows={result.windows} elapsed={result.elapsed_s:.3f}s",
            flush=True,
        )

    payload = {
        "episode": 1,
        "phase": "12-amrd",
        "settings": {
            "windows": [64, 256],
            "stride": "half-window",
            "bm_max_order": 64,
            "affine_subset_budget": 16,
            "sample_limit": 262144,
        },
        "peak_memory_mb": peak_working_set_mb(),
        "elapsed_s": time.perf_counter() - started,
        "controls": output,
    }
    target = RESULTS / "controls.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(f"wrote {target} ({len(output)} controls) in {payload['elapsed_s']:.2f}s", flush=True)


if __name__ == "__main__":
    main()
