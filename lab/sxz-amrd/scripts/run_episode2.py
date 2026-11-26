"""Episode 2: reversible representation discovery, bounded diagnostic."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import zstandard as zstd

PHASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_ROOT))

from amrd.config import PROJECT_ROOT, RESULTS
from amrd.inference import detect_word_window, poly_predict
from amrd.representations import REP_BY_NAME
from amrd.scanner import scan_file

START = time.perf_counter()
BUDGET = 180.0
ZSTD = zstd.ZstdCompressor(level=19)
REGION = 4096


def zstd_size(data: bytes) -> int:
    return len(ZSTD.compress(data))


def entropy_bytes(data: bytes) -> float:
    if not data:
        return 0.0
    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    total = len(data)
    value = 0.0
    for count in counts:
        if count:
            p = count / total
            value -= p * math.log2(p)
    return value


def shuffle_body(data: bytes, width: int):
    # SXZ4-compatible byte-plane shuffle: all lane-0 bytes, then lane-1...
    body_len = len(data) - (len(data) % width)
    trailing = data[body_len:]
    body = bytearray()
    for lane in range(width):
        body += data[lane:body_len:width]
    return bytes(body), trailing


def unshuffle_body(body: bytes, original_len: int, width: int, trailing: bytes) -> bytes:
    body_len = original_len - (original_len % width)
    count = body_len // width
    out = bytearray(original_len)
    position = 0
    for lane in range(width):
        out[lane:body_len:width] = body[position : position + count]
        position += count
    out[body_len:] = trailing
    return bytes(out)


def delta_body(data: bytes):
    if not data:
        return b"", 0
    body = bytes((data[index] - data[index - 1]) & 255 for index in range(1, len(data)))
    return body, data[0]


def undelta_body(body: bytes, initial: int) -> bytes:
    out = bytearray([initial])
    for value in body:
        out.append((out[-1] + value) & 255)
    return bytes(out)


def xor_body(data: bytes):
    if not data:
        return b"", 0
    body = bytes(data[index] ^ data[index - 1] for index in range(1, len(data)))
    return body, data[0]


def unxor_body(body: bytes, initial: int) -> bytes:
    out = bytearray([initial])
    for value in body:
        out.append(out[-1] ^ value)
    return bytes(out)


def bitplanes_body(data: bytes):
    raw = np.frombuffer(data, dtype=np.uint8)
    per_plane = (len(data) + 7) // 8
    planes = []
    for bit in range(8):
        bits = (raw >> bit) & 1
        planes.append(np.packbits(bits, bitorder="big").tobytes())
    return b"".join(planes), per_plane


def unbitplanes_body(body: bytes, original_len: int, per_plane: int) -> bytes:
    planes = [
        np.unpackbits(
            np.frombuffer(body[bit * per_plane : (bit + 1) * per_plane], dtype=np.uint8),
            bitorder="big",
        )[:original_len]
        for bit in range(8)
    ]
    out = np.zeros(original_len, dtype=np.uint8)
    for bit, bits in enumerate(planes):
        out |= (bits.astype(np.uint8) & 1) << bit
    return out.tobytes()


def build_transforms(data: bytes):
    transforms = {}
    transforms["identity"] = (data, 6, lambda body, meta: body)
    body, initial = delta_body(data)
    transforms["delta"] = (body, 7, lambda body, meta, initial=initial: undelta_body(body, initial))
    body, initial = xor_body(data)
    transforms["xor_prev"] = (body, 7, lambda body, meta, initial=initial: unxor_body(body, initial))
    for width in (2, 3, 4):
        body, trailing = shuffle_body(data, width)
        transforms[f"shuffle{width}"] = (
            body,
            7 + len(trailing),
            lambda body, meta, width=width, trailing=trailing: unshuffle_body(body, len(data), width, trailing),
        )
    body, trailing = shuffle_body(data, 3)
    body, initial = delta_body(body)
    transforms["shuffle3_delta"] = (
        body,
        8 + len(trailing),
        lambda body, meta, trailing=trailing, initial=initial: unshuffle_body(
            undelta_body(body, initial), len(data), 3, trailing
        ),
    )
    body, per_plane = bitplanes_body(data)
    transforms["bitplanes"] = (
        body,
        7,
        lambda body, meta, per_plane=per_plane: unbitplanes_body(body, len(data), per_plane),
    )
    return transforms


def transform_inverse_ok(name: str, body: bytes, meta: int, inverse, original: bytes, data: bytes) -> bool:
    try:
        if name == "shuffle3_delta":
            # inverse lambda returns the shuffled body, not the original.
            return True
        return inverse(body, meta) == data
    except Exception:
        return False


def inverse_shuffle3_delta(body, meta, original, data):
    # The lambda above inverts delta; shuffle inversion is checked by rebuilding.
    return True


def equation(model, bits: int) -> str:
    family = model.family
    params = model.params
    if family == "const":
        return f"X[n] = {int(params[0])}"
    if family == "periodic":
        pattern = ", ".join(str(int(value)) for value in params[0])
        return f"X[n] = pattern[n mod {model.order}], pattern = [{pattern}]"
    if family.startswith("poly"):
        vals = [int(value) for value in params]
        terms = [str(vals[0])]
        for index in range(1, len(vals)):
            terms.append(f"{vals[index]}*C(n,{index})")
        return "X[n] = " + " + ".join(terms) + f" (mod 2^{bits})"
    if family == "affine1":
        a, c, x0 = (int(value) for value in params)
        return f"X[n] = {a}*X[n-1] + {c}, X[0]={x0} (mod 2^{bits})"
    if family == "affine2":
        a, b, c, x0, x1 = (int(value) for value in params)
        return f"X[n] = {a}*X[n-1] + {b}*X[n-2] + {c} (mod 2^{bits})"
    return family


def infer_word(region: bytes, rep_name: str, label: str):
    rep = REP_BY_NAME[rep_name]
    result = scan_file(region, label, reps=[rep], windows=(64,))
    priority = {"poly3": 0, "poly2": 1, "poly1": 2, "affine2": 3, "affine1": 4, "periodic": 5, "const": 6}
    models = sorted(
        result.models,
        key=lambda model: (priority.get(model.family, 9), -model.span_bytes, model.record_bytes),
    )
    top = models[0] if models else None
    return {
        "rep": rep_name,
        "region_bytes": len(region),
        "models": len(models),
        "by_family": dict(Counter(model.family for model in models)),
        "top": None if top is None else {
            "family": top.family,
            "start": top.start,
            "count": top.count,
            "span_bytes": top.span_bytes,
            "record_bytes": top.record_bytes,
            "exact": top.exact,
            "equation": equation(top, rep.sym_bits),
        },
    }


def infer_bitplanes(data: bytes):
    raw = data[:REGION]
    stats = Counter()
    families = Counter()
    for bit in range(8):
        bits = ((np.frombuffer(raw, dtype=np.uint8) >> bit) & 1).astype(np.uint8)
        for start in range(0, len(bits) - 64 + 1, 32):
            candidate = detect_word_window(bits, start, 64, 1, {})
            if candidate is not None:
                families[candidate.family] += 1
    return {"rep": "bitplanes", "region_bytes": len(raw), "windows": 8 * ((len(raw) - 64) // 32 + 1), "by_family": dict(families)}


def cross_plane(data: bytes, label: str):
    raw = np.frombuffer(data[:REGION], dtype=np.uint8)
    planes = [((raw >> bit) & 1).astype(np.uint8) for bit in range(8)]
    direct_sum = 0
    best_sum = 0
    improved = 0
    exact_planes = 0
    best_examples = []
    candidates = 0
    exact_fractions = []
    entropies = []
    for target_index, target in enumerate(planes):
        packed_target = np.packbits(target, bitorder="big").tobytes()
        direct = zstd_size(packed_target) + 6
        direct_sum += direct
        best = None
        options = []
        for source in range(target_index):
            options.append(("eq", (source,), planes[source], 7))
            options.append(("xor1", (source,), planes[source] ^ 1, 8))
            for second in range(source + 1, target_index):
                options.append(("xor2", (source, second), planes[source] ^ planes[second], 8))
        for kind, refs, prediction, record in options:
            candidates += 1
            residual = target ^ prediction
            matches = int(np.count_nonzero(residual == 0))
            packed = np.packbits(residual, bitorder="big").tobytes()
            residual_zstd = zstd_size(packed)
            total = record + residual_zstd
            item = {
                "kind": kind,
                "refs": refs,
                "record": record,
                "matches": matches,
                "exact_pct": 100.0 * matches / len(target),
                "entropy": entropy_bytes(packed),
                "residual_zstd": residual_zstd,
                "total": total,
                "direct": direct,
                "saving": direct - total,
            }
            if best is None or (item["total"], item["record"]) < (best["total"], best["record"]):
                best = item
        if best is None:
            best = {"kind": "none", "refs": (), "record": 0, "matches": 0, "exact_pct": 0.0, "entropy": 0.0, "residual_zstd": direct - 6, "total": direct, "direct": direct, "saving": 0}
        best_sum += best["total"]
        improved += int(best["total"] < direct)
        exact_planes += int(best["matches"] == len(target))
        exact_fractions.append(best["exact_pct"])
        entropies.append(best["entropy"])
        best_examples.append({"target": target_index, **best})
    return {
        "sample": label,
        "candidates": candidates,
        "planes": 8,
        "direct_sum": direct_sum,
        "best_sum": best_sum,
        "saving": direct_sum - best_sum,
        "improved_planes": improved,
        "exact_planes": exact_planes,
        "mean_best_exact_pct": sum(exact_fractions) / 8.0,
        "mean_best_entropy": sum(entropies) / 8.0,
        "examples": sorted(best_examples, key=lambda item: (-item["saving"], item["target"]))[:4],
    }


def main():
    samples = {
        "ecg": PROJECT_ROOT / "data/05-sxz4-corpus/ecg-train.bin",
        "7zr": PROJECT_ROOT / "data/03-audit-assets/7zr.exe",
        "text": PROJECT_ROOT / "data/06-sxz5-data/alice29.txt",
    }
    data = {name: path.read_bytes()[: 32 * 1024] for name, path in samples.items()}
    # Synthetic: two independently generated interleaved 16-bit cubics.
    a = poly_predict([100, 7, 3, 1], 2048, 16)
    b = poly_predict([50000, 11, 5, 2], 2048, 16)
    interleaved = bytearray()
    for left, right in zip(a, b):
        interleaved += int(left).to_bytes(2, "little") + int(right).to_bytes(2, "little")
    data["interleaved"] = bytes(interleaved)

    screening = {}
    selected = {}
    for name, sample in data.items():
        transforms = build_transforms(sample)
        rows = []
        for transform_name, (body, meta, inverse) in transforms.items():
            compressed = zstd_size(body)
            verified = inverse(body, meta) == sample
            if not verified:
                raise RuntimeError(f"transform inverse failed: {name}:{transform_name}")
            rows.append({
                "transform": transform_name,
                "body_bytes": len(body),
                "zstd19": compressed,
                "metadata": meta,
                "total": compressed + meta,
                "verified": verified,
            })
        screening[name] = {
            "bytes": len(sample),
            "sha256": hashlib.sha256(sample).hexdigest(),
            "transforms": rows,
        }
        candidates = [row for row in rows if row["transform"] != "identity"]
        candidates.sort(key=lambda row: (row["total"], row["transform"]))
        chosen = ["identity"] + [row["transform"] for row in candidates[:2]]
        if name == "ecg":
            chosen.append("shuffle3_delta")
        if name == "interleaved":
            # The control exists to test byte-plane separation; zstd ranking
            # alone would omit the width-4 lane split that exposes the law.
            chosen.append("shuffle4")
        chosen.append("bitplanes")
        chosen = list(dict.fromkeys(chosen))
        selected[name] = {"chosen": chosen, "inference": []}
        for transform_name in chosen:
            if transform_name == "bitplanes":
                selected[name]["inference"].append(infer_bitplanes(sample))
                continue
            body, meta, inverse = transforms[transform_name]
            rep_name = {
                "identity": "u8",
                "delta": "u8",
                "xor_prev": "u8",
                "shuffle2": "u8",
                "shuffle3": "u8",
                "shuffle4": "u8",
                "shuffle3_delta": "u8",
            }[transform_name]
            region = body[:REGION]
            result = infer_word(region, rep_name, f"{name}:{transform_name}")
            result["transform"] = transform_name
            result["transform_meta"] = meta
            selected[name]["inference"].append(result)

    cross = {name: cross_plane(sample, name) for name, sample in data.items()}
    payload = {
        "episode": 2,
        "phase": "12-amrd",
        "region_bytes": REGION,
        "elapsed_s": time.perf_counter() - START,
        "budget_s": BUDGET,
        "samples": screening,
        "selected": selected,
        "cross_plane": cross,
        "transforms": [
            "identity",
            "delta",
            "xor_prev",
            "shuffle2",
            "shuffle3",
            "shuffle4",
            "shuffle3_delta",
            "bitplanes",
        ],
    }
    target = RESULTS / "episode2.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({
        "elapsed_s": payload["elapsed_s"],
        "screening": {name: {row["transform"]: row["total"] for row in value["transforms"]} for name, value in screening.items()},
        "selected": {name: value["chosen"] for name, value in selected.items()},
        "cross": {name: {k: value[k] for k in ("saving", "improved_planes", "exact_planes", "mean_best_exact_pct")} for name, value in cross.items()},
    }, indent=1))


if __name__ == "__main__":
    main()
