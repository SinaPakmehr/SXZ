"""Episode 3: real-file cross-plane representation optimization (bounded)."""

from __future__ import annotations

import hashlib
import json
import lzma
import math
import sys
import time
from collections import Counter
from itertools import permutations
from pathlib import Path

import numpy as np
import zstandard as zstd

PHASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_ROOT))

from amrd.config import PROJECT_ROOT, RESULTS
from amrd.inference import detect_word_window
from amrd.representations import REP_BY_NAME
from amrd.scanner import scan_file
from scripts.run_episode2 import (
    build_transforms,
    equation,
    infer_bitplanes,
    infer_word,
    zstd_size,
)

START = time.perf_counter()
BUDGET = 180.0
REGION = 16384
SCREEN = 4096
ZSTD = zstd.ZstdCompressor(level=19)
ZDEC = zstd.ZstdDecompressor()


def bits(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.uint8)


def apply_cross(data: bytes, ops: tuple) -> bytes:
    array = np.frombuffer(data, dtype=np.uint8).copy()
    for target, source1, source2 in ops:
        source = (array >> source1) & 1
        if source2 >= 0:
            source ^= (array >> source2) & 1
        array ^= (source & 1) << target
    return array.tobytes()


def inverse_cross(data: bytes, ops: tuple) -> bytes:
    return apply_cross(data, tuple(reversed(ops)))


def cross_meta(ops: tuple) -> int:
    return 4 + 3 * len(ops)


def op_name(op: tuple) -> str:
    target, source1, source2 = op
    if source2 < 0:
        return f"bit{target}<-bit{source1}"
    return f"bit{target}<-bit{source1}^bit{source2}"


def all_ops():
    singles = [(target, source, -1) for target in range(8) for source in range(8) if target != source]
    pairs = [
        (target, source1, source2)
        for target in range(8)
        for source1 in range(8)
        for source2 in range(source1 + 1, 8)
        if source1 != target and source2 != target
    ]
    return singles + pairs


def sample_files():
    return [
        ("txt", "data/06-sxz5-data/book1", "TXT"),
        ("json", "phases/11-cgmc/data/slices/linux-tree-1m.bin", "JSON/XML"),
        ("exe", "data/03-audit-assets/7zr.exe", "EXE"),
        ("pdf", "data/06-sxz5-data/raw/irs1040.pdf", "PDF"),
        ("bmp", "phases/09-msmc/hopper.bmp", "BMP"),
        ("ecg", "data/05-sxz4-corpus/ecg-holdout.bin", "ECG"),
        ("png", "data/06-sxz5-data/raw/transparency.png", "JPEG/PNG"),
        ("docx", "data/06-sxz5-data/raw/docx-images.docx", "DOCX/ZIP"),
    ]


def lane_scan(data: bytes, width: int, factor: int):
    dtype = np.dtype("<u2") if width == 2 else np.dtype("<u4")
    limit = (min(len(data), SCREEN) // width) * width
    words = np.frombuffer(data[:limit], dtype=dtype)
    stats = Counter()
    examples = []
    for lane in range(factor):
        lane_words = words[lane::factor]
        if len(lane_words) < 64:
            continue
        for start in range(0, len(lane_words) - 64 + 1, 32):
            candidate = detect_word_window(lane_words, start, 64, width * 8, {})
            if candidate is None:
                continue
            stats[candidate.family] += 1
            if candidate.family in {"poly1", "poly2", "poly3", "affine1", "affine2"} and len(examples) < 4:
                examples.append({"lane": lane, "start": start, "family": candidate.family})
    return {"width": width, "factor": factor, "by_family": dict(stats), "examples": examples}


def nontrivial_models(result):
    keep = []
    for model in result.models:
        if model.family in {"poly1", "poly2", "poly3", "affine1", "affine2"}:
            keep.append({
                "family": model.family,
                "start": model.start,
                "count": model.count,
                "span_bytes": model.span_bytes,
                "record_bytes": model.record_bytes,
                "equation": equation(model, REP_BY_NAME[model.rep].sym_bits),
                "exact": model.exact,
            })
    return keep


def main():
    ops_all = all_ops()
    files = sample_files()
    results = []
    total_evaluated = 0
    total_verified = 0
    total_encode_s = 0.0
    total_decode_s = 0.0
    for key, relative, category in files:
        path = PROJECT_ROOT / relative
        raw = path.read_bytes()
        sample = raw[: 64 * 1024]
        complete = len(raw) <= 64 * 1024
        dev_screen = sample[:SCREEN]
        dev_eval = sample[:REGION]
        val = sample[REGION : 2 * REGION]
        if len(val) < 1024:
            val = sample[-REGION:]
        transform_sets = {
            "dev": build_transforms(dev_eval),
            "val": build_transforms(val),
            "screen": build_transforms(dev_screen),
        }
        # Screen all 56 directed pairs plus the inexpensive two-source pairs.
        ranked = []
        for op in ops_all:
            body = apply_cross(dev_screen, (op,))
            ranked.append((zstd_size(body) + cross_meta((op,)), op))
        ranked.sort(key=lambda item: (item[0], op_name(item[1])))
        retained = [op for _, op in ranked[:3]]
        # Compose up to three retained primitives, preserving order.
        compositions = [(op,) for op in retained]
        for length in (2, 3):
            compositions.extend(permutations(retained, length))
        composed = []
        for ops in compositions:
            body = apply_cross(dev_eval, tuple(ops))
            composed.append((zstd_size(body) + cross_meta(tuple(ops)), tuple(ops)))
        composed.sort(key=lambda item: (item[0], tuple(op_name(op) for op in item[1])))
        best_ops = composed[0][1]

        # Evaluate the frozen rule on the non-overlapping validation region.
        base_names = ["identity", "bitplanes", "shuffle2", "shuffle3", "shuffle4", "delta", "shuffle3_delta"]
        base_rows = []
        for base in base_names:
            body, meta, inverse = transform_sets["val"][base]
            base_rows.append({
                "base": base,
                "order": "base",
                "total": zstd_size(body) + meta,
                "body_bytes": len(body),
                "meta": meta,
                "verified": inverse(body, meta) == val,
                "output": body,
            })
        direct_zstd19 = zstd_size(val)
        direct_lzma2 = len(lzma.compress(val, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME))
        base_best = min(base_rows, key=lambda row: row["total"])

        combo_rows = []
        seen = set()
        for base in base_names:
            # base -> cross
            body, meta, inverse = transform_sets["val"][base]
            out = apply_cross(body, best_ops)
            digest = hashlib.sha256(out).hexdigest() + f":{meta}:{cross_meta(best_ops)}"
            if digest not in seen:
                seen.add(digest)
                reconstructed = inverse(inverse_cross(out, best_ops), meta)
                combo_rows.append({
                    "base": base,
                    "order": "base_cross",
                    "total": zstd_size(out) + meta + cross_meta(best_ops) + 1,
                    "meta": meta + cross_meta(best_ops) + 1,
                    "verified": reconstructed == val,
                    "output": out,
                })
            # cross -> base
            cross_data = apply_cross(val, best_ops)
            base2 = build_transforms(cross_data)[base]
            body2, meta2, inverse2 = base2
            out2 = body2
            digest2 = hashlib.sha256(out2).hexdigest() + f":{meta2}:{cross_meta(best_ops)}"
            if digest2 not in seen:
                seen.add(digest2)
                reconstructed2 = inverse_cross(inverse2(out2, meta2), best_ops)
                combo_rows.append({
                    "base": base,
                    "order": "cross_base",
                    "total": zstd_size(out2) + meta2 + cross_meta(best_ops) + 1,
                    "meta": meta2 + cross_meta(best_ops) + 1,
                    "verified": reconstructed2 == val,
                    "output": out2,
                })
        for row in base_rows:
            total_evaluated += 1
            total_verified += int(row["verified"])
        for row in combo_rows:
            total_evaluated += 1
            total_verified += int(row["verified"])
        new_best = min(combo_rows, key=lambda row: row["total"])
        base_with_overhead = base_best["total"] + 1
        new_with_overhead = new_best["total"]
        saving = base_with_overhead - new_with_overhead
        relative_saving = saving / base_with_overhead if base_with_overhead else 0.0
        # Direct discovery on the two best validation representations.
        all_candidates = base_rows + combo_rows
        top_two = sorted(all_candidates, key=lambda row: row["total"])[:2]
        discovery = []
        for candidate in top_two:
            out = candidate["output"]
            word = infer_word(out[:4096], "u8", f"{key}:{candidate['base']}:{candidate['order']}")
            laws = nontrivial_models(scan_file(out[:4096], "law", reps=[REP_BY_NAME["u8"]], windows=(64,))) if False else []
            # Reuse the word result's consolidated models directly.
            raw_result = scan_file(out[:4096], "law", reps=[REP_BY_NAME["u8"]], windows=(64,))
            laws = nontrivial_models(raw_result)
            lanes = [lane_scan(out, width, factor) for width in (2, 4) for factor in (2, 3)]
            discovery.append({
                "base": candidate["base"],
                "order": candidate["order"],
                "total": candidate["total"],
                "word_models": word["models"],
                "nontrivial": laws,
                "lanes": lanes,
            })
        # Encoding/decoding time for the selected new rule.
        encode_start = time.perf_counter()
        encoded_body = apply_cross(val, best_ops)
        compressed = ZSTD.compress(encoded_body)
        encode_s = time.perf_counter() - encode_start
        decode_start = time.perf_counter()
        decoded_body = ZDEC.decompress(compressed)
        decoded = inverse_cross(decoded_body, best_ops)
        decode_s = time.perf_counter() - decode_start
        total_encode_s += encode_s
        total_decode_s += decode_s
        results.append({
            "key": key,
            "category": category,
            "path": relative,
            "original_bytes": len(raw),
            "sample_bytes": len(sample),
            "complete": complete,
            "sha256_sample": hashlib.sha256(sample).hexdigest(),
            "dev_bytes": len(dev_eval),
            "val_bytes": len(val),
            "retained": [op_name(op) for op in retained],
            "best_ops": [op_name(op) for op in best_ops],
            "best_cross_meta": cross_meta(best_ops),
            "direct_zstd19": direct_zstd19,
            "direct_lzma2": direct_lzma2,
            "base_best": {"base": base_best["base"], "total": base_with_overhead},
            "base_lzma2": len(lzma.compress(base_best["output"], format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME)) + base_best["meta"] + 1,
            "new_best": {"base": new_best["base"], "order": new_best["order"], "total": new_with_overhead},
            "new_lzma2": len(lzma.compress(new_best["output"], format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME)) + new_best["meta"],
            "saving": saving,
            "relative_saving": relative_saving,
            "success": saving >= 128 and relative_saving >= 0.01,
            "verified": total_verified == total_evaluated,
            "discovery": discovery,
            "encode_s": encode_s,
            "decode_s": decode_s,
            "encode_mb_s": len(val) / (1 << 20) / encode_s if encode_s else 0.0,
            "decode_mb_s": len(val) / (1 << 20) / decode_s if decode_s else 0.0,
        })
        print(
            f"{key}: base={base_best['base']} {base_with_overhead} new={new_best['base']}/{new_best['order']} "
            f"{new_with_overhead} saving={saving} ({100*relative_saving:.2f}%) ops={len(best_ops)}",
            flush=True,
        )
    payload = {
        "episode": 3,
        "phase": "12-amrd",
        "region_bytes": REGION,
        "screen_bytes": SCREEN,
        "elapsed_s": time.perf_counter() - START,
        "budget_s": BUDGET,
        "files": results,
        "total_evaluated_representations": total_evaluated,
        "total_verified_representations": total_verified,
        "success_files": sum(1 for item in results if item["success"]),
        "encode_s": total_encode_s,
        "decode_s": total_decode_s,
    }
    target = RESULTS / "episode3.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({
        "elapsed_s": payload["elapsed_s"],
        "success_files": payload["success_files"],
        "verified": f"{total_verified}/{total_evaluated}",
        "files": [{"key": item["key"], "base_best": item["base_best"], "new_best": item["new_best"], "saving": item["saving"], "relative": item["relative_saving"], "ops": item["best_ops"]} for item in results],
    }, indent=1))


if __name__ == "__main__":
    main()
