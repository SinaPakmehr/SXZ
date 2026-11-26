"""Phase 15 Episode 2: adaptive hierarchical mathematical image representation."""

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
from run_phase15 import candidates, image_pixels, spatial_prediction

START = time.perf_counter()
BUDGET = 180.0
Z9 = zstd.ZstdCompressor(level=9)
MAX_NODES = 120
MIN_SIZE = 8


def zsize(data: bytes) -> int:
    return len(Z9.compress(data)) if data else 0


def family_key(candidate):
    return candidate[0], tuple(candidate[3]) if candidate[3] else None


def palette_model(pixels):
    h, w, c = pixels.shape
    colors, inverse = np.unique(pixels.reshape(-1, c), axis=0, return_inverse=True)
    if len(colors) > 64:
        return None
    indices = inverse.astype(np.uint8).tobytes()
    record = 10 + c * len(colors) + len(colors) * 2
    cost = record + zsize(indices) + 6
    rec = colors[inverse].reshape(h, w, c).astype(np.uint8)
    return {"kind": "palette", "cost": cost, "record": record, "residual": 0, "residual_zstd": 0, "exact": True, "rec": rec, "colors": len(colors)}


def shape_model(pixels):
    h, w, c = pixels.shape
    flat = pixels.reshape(-1, c)
    uniq, counts = np.unique(flat, axis=0, return_counts=True)
    if len(uniq) < 2:
        return None
    order = np.argsort(-counts)
    bg = uniq[order[0]]
    fg = uniq[order[1]]
    mask = np.all(pixels == fg, axis=2)
    ys, xs = np.where(mask)
    if len(xs) < 4:
        return None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    out = []
    Y, X = np.mgrid[0:h, 0:w]
    for kind in ("rect", "ellipse"):
        if kind == "rect":
            pred_mask = (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
        else:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            rx, ry = max(1, (x1 - x0 + 1) / 2), max(1, (y1 - y0 + 1) / 2)
            pred_mask = ((X - cx) / rx) ** 2 + ((Y - cy) / ry) ** 2 <= 1
        pred = np.empty_like(pixels)
        pred[:] = bg
        pred[pred_mask] = fg
        residual = ((pixels.astype(np.int16) - pred.astype(np.int16)) & 255).astype(np.uint8)
        record = 10 + 2 * c + 8
        cost = record + zsize(residual.tobytes()) + 6
        rec = (pred.astype(np.int16) + residual.astype(np.int16)) & 255
        out.append({"kind": kind, "cost": cost, "record": record, "residual": int(np.count_nonzero(residual)), "residual_zstd": zsize(residual.tobytes()), "exact": not residual.any(), "rec": rec.astype(np.uint8), "shape": (x0, x1, y0, y1)})
    return min(out, key=lambda item: item["cost"])


def leaf(pixels, allow_global):
    h, w, c = pixels.shape
    channel_candidates = []
    for ch in range(c):
        items = []
        Y = pixels[:, :, ch]
        for item in candidates(Y):
            residual = ((Y.astype(np.int64) - item[2]) % 256).astype(np.uint8)
            rb = residual.tobytes()
            items.append(item + (residual, rb, item[4] + zsize(rb)))
        channel_candidates.append(items)
    by_family = {}
    for ch, items in enumerate(channel_candidates):
        for item in items:
            key = family_key(item)
            by_family.setdefault(key, {})[ch] = item
    best = None
    for key, per_channel in by_family.items():
        if len(per_channel) != c:
            continue
        records = sum(item[4] for item in per_channel.values())
        rb = b"".join(item[7] for item in per_channel.values())
        cost = records + zsize(rb) + 6
        if best is None or cost < best["cost"]:
            pred = np.stack([per_channel[ch][2] for ch in range(c)], axis=2).astype(np.int64)
            res = np.stack([per_channel[ch][6] for ch in range(c)], axis=2)
            rec = (pred + res) & 255
            best = {"kind": "shared:" + key[0], "cost": cost, "record": records, "residual": len(rb), "residual_zstd": zsize(rb), "exact": not rb or not any(rb), "rec": rec.astype(np.uint8), "family": key[0]}
    # Per-channel mixed family candidate.
    chosen = [min(items, key=lambda item: item[8]) for items in channel_candidates]
    records = sum(item[4] for item in chosen)
    rb = b"".join(item[7] for item in chosen)
    cost = records + zsize(rb) + 6
    if best is None or cost < best["cost"]:
        pred = np.stack([item[2] for item in chosen], axis=2).astype(np.int64)
        res = np.stack([item[6] for item in chosen], axis=2)
        rec = (pred + res) & 255
        best = {"kind": "mixed", "cost": cost, "record": records, "residual": len(rb), "residual_zstd": zsize(rb), "exact": not rb or not any(rb), "rec": rec.astype(np.uint8), "family": "mixed"}
    if allow_global:
        for model in (palette_model(pixels), shape_model(pixels)):
            if model is not None and model["cost"] < best["cost"]:
                best = model
    # Literal and spatial fallback.
    literal = {"kind": "literal", "cost": zsize(pixels.tobytes()) + 6, "record": 0, "residual": pixels.nbytes, "residual_zstd": zsize(pixels.tobytes()), "exact": False, "rec": pixels.copy(), "family": "literal"}
    if literal["cost"] < best["cost"]:
        best = literal
    spatial, predictor = spatial_prediction(pixels)
    spatial_cost = spatial + 6
    if spatial_cost < best["cost"]:
        best = {"kind": "spatial", "cost": spatial_cost, "record": 0, "residual": len(pixels.tobytes()), "residual_zstd": spatial, "exact": False, "rec": pixels.copy(), "family": "spatial"}
    return best


def solve(pixels, allow_global, budget):
    h, w, c = pixels.shape
    if budget[0] <= 0:
        fallback = leaf(pixels, False)
        return fallback, [{"y": 0, "x": 0, "h": h, "w": w, "leaf": fallback}]
    budget[0] -= 1
    node = leaf(pixels, allow_global)
    if min(h, w) <= MIN_SIZE or budget[0] <= 0:
        return node, [{"y": 0, "x": 0, "h": h, "w": w, "leaf": node}]
    mh, mw = h // 2, w // 2
    if mh < MIN_SIZE or mw < MIN_SIZE:
        return node, [{"y": 0, "x": 0, "h": h, "w": w, "leaf": node}]
    children = []
    leaves = []
    cost = 6
    for top, bottom in ((0, mh), (mh, h)):
        for left, right in ((0, mw), (mw, w)):
            child, child_leaves = solve(pixels[top:bottom, left:right], allow_global, budget)
            cost += child["cost"]
            children.append(child)
            leaves.extend({"y": top + item["y"], "x": left + item["x"], "h": item["h"], "w": item["w"], "leaf": item["leaf"]} for item in child_leaves)
    if cost < node["cost"]:
        return {"kind": "split", "cost": cost, "record": 6, "residual": sum(ch["residual"] for ch in children), "exact": all(ch["exact"] for ch in children), "rec": None, "family": "split"}, leaves
    return node, [{"y": 0, "x": 0, "h": h, "w": w, "leaf": node}]


def assemble(leaves, h, w, c):
    out = np.zeros((h, w, c), dtype=np.uint8)
    for item in leaves:
        out[item["y"] : item["y"] + item["h"], item["x"] : item["x"] + item["w"]] = item["leaf"]["rec"]
    return out


def math_adaptive(pixels, allow_global):
    t0 = time.perf_counter()
    tree, leaves = solve(pixels, allow_global, [MAX_NODES])
    encode = time.perf_counter() - t0
    t0 = time.perf_counter()
    rec = assemble(leaves, *pixels.shape)
    decode = time.perf_counter() - t0
    exact_pixels = sum(item["leaf"]["rec"].size for item in leaves if item["leaf"]["exact"])
    total_pixels = pixels.size
    return {
        "cost": tree["cost"] + 16,
        "records": sum(item["leaf"]["record"] for item in leaves) + 16,
        "residual_zstd": sum(item["leaf"].get("residual_zstd", 0) for item in leaves),
        "leaves": len(leaves),
        "exact_pixels": exact_pixels,
        "total_channel_pixels": total_pixels,
        "exact_fraction": exact_pixels / total_pixels,
        "families": dict(Counter(item["leaf"]["family"] for item in leaves)),
        "verified": np.array_equal(rec, pixels),
        "encode_s": encode,
        "decode_s": decode,
        "examples": [{"family": item["leaf"]["family"], "y": item["y"], "x": item["x"], "h": item["h"], "w": item["w"], "exact": item["leaf"]["exact"], "record": item["leaf"]["record"], "residual_zstd": item["leaf"].get("residual_zstd", 0)} for item in leaves[:6]],
    }


def main():
    files = [
        ("banana", "natural", "JPEG", "data/06-sxz5-data/raw/banana.jpg", "dev", False),
        ("gull", "natural", "JPEG", "data/06-sxz5-data/raw/gull.jpg", "val", False),
        ("python-logo", "graphics", "PNG", "phases/07-next/python-logo.png", "dev", True),
        ("transparency", "graphics", "BMP", "data/06-sxz5-data/corpus/transparency.bmp", "val", False),
        ("exif", "screenshot/document", "PNG", "phases/07-next/exif.png", "dev", False),
        ("fig1_class_hits", "screenshot/document", "PNG", "phases/11-cgmc/figures/fig1_class_hits.png", "val", False),
    ]
    payload = {"phase": 15, "episode": 2, "max_nodes": MAX_NODES, "min_size": MIN_SIZE, "files": []}
    for key, category, fmt, relative, split, complete in files:
        path = ROOT / relative
        im, pixels, mode, orig_size, cropped, box = image_pixels(path, crop=256 if key != "python-logo" else None)
        pixels = pixels.copy()
        full = None
        if complete:
            _, full_pixels, _, _, _, _ = image_pixels(path, crop=None)
            full = full_pixels.copy()
        C = math_adaptive(pixels, True)
        D = math_adaptive(pixels, False)
        # Episode 1 fixed-tile B for the crop.
        from run_phase15 import math_image, spatial_prediction
        B = math_image(pixels, 64)
        A = len(Z9.compress(pixels.tobytes()))
        Dsp, pred = spatial_prediction(pixels)
        buf = io.BytesIO()
        Image.fromarray(pixels[:, :, 0] if pixels.shape[2] == 1 else pixels).save(buf, format="PNG", optimize=True, compress_level=9)
        E = len(buf.getvalue())
        entry = {
            "key": key,
            "category": category,
            "format": fmt,
            "split": split,
            "tested_size": [int(pixels.shape[1]), int(pixels.shape[0])],
            "complete": not cropped,
            "crop_box": list(box),
            "A_zstd9": A,
            "B_fixed": B["C_math_zstd9"],
            "C_adaptive": C,
            "D_control": D,
            "E_spatial": Dsp,
            "F_png": E,
            "complete_image": None,
        }
        if full is not None:
            Cfull = math_adaptive(full, True)
            Dfull = math_adaptive(full, False)
            Bfull = math_image(full, 64)
            Afull = len(Z9.compress(full.tobytes()))
            Dspfull, _ = spatial_prediction(full)
            buf = io.BytesIO()
            Image.fromarray(full[:, :, 0] if full.shape[2] == 1 else full).save(buf, format="PNG", optimize=True, compress_level=9)
            Efull = len(buf.getvalue())
            entry["complete_image"] = {
                "size": [int(full.shape[1]), int(full.shape[0])],
                "A": Afull,
                "B": Bfull["C_math_zstd9"],
                "C": Cfull,
                "D": Dfull,
                "E_spatial": Dspfull,
                "F_png": Efull,
            }
        payload["files"].append(entry)
        print(f"{key}: crop C={C['cost']} B={B['C_math_zstd9']} D={D['cost']} A={A} E={E}", flush=True)
    payload["elapsed_s"] = time.perf_counter() - START
    target = ROOT / "lab/sxz-image-math/results/phase15_ep2.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({"elapsed_s": payload["elapsed_s"], "files": [{k: e[k] for k in ("key", "A_zstd9", "B_fixed", "E_spatial", "F_png")} for e in payload["files"]]}, indent=1))


if __name__ == "__main__":
    main()
