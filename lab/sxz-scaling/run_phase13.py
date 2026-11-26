"""Phase 13 Episode 1: scaling and mathematical cost diagnostics (bounded)."""

from __future__ import annotations

import json
import lzma
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import zstandard as zstd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lab" / "sxz-next-research"))
sys.path.insert(0, str(ROOT / "lab" / "sxz-amrd"))

from accelerate import output, scan_native
from amrd.representations import REP_BY_NAME
from amrd.scanner import scan_file

START = time.perf_counter()
BUDGET = 180.0
SIZES = [64 << 10, 1 << 20, 8 << 20, 32 << 20, 100 << 20]
NATIVE_CAP = 50000
Z9 = zstd.ZstdCompressor(level=9)
Z19 = zstd.ZstdCompressor(level=19)
SAMPLE = 32 << 10


def zsize(data: bytes, level: int) -> int:
    return len((Z9 if level == 9 else Z19).compress(data))


def lzma_size(data: bytes) -> int:
    return len(lzma.compress(data, format=lzma.FORMAT_XZ, preset=9 | lzma.PRESET_EXTREME))


def merge_coverage(hits, n: int):
    intervals = sorted((pos, min(n, pos + length)) for pos, length, *_ in hits)
    covered = 0
    end = 0
    for begin, stop in intervals:
        if stop <= end:
            continue
        covered += stop - max(begin, end)
        end = stop
    return covered


def bucket(length: int) -> str:
    if length < 16:
        return "8-15"
    if length < 32:
        return "16-31"
    if length < 64:
        return "32-63"
    if length < 256:
        return "64-255"
    if length < 1024:
        return "256-1023"
    return "1024+"


def verify_hits(data: bytes, hits):
    verified = 0
    for pos, length, a, b, c, x, y in hits:
        generated = output("rec2", length, a, b, c, x, y)
        if generated == data[pos : pos + length]:
            verified += 1
    return verified


def fast_delta(data: bytes) -> bytes:
    array = np.frombuffer(data, dtype=np.uint8)
    if len(array) < 2:
        return b""
    out = np.empty(len(array), dtype=np.uint8)
    out[0] = array[0]
    out[1:] = (array[1:] - array[:-1]) & 255
    return out.tobytes()


def fast_shuffle(data: bytes, width: int):
    body_len = len(data) - len(data) % width
    body = b"".join(data[lane:body_len:width] for lane in range(width))
    return body, data[body_len:]


def fast_bitplanes(data: bytes) -> bytes:
    raw = np.frombuffer(data, dtype=np.uint8)
    return b"".join(np.packbits((raw >> bit) & 1, bitorder="big").tobytes() for bit in range(8))


def inverse_delta(body: bytes) -> bytes:
    arr = np.frombuffer(body, dtype=np.uint8)
    out = np.empty(len(arr), dtype=np.uint8)
    out[0] = arr[0]
    out[1:] = (np.cumsum(arr[1:], dtype=np.uint64) + arr[0]) & 255
    return out.tobytes()


def inverse_shuffle(body: bytes, original_len: int, width: int, trailing: bytes) -> bytes:
    body_len = original_len - original_len % width
    count = body_len // width
    out = bytearray(original_len)
    pos = 0
    for lane in range(width):
        out[lane:body_len:width] = body[pos : pos + count]
        pos += count
    out[body_len:] = trailing
    return bytes(out)


def inverse_bitplanes(body: bytes, original_len: int) -> bytes:
    per_plane = (original_len + 7) // 8
    out = np.zeros(original_len, dtype=np.uint8)
    for bit in range(8):
        plane = np.unpackbits(
            np.frombuffer(body[bit * per_plane : (bit + 1) * per_plane], dtype=np.uint8),
            bitorder="big",
        )[:original_len]
        out |= (plane & 1) << bit
    return out.tobytes()


def transform_control(data: bytes):
    candidates = []
    candidates.append(("identity", data, 6, data))
    delta_body = fast_delta(data)
    candidates.append(("delta", delta_body, 7, inverse_delta(delta_body)))
    for width in (2, 3, 4):
        body, trailing = fast_shuffle(data, width)
        candidates.append(
            (
                f"shuffle{width}",
                body,
                7 + len(trailing),
                inverse_shuffle(body, len(data), width, trailing),
            )
        )
    body, trailing = fast_shuffle(data, 3)
    shuffled_delta = fast_delta(body)
    candidates.append(
        (
            "shuffle3_delta",
            shuffled_delta,
            8 + len(trailing),
            inverse_shuffle(inverse_delta(shuffled_delta), len(data), 3, trailing),
        )
    )
    planes = fast_bitplanes(data)
    candidates.append(("bitplanes", planes, 7, inverse_bitplanes(planes, len(data))))
    sizes = [
        (name, zsize(body, 9) + meta, meta, rebuilt == data)
        for name, body, meta, rebuilt in candidates
    ]
    sizes.sort(key=lambda item: (item[1], item[0]))
    return sizes[0]


def amrd_diagnostics(data: bytes, offset: int):
    sample = data[offset : offset + SAMPLE]
    if len(sample) < 4096:
        return None
    result = scan_file(
        sample,
        "sample",
        reps=[
            REP_BY_NAME["u8"],
            REP_BY_NAME["u16le"],
            REP_BY_NAME["u32le"],
            REP_BY_NAME["u64le"],
        ],
        windows=(16, 32, 64),
    )
    buckets = Counter()
    families = Counter()
    widths = Counter()
    nontrivial = 0
    record_cost = 0
    span_total = 0
    profitable_raw = 0
    profitable_z9 = 0
    for model in result.models:
        width = REP_BY_NAME[model.rep].sym_bits
        buckets[bucket(model.span_bytes)] += 1
        families[model.family] += 1
        widths[str(width)] += 1
        record_cost += model.record_bytes
        span_total += model.span_bytes
        if model.family not in {"const", "periodic"}:
            nontrivial += 1
        if model.record_bytes < model.span_bytes:
            profitable_raw += 1
        span = sample[model.start_byte : model.end_byte] if model.start_byte is not None else b""
        if span and model.record_bytes < zsize(span, 9):
            profitable_z9 += 1
    return {
        "offset": offset,
        "sample_bytes": len(sample),
        "models": len(result.models),
        "nontrivial": nontrivial,
        "families": dict(families),
        "widths": dict(widths),
        "buckets": dict(buckets),
        "record_cost": record_cost,
        "span_total": span_total,
        "profitable_raw": profitable_raw,
        "profitable_z9": profitable_z9,
        "elapsed_s": result.elapsed_s,
    }


def main():
    files = [
        ("enwik8", "text", ROOT / "datasets/06-compare-corpus/enwik8"),
        ("model-weights.bin", "binary", ROOT / "datasets/06-compare-corpus/model-weights.bin"),
        ("desktop-mixed.tar", "structured/multimedia", ROOT / "datasets/06-compare-corpus/desktop-mixed.tar"),
    ]
    payload = {"phase": 13, "episode": 1, "sizes": SIZES, "files": [], "budget_s": BUDGET}
    for key, family, path in files:
        raw = path.read_bytes()
        record = {"key": key, "family": family, "path": str(path.relative_to(ROOT)), "available": len(raw), "scales": []}
        for size in SIZES:
            if size > len(raw):
                continue
            if time.perf_counter() - START > BUDGET - 5:
                break
            data = raw[:size]
            t0 = time.perf_counter()
            hits, total_hits = scan_native(data, step=1, minimum=32, cap=NATIVE_CAP)
            scan_s = time.perf_counter() - t0
            coverage = merge_coverage(hits, len(data))
            verified = verify_hits(data, hits)
            records = 32 * len(hits)
            mask = np.ones(len(data), dtype=bool)
            for pos, length, *_ in hits:
                mask[pos : pos + length] = False
            literals = np.frombuffer(data, dtype=np.uint8)[mask].tobytes()
            a9 = zsize(data, 9)
            b = 16 + records + len(literals)
            c9 = 16 + records + zsize(literals, 9)
            entry = {
                "input_bytes": len(data),
                "native_hits": total_hits,
                "returned_hits": len(hits),
                "coverage_bytes": coverage,
                "coverage_fraction": coverage / len(data),
                "native_scan_s": scan_s,
                "verified_hits": verified,
                "records_bytes": records,
                "A_zstd9": a9,
                "B_math_only_estimate": b,
                "C_hybrid_zstd9_estimate": c9,
                "bucket_counts": dict(Counter(bucket(hit[1]) for hit in hits)),
            }
            if size <= 8 << 20:
                entry["A_zstd19"] = zsize(data, 19)
                entry["A_lzma2"] = lzma_size(data)
                entry["C_hybrid_zstd19_estimate"] = 16 + records + zsize(literals, 19)
            if size <= 1 << 20:
                t = transform_control(data)
                entry["transform_best"] = t[0]
                entry["transform_total"] = t[1]
                entry["transform_verified"] = t[3]
            record["scales"].append(entry)
            print(f"{key} {size>>10}K hits={total_hits} cov={coverage} A9={a9} B={b} C9={c9} t={scan_s:.2f}", flush=True)
        # Fixed 64 KiB AMRD sample for width/family diagnostics (not full scan).
        if record["scales"]:
            largest = SIZES[min(len(record["scales"]) - 1, len(SIZES) - 1)]
            if largest <= len(raw):
                offsets = [0, min(4 << 20, max(0, len(raw) - SAMPLE))]
                record["amrd_samples"] = [x for x in (amrd_diagnostics(raw, off) for off in offsets) if x]
        payload["files"].append(record)
        target = ROOT / "lab/sxz-scaling/results/phase13.json"
        target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    payload["elapsed_s"] = time.perf_counter() - START
    target = ROOT / "lab/sxz-scaling/results/phase13.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({"elapsed_s": payload["elapsed_s"]}, indent=1))


if __name__ == "__main__":
    main()
