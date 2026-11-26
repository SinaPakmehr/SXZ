"""Phase 15 Episode 3: compositional coordinate-function networks (bounded)."""

from __future__ import annotations

import io
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import zstandard as zstd
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "lab" / "sxz-image-math"))
from run_phase15 import image_pixels, spatial_prediction

START = time.perf_counter()
BUDGET = 180.0
Z9 = zstd.ZstdCompressor(level=9)
SCALE = 4096
MAX_FEATURES = 8


def zsize(data: bytes) -> int:
    return len(Z9.compress(data)) if data else 0


def base_defs():
    return [
        {"name": "const", "op": "const"},
        {"name": "x", "op": "coord"}, {"name": "y", "op": "coord"},
        {"name": "x2", "op": "square", "refs": ["x"]},
        {"name": "y2", "op": "square", "refs": ["y"]},
        {"name": "xy", "op": "mul", "refs": ["x", "y"]},
        {"name": "sinx1", "op": "sin", "refs": ["x"], "f": 1},
        {"name": "cosx1", "op": "cos", "refs": ["x"], "f": 1},
        {"name": "siny1", "op": "sin", "refs": ["y"], "f": 1},
        {"name": "cosy1", "op": "cos", "refs": ["y"], "f": 1},
        {"name": "sinx2", "op": "sin", "refs": ["x"], "f": 2},
        {"name": "cosx2", "op": "cos", "refs": ["x"], "f": 2},
        {"name": "siny2", "op": "sin", "refs": ["y"], "f": 2},
        {"name": "cosy2", "op": "cos", "refs": ["y"], "f": 2},
        {"name": "absx", "op": "abs", "refs": ["x"]},
        {"name": "absy", "op": "abs", "refs": ["y"]},
    ]


def extra_defs():
    return [
        {"name": "sinxy", "op": "mul", "refs": ["sinx1", "y"]},
        {"name": "cosx_absy", "op": "mul", "refs": ["cosx1", "absy"]},
        {"name": "absxy", "op": "mul", "refs": ["absx", "absy"]},
        {"name": "minxy", "op": "min", "refs": ["x", "y"]},
        {"name": "maxxy", "op": "max", "refs": ["x", "y"]},
        {"name": "threshx", "op": "threshold", "refs": ["x"], "t": 0.0},
        {"name": "threshy", "op": "threshold", "refs": ["y"], "t": 0.0},
        {"name": "sinx_cosy", "op": "mul", "refs": ["sinx1", "cosy1"]},
        {"name": "sinx2_cosy2", "op": "mul", "refs": ["sinx2", "cosy2"]},
        {"name": "abs_xy", "op": "abs", "refs": ["xy"]},
        {"name": "sin_sum", "op": "sin_sum", "refs": ["x", "y"], "f": 1},
        {"name": "cos_diff", "op": "cos_diff", "refs": ["x", "y"], "f": 1},
    ]


def make_features(h, w):
    y, x = np.mgrid[0:h, 0:w]
    x = 2.0 * x / max(1, w - 1) - 1.0
    y = 2.0 * y / max(1, h - 1) - 1.0
    f = {
        "const": np.ones((h, w)),
        "x": x, "y": y,
        "x2": x * x, "y2": y * y, "xy": x * y,
        "sinx1": np.sin(math.pi * x), "cosx1": np.cos(math.pi * x),
        "siny1": np.sin(math.pi * y), "cosy1": np.cos(math.pi * y),
        "sinx2": np.sin(2 * math.pi * x), "cosx2": np.cos(2 * math.pi * x),
        "siny2": np.sin(2 * math.pi * y), "cosy2": np.cos(2 * math.pi * y),
        "absx": np.abs(x), "absy": np.abs(y),
        "sinxy": np.sin(math.pi * x) * y,
        "cosx_absy": np.cos(math.pi * x) * np.abs(y),
        "absxy": np.abs(x) * np.abs(y),
        "minxy": np.minimum(x, y), "maxxy": np.maximum(x, y),
        "threshx": (x >= 0).astype(np.float64), "threshy": (y >= 0).astype(np.float64),
        "sinx_cosy": np.sin(math.pi * x) * np.cos(math.pi * y),
        "sinx2_cosy2": np.sin(2 * math.pi * x) * np.cos(2 * math.pi * y),
        "abs_xy": np.abs(x * y),
        "sin_sum": np.sin(math.pi * (x + y)),
        "cos_diff": np.cos(math.pi * (x - y)),
    }
    return f


def fit(pixels, features, names):
    h, w, c = pixels.shape
    A = np.stack([features[name].ravel() for name in names], axis=1)
    Y = pixels.reshape(-1, c).astype(np.float64)
    step = max(1, len(Y) // 100000)
    As = A[::step]
    Ys = Y[::step]
    weights = []
    preds = []
    for ch in range(c):
        coef, *_ = np.linalg.lstsq(As, Ys[:, ch], rcond=None)
        q = np.rint(coef * SCALE).astype(np.int64)
        weights.append(q.tolist())
        preds.append(np.rint((A @ q) / SCALE))
    pred = np.stack([np.clip(p, 0, 255) for p in preds], axis=1).reshape(h, w, c)
    residual = ((pixels.astype(np.int16) - pred.astype(np.int16)) & 255).astype(np.uint8)
    return weights, pred.astype(np.uint8), residual


def blob_for(names, defs_by_name, weights, h, w, c):
    payload = {
        "nodes": [defs_by_name[name] for name in names],
        "weights": weights,
        "h": int(h), "w": int(w), "c": int(c),
    }
    return json.dumps(payload, separators=(",", ":")).encode()


def spatial_residual(residual):
    h, w, c = residual.shape
    left = np.empty_like(residual)
    for ch in range(c):
        y = residual[:, :, ch]
        left[:, 0, ch] = y[:, 0]
        left[:, 1:, ch] = (y[:, 1:].astype(np.int16) - y[:, :-1]) & 255
    return left.tobytes()


def select(pixels, features, defs, candidates):
    h, w, c = pixels.shape
    selected = ["const"]
    best = None
    while len(selected) < MAX_FEATURES:
        trial = None
        for name in candidates:
            if name in selected:
                continue
            names = selected + [name]
            weights, pred, residual = fit(pixels, features, names)
            blob = blob_for(names, defs, weights, h, w, c)
            residual_bytes = residual.tobytes()
            cost = len(blob) + zsize(residual_bytes) + 16
            if trial is None or cost < trial[0]:
                trial = (cost, name, names, weights, pred, residual, blob)
        if trial is None or (best is not None and trial[0] >= best[0]):
            break
        best = trial
        selected = trial[2]
    if best is None:
        weights, pred, residual = fit(pixels, features, selected)
        blob = blob_for(selected, defs, weights, h, w, c)
        cost = len(blob) + zsize(residual.tobytes()) + 16
        best = (cost, selected[-1], selected, weights, pred, residual, blob)
    return best


def decode_network(blob, features, pixels_shape, residual_blob, spatial_mode):
    payload = json.loads(blob.decode("utf8"))
    names = [node["name"] for node in payload["nodes"]]
    h, w, c = pixels_shape
    A = np.stack([features[name].ravel() for name in names], axis=1)
    weights = payload["weights"]
    pred = np.stack([np.clip(np.rint((A @ np.array(weights[ch])) / SCALE), 0, 255) for ch in range(c)], axis=1).reshape(h, w, c)
    residual = np.frombuffer(zstd.ZstdDecompressor().decompress(residual_blob), dtype=np.uint8).reshape(h, w, c)
    if spatial_mode:
        # Inverse left predictor for each channel.
        decoded = np.empty_like(residual)
        for ch in range(c):
            for y in range(h):
                decoded[y, 0, ch] = residual[y, 0, ch]
                for x in range(1, w):
                    decoded[y, x, ch] = (int(decoded[y, x - 1, ch]) + int(residual[y, x, ch])) & 255
        residual = decoded
    return (pred.astype(np.int16) + residual.astype(np.int16) & 255).astype(np.uint8)


def evaluate_image(pixels, use_full):
    h, w, c = pixels.shape
    features = make_features(h, w)
    base = base_defs()
    full = base + extra_defs()
    defs_by_name = {node["name"]: node for node in full}
    candidates = [node["name"] for node in (full if use_full else base) if node["name"] != "const"]
    cost, last, names, weights, pred, residual, blob = select(pixels, features, defs_by_name, candidates)
    # Direct residual.
    direct = residual.tobytes()
    direct_cost = len(blob) + zsize(direct) + 16
    # Spatially predicted residual.
    sp = spatial_residual(residual)
    sp_cost = len(blob) + zsize(sp) + 1 + 16
    if sp_cost < direct_cost:
        mode = "spatial"
        residual_blob = Z9.compress(sp)
        total = sp_cost
    else:
        mode = "direct"
        residual_blob = Z9.compress(direct)
        total = direct_cost
    # Decode from the serialized blob and compressed residual.
    rec = decode_network(blob, features, pixels.shape, residual_blob, mode == "spatial")
    exact = int(np.count_nonzero(residual == 0))
    return {
        "cost": int(total),
        "nodes": len(names),
        "selected": names,
        "blob_bytes": len(blob),
        "residual_bytes": len(direct),
        "residual_zstd": len(residual_blob),
        "residual_mode": mode,
        "network_exact_pixels": exact,
        "total_pixels": pixels.size,
        "verified": bool(np.array_equal(rec, pixels)),
        "weights": weights,
        "blob": blob.decode("utf8"),
    }


def png_size(pixels):
    buf = io.BytesIO()
    Image.fromarray(pixels[:, :, 0] if pixels.shape[2] == 1 else pixels).save(buf, format="PNG", optimize=True, compress_level=9)
    return len(buf.getvalue())


def main():
    files = [
        ("banana", "natural", "JPEG", "data/06-sxz5-data/raw/banana.jpg", False),
        ("gull", "natural", "JPEG", "data/06-sxz5-data/raw/gull.jpg", False),
        ("python-logo", "graphics", "PNG", "phases/07-next/python-logo.png", True),
        ("transparency", "graphics", "BMP", "data/06-sxz5-data/corpus/transparency.bmp", True),
        ("exif", "screenshot/document", "PNG", "phases/07-next/exif.png", True),
        ("fig1_class_hits", "screenshot/document", "PNG", "phases/11-cgmc/figures/fig1_class_hits.png", True),
    ]
    ep2 = json.loads((ROOT / "lab/sxz-image-math/results/phase15_ep2.json").read_text(encoding="utf8"))
    ep2_by_key = {item["key"]: item for item in ep2["files"]}
    payload = {"phase": 15, "episode": 3, "max_features": MAX_FEATURES, "files": []}
    for key, category, fmt, relative, complete in files:
        path = ROOT / relative
        im, pixels, mode, orig_size, cropped, box = image_pixels(path, crop=256 if key != "python-logo" else None)
        pixels = pixels.copy()
        D = evaluate_image(pixels, False)
        E = evaluate_image(pixels, True)
        A = len(Z9.compress(pixels.tobytes()))
        B, _ = spatial_prediction(pixels)
        F = png_size(pixels)
        old = ep2_by_key[key]
        entry = {
            "key": key, "category": category, "format": fmt,
            "tested_size": [int(pixels.shape[1]), int(pixels.shape[0])],
            "crop_box": list(box), "complete_crop": not cropped,
            "A_zstd9": A, "B_spatial": B, "C_ep2_adaptive": old["C_adaptive"]["cost"],
            "D_linear_features": D, "E_compositional": E, "F_png": F,
            "complete_image": None,
        }
        if complete:
            full = image_pixels(path, crop=None)[1].copy()
            entry["complete_image"] = {
                "size": [int(full.shape[1]), int(full.shape[0])],
                "A_zstd9": len(Z9.compress(full.tobytes())),
                "B_spatial": spatial_prediction(full)[0],
                "F_png": png_size(full),
                "D": evaluate_image(full, False),
                "E": evaluate_image(full, True),
            }
        payload["files"].append(entry)
        print(f"{key}: D={D['cost']} E={E['cost']} A={A} B={B} C={old['C_adaptive']['cost']} F={F} verified={E['verified']}", flush=True)
    payload["elapsed_s"] = time.perf_counter() - START
    target = ROOT / "lab/sxz-image-math/results/phase15_ep3.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({"elapsed_s": payload["elapsed_s"], "files": [{"key": e["key"], "D": e["D_linear_features"]["cost"], "E": e["E_compositional"]["cost"], "A": e["A_zstd9"], "C": e["C_ep2_adaptive"]} for e in payload["files"]]}, indent=1))


if __name__ == "__main__":
    main()
