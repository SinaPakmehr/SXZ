"""Phase 14 Episode 1: exact 2-adic rational description discovery."""

from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import zstandard as zstd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "lab" / "sxz-amrd"))

from amrd.inference import bm_fit

START = time.perf_counter()
BUDGET = 180.0
REGION = 16384 // 3
WINDOWS = (128, 512)
EXTEND = 8192
Z9 = zstd.ZstdCompressor(level=9)
Z19 = zstd.ZstdCompressor(level=19)


def uvarint(value: int) -> bytes:
    value = int(value)
    if value < 0:
        raise ValueError("unsigned varint")
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def zigzag(value: int) -> int:
    return value << 1 if value >= 0 else ((-value) << 1) - 1


def nearest_div(a: int, b: int) -> int:
    if b < 0:
        a, b = -a, -b
    return (2 * a + b) // (2 * b)


def gauss(v1, v2):
    if v1[0] * v1[0] + v1[1] * v1[1] > v2[0] * v2[0] + v2[1] * v2[1]:
        v1, v2 = v2, v1
    while True:
        norm = v1[0] * v1[0] + v1[1] * v1[1]
        mu = nearest_div(v1[0] * v2[0] + v1[1] * v2[1], norm)
        v2 = (v2[0] - mu * v1[0], v2[1] - mu * v1[1])
        if v2[0] * v2[0] + v2[1] * v2[1] >= norm:
            return v1, v2
        v1, v2 = v2, v1


def candidates(A: int, bits: int):
    M = 1 << bits
    v1, v2 = gauss((M, 0), (A, 1))
    vectors = {v1, v2}
    for u in range(-2, 3):
        for v in range(-2, 3):
            if u == 0 and v == 0:
                continue
            vectors.add((u * v1[0] + v * v2[0], u * v1[1] + v * v2[1]))
    found = {}
    for p, q in vectors:
        if q == 0 or q % 2 == 0:
            continue
        if q < 0:
            p, q = -p, -q
        if q == 1 or p == 0:
            continue
        if (p - A * q) % M:
            continue
        g = math.gcd(abs(p), q)
        p //= g
        q //= g
        if q % 2 == 0 or q == 1:
            continue
        found[(p, q)] = (p.bit_length() + q.bit_length(), p, q)
    return [found[key] for key in sorted(found, key=lambda key: found[key][0])[:8]]


def stream_bits(p: int, q: int, n: int):
    out = []
    for _ in range(n):
        bit = p & 1
        out.append(bit)
        p = (p - bit * q) // 2
    return out


def periodic(bits, maximum=64):
    for period in range(1, min(maximum, len(bits) // 2) + 1):
        if bits[period:] == bits[:-period]:
            return period
    return 0


def simple_repr(bits):
    """Cheapest prefix + period description with period <= 64."""
    best = None
    n = len(bits)
    for period in range(1, 65):
        for pre in range(0, n - period + 1):
            if pre == 0:
                ok = bits[period:] == bits[:-period]
            else:
                ok = bits[pre + period :] == bits[pre:-period]
            if ok:
                cost = pre + period
                if best is None or cost < best[0]:
                    best = (cost, pre, period)
                break
    return best


def record_size(p: int, q: int, span: int, position: int, rep: int) -> int:
    return (
        1
        + 1
        + len(uvarint(zigzag(p)))
        + len(uvarint(q))
        + len(uvarint(span))
        + len(uvarint(position))
        + 1
        + 1
        + 1
    )


def simple_size(kind: str, bits, span: int, position: int, rep: int):
    base = 1 + 1 + len(uvarint(span)) + len(uvarint(position)) + 1
    if kind == "const":
        return base + 1
    pattern = periodic(bits[:span]) or 1
    return base + 1 + (pattern + 7) // 8


def packed(bits):
    return np.packbits(np.asarray(bits, dtype=np.uint8), bitorder="little").tobytes()


def main():
    files = [
        ("book1", "TXT", ROOT / "datasets/06-sxz5-data/book1"),
        ("linux-tree.json", "XML", ROOT / "datasets/06-sxz5-data/raw/linux-tree.json"),
        ("7zr.exe", "EXE", ROOT / "datasets/03-audit-assets/7zr.exe"),
        ("irs1040.pdf", "PDF", ROOT / "datasets/06-sxz5-data/raw/irs1040.pdf"),
        ("hopper.bmp", "BMP", ROOT / "phases/09-msmc/hopper.bmp"),
        ("ecg-holdout.bin", "ECG", ROOT / "datasets/05-sxz4-corpus/ecg-holdout.bin"),
        ("transparency.png", "PNG", ROOT / "datasets/06-sxz5-data/raw/transparency.png"),
        ("docx-images.docx", "DOCX", ROOT / "datasets/06-sxz5-data/raw/docx-images.docx"),
    ]
    payload = {"phase": 14, "episode": 1, "windows": WINDOWS, "extend_bits": EXTEND, "files": []}
    total_windows = total_matches = 0
    total_models = 0
    total_verified = 0
    for key, category, path in files:
        if time.perf_counter() - START > BUDGET - 5:
            payload["partial"] = True
            break
        raw = path.read_bytes()
        offsets = [0, max(0, (len(raw) - REGION) // 2), max(0, len(raw) - REGION)]
        file_entry = {
            "key": key,
            "category": category,
            "path": str(path.relative_to(ROOT)),
            "bytes": len(raw),
            "regions": [],
            "models": [],
            "simple_bits": 0,
            "rational_bits": 0,
            "windows": 0,
        }
        for region_index, offset in enumerate(offsets):
            chunk = raw[offset : offset + REGION]
            raw_arr = np.frombuffer(chunk, dtype=np.uint8)
            sequences = [("packed", np.unpackbits(raw_arr, bitorder="little"))]
            for bit in range(8):
                sequences.append((f"bit{bit}", ((raw_arr >> bit) & 1).astype(np.uint8)))
            region_entry = {"offset": offset, "bytes": len(chunk), "sequences": {}}
            for rep_name, sequence in sequences:
                bits_list = sequence.tolist()
                seq_models = []
                simple_bits = 0
                simple_windows = 0
                for window in WINDOWS:
                    half = window // 2
                    for start in range(0, len(bits_list) - window + 1, window):
                        total_windows += 1
                        file_entry["windows"] += 1
                        window_bits = bits_list[start : start + window]
                        if max(window_bits) == min(window_bits):
                            simple_bits += window
                            simple_windows += 1
                            continue
                        if periodic(window_bits):
                            simple_bits += window
                            simple_windows += 1
                            continue
                        A = sum(window_bits[i] << i for i in range(half))
                        for _, p, q in candidates(A, half):
                            total_matches += 1
                            generated = stream_bits(p, q, window)
                            if generated != window_bits:
                                continue
                            limit = min(EXTEND, len(bits_list) - start)
                            extended = stream_bits(p, q, limit)
                            span = 0
                            for actual, want in zip(bits_list[start : start + limit], extended):
                                if actual != want:
                                    break
                                span += 1
                            if span < window:
                                continue
                            span_bits = bits_list[start : start + span]
                            if max(span_bits) == min(span_bits) or periodic(span_bits):
                                simple_bits += span
                                continue
                            record = record_size(p, q, span, start, 0)
                            seq_models.append(
                                {
                                    "rep": rep_name,
                                    "region": region_index,
                                    "offset": offset,
                                    "start": start,
                                    "span": span,
                                    "p": p,
                                    "q": q,
                                    "p_bits": p.bit_length(),
                                    "q_bits": q.bit_length(),
                                    "record_bytes": record,
                                }
                            )
                # Longest-first, non-overlapping dedup within this sequence/region.
                seq_models.sort(key=lambda item: (-item["span"], item["record_bytes"]))
                chosen = []
                occupied = []
                for model in seq_models:
                    a, b = model["start"], model["start"] + model["span"]
                    if any(not (b <= x or a >= y) for x, y in occupied):
                        continue
                    occupied.append((a, b))
                    chosen.append(model)
                for model in chosen:
                    total_models += 1
                    span_bits = bits_list[model["start"] : model["start"] + model["span"]]
                    pack = packed(span_bits)
                    model["raw_bytes"] = (model["span"] + 7) // 8
                    model["zstd9"] = len(Z9.compress(pack))
                    model["zstd19"] = len(Z19.compress(pack)) if model["record_bytes"] < model["zstd9"] else None
                    L, taps = bm_fit(span_bits)
                    model["bm_bits"] = L
                    model["bm_record"] = (2 * L + 7) // 8 + 8
                    simple = simple_repr(span_bits)
                    model["simple_pre"] = simple[1] if simple else None
                    model["simple_period"] = simple[2] if simple else None
                    model["simple_record"] = (
                        2
                        + len(uvarint(model["span"]))
                        + len(uvarint(model["start"]))
                        + 1
                        + ((simple[0] + 7) // 8)
                        if simple
                        else None
                    )
                    model["nontrivial"] = (
                        simple is None or model["record_bytes"] < model["simple_record"]
                    )
                    model["const_size"] = (
                        simple_size("const", span_bits, model["span"], model["start"], 0)
                        if max(span_bits) == min(span_bits)
                        else None
                    )
                    model["period_size"] = model["simple_record"]
                    model["D"] = (
                        model["record_bytes"] < model["raw_bytes"]
                        and model["record_bytes"] < model["zstd9"]
                    )
                    model["beats_bm"] = model["record_bytes"] < model["bm_record"]
                    model["verified"] = stream_bits(model["p"], model["q"], model["span"]) == span_bits
                    total_verified += int(model["verified"])
                    file_entry["models"].append(model)
                file_entry["simple_bits"] += simple_bits
                file_entry["rational_bits"] += sum(model["span"] for model in chosen if model["nontrivial"])
                region_entry["sequences"][rep_name] = {
                    "simple_bits": simple_bits,
                    "simple_windows": simple_windows,
                    "models": len(chosen),
                }
            file_entry["regions"].append(region_entry)
        payload["files"].append(file_entry)
        print(
            f"{key}: windows={file_entry['windows']} simple_bits={file_entry['simple_bits']} "
            f"rational_bits={file_entry['rational_bits']} models={len(file_entry['models'])}",
            flush=True,
        )
    payload["total_windows"] = total_windows
    payload["total_matches"] = total_matches
    payload["total_models"] = total_models
    payload["total_verified"] = total_verified
    payload["elapsed_s"] = time.perf_counter() - START
    target = ROOT / "lab/sxz-2adic/results/phase14.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({k: payload[k] for k in ("total_windows", "total_matches", "total_models", "total_verified", "elapsed_s")}, indent=1))


if __name__ == "__main__":
    main()
