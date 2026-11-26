"""Phase 15 Episode 1: mathematical image representation (bounded)."""

from __future__ import annotations

import hashlib
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
START = time.perf_counter()
BUDGET = 180.0
Z9 = zstd.ZstdCompressor(level=9)
TILE = 64
SIZES = (8, 16, 32, 64)
SCALE = 256


def uvarint(value: int) -> bytes:
    value = int(value)
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts if c)


def basis(kind, h, w, freqs=None):
    y, x = np.mgrid[0:h, 0:w]
    xf = x.astype(np.float64)
    yf = y.astype(np.float64)
    cols = [np.ones(h * w)]
    if kind == "linear":
        cols += [xf.ravel(), yf.ravel()]
    elif kind == "quad":
        cols += [xf.ravel(), yf.ravel(), (xf * xf).ravel(), (xf * yf).ravel(), (yf * yf).ravel()]
    elif kind == "radial":
        dx = xf - (w - 1) / 2
        dy = yf - (h - 1) / 2
        cols += [dx.ravel(), dy.ravel(), (dx * dx).ravel(), (dy * dy).ravel()]
    elif kind == "sine":
        fx, fy = freqs
        cols += [
            np.sin(2 * math.pi * fx * xf / w).ravel(),
            np.cos(2 * math.pi * fx * xf / w).ravel(),
            np.sin(2 * math.pi * fy * yf / h).ravel(),
            np.cos(2 * math.pi * fy * yf / h).ravel(),
        ]
    elif kind == "sinlin":
        fx, fy = freqs
        cols += [
            xf.ravel(), yf.ravel(),
            np.sin(2 * math.pi * fx * xf / w).ravel(),
            np.cos(2 * math.pi * fx * xf / w).ravel(),
            np.sin(2 * math.pi * fy * yf / h).ravel(),
            np.cos(2 * math.pi * fy * yf / h).ravel(),
        ]
    return np.stack(cols, axis=1)


def fit_plane(Y):
    h, w = Y.shape
    A = basis("linear", h, w)
    coef, *_ = np.linalg.lstsq(A, Y.astype(np.float64).ravel(), rcond=None)
    q = np.rint(coef * SCALE).astype(np.int64)
    pred = np.rint((A @ q) / SCALE).astype(np.int64)
    return q, np.clip(pred, 0, 255).reshape(h, w), A


def fit_basis(Y, kind, freqs=None):
    h, w = Y.shape
    A = basis(kind, h, w, freqs)
    coef, *_ = np.linalg.lstsq(A, Y.astype(np.float64).ravel(), rcond=None)
    q = np.rint(coef * SCALE).astype(np.int64)
    pred = np.rint((A @ q) / SCALE).astype(np.int64)
    return q, np.clip(pred, 0, 255).reshape(h, w)


def piecewise(Y):
    h, w = Y.shape
    pred = np.zeros((h, w), dtype=np.int64)
    qs = []
    for top in (0, h // 2):
        for left in (0, w // 2):
            sub = Y[top:, left:]
            if sub.size == 0:
                continue
            q, p, _ = fit_plane(sub)
            pred[top:, left:] = p
            qs.extend(q.tolist())
    return qs, pred


def candidates(Y):
    h, w = Y.shape
    out = []
    for kind in ("const", "linear", "quad", "radial"):
        if kind == "const":
            q = np.array([np.rint(np.mean(Y) * SCALE)], dtype=np.int64)
            pred = np.clip(np.rint(q[0] / SCALE) * np.ones((h, w)), 0, 255).astype(np.int64)
        else:
            q, pred = fit_basis(Y, kind)
        out.append((kind, q.tolist(), pred, None, len(q) * 2 + 10, kind in {"const", "linear", "quad"}))
    for freqs in ((1, 1), (1, 2), (2, 1), (2, 2)):
        q, pred = fit_basis(Y, "sine", freqs)
        out.append(("sine", q.tolist(), pred, freqs, len(q) * 2 + 12, False))
    for freqs in ((1, 1), (2, 2)):
        q, pred = fit_basis(Y, "sinlin", freqs)
        out.append(("sinlin", q.tolist(), pred, freqs, len(q) * 2 + 12, False))
    qs, pred = piecewise(Y)
    out.append(("piece", qs, pred, None, len(qs) * 2 + 12, True))
    return out


def choose_tile(Y):
    best = None
    control = None
    all_c = []
    for kind, q, pred, freqs, record, is_control in candidates(Y):
        residual = ((Y.astype(np.int64) - pred) % 256).astype(np.uint8)
        rb = residual.tobytes()
        z = len(Z9.compress(rb)) if np.any(residual) else 0
        c = record + z
        all_c.append((kind, q, pred, freqs, record, is_control, rb, z, c))
        if best is None or c < best[8]:
            best = all_c[-1]
        if is_control and (control is None or c < control[8]):
            control = all_c[-1]
    return best, control


def image_pixels(path: Path, crop=256):
    im = Image.open(path)
    original_mode = im.mode
    original_size = im.size
    if crop and (im.width > crop or im.height > crop):
        full = np.asarray(im)
        if full.ndim == 2:
            full = full[:, :, None]
        best = None
        for top in range(0, max(1, full.shape[0] - crop + 1), 128):
            for left in range(0, max(1, full.shape[1] - crop + 1), 128):
                patch = full[top : top + crop, left : left + crop]
                score = float(np.var(patch.astype(np.float64)))
                if best is None or score > best[0]:
                    best = (score, left, top)
        _, left, top = best
        im = im.crop((left, top, left + crop, top + crop))
        cropped = True
        box = (left, top, left + crop, top + crop)
    else:
        cropped = False
        box = (0, 0, im.width, im.height)
    pixels = np.asarray(im)
    if pixels.ndim == 2:
        pixels = pixels[:, :, None]
    return im, pixels, original_mode, original_size, cropped, box


def tile_positions(h, w, size, limit=None):
    positions = [(y, x) for y in range(0, h, size) for x in range(0, w, size)]
    if limit is not None:
        positions = positions[:limit]
    return positions


def math_image(pixels, size=TILE):
    h, w, channels = pixels.shape
    records = 0
    residuals = []
    control_records = 0
    control_residuals = []
    exact_pixels = 0
    total_pixels = 0
    counts = Counter()
    examples = []
    verified = True
    for y0, x0 in tile_positions(h, w, size):
        y1, x1 = min(h, y0 + size), min(w, x0 + size)
        for channel in range(channels):
            Y = pixels[y0:y1, x0:x1, channel]
            best, control = choose_tile(Y)
            records += best[4]
            residuals.append(best[6])
            reconstructed = (
                best[2] + np.frombuffer(best[6], dtype=np.uint8).reshape(Y.shape)
            ) & 255
            if not np.array_equal(reconstructed, Y):
                verified = False
            if not best[6] or not any(best[6]):
                exact_pixels += Y.size
            total_pixels += Y.size
            counts[best[0]] += 1
            if not examples or best[0] not in {e[0] for e in examples}:
                examples.append((best[0], best[1], best[3], y0, x0, channel, y1 - y0, x1 - x0))
            if control is not None:
                control_records += control[4]
                control_residuals.append(control[6])
    residual = b"".join(residuals)
    control_residual = b"".join(control_residuals)
    return {
        "records": records,
        "residual_bytes": len(residual),
        "residual_zstd9": len(Z9.compress(residual)) if residual else 0,
        "B_math_raw": records + len(residual) + 16,
        "C_math_zstd9": records + (len(Z9.compress(residual)) if residual else 0) + 16,
        "control_records": control_records,
        "control_residual_bytes": len(control_residual),
        "control_C": control_records + (len(Z9.compress(control_residual)) if control_residual else 0) + 16,
        "exact_pixels": exact_pixels,
        "total_channel_pixels": total_pixels,
        "exact_fraction": exact_pixels / total_pixels if total_pixels else 0.0,
        "families": dict(counts),
        "examples": examples[:6],
        "residual_entropy": entropy(residual),
        "verified": verified,
    }


def spatial_prediction(pixels):
    h, w, c = pixels.shape
    left = np.empty_like(pixels)
    up = np.empty_like(pixels)
    for ch in range(c):
        Y = pixels[:, :, ch]
        left[:, 0, ch] = Y[:, 0]
        left[:, 1:, ch] = (Y[:, 1:].astype(np.int16) - Y[:, :-1]) & 255
        up[0, :, ch] = Y[0, :]
        up[1:, :, ch] = (Y[1:, :].astype(np.int16) - Y[:-1, :]) & 255
    a = len(Z9.compress(left.tobytes())) + 1
    b = len(Z9.compress(up.tobytes())) + 1
    return min(a, b), ("left" if a <= b else "up")


def region_study(images):
    rows = []
    for entry in images:
        if entry["split"] != "dev":
            continue
        pixels = entry["_pixels"]
        for size in SIZES:
            exact = total = 0
            records = 0
            residual = b""
            ys = np.unique(np.linspace(0, max(0, pixels.shape[0] - size), 4).astype(int))
            xs = np.unique(np.linspace(0, max(0, pixels.shape[1] - size), 2).astype(int))
            positions = [(int(y), int(x)) for y in ys for x in xs][:8]
            for y0, x0 in positions:
                y1, x1 = min(pixels.shape[0], y0 + size), min(pixels.shape[1], x0 + size)
                for channel in range(pixels.shape[2]):
                    Y = pixels[y0:y1, x0:x1, channel]
                    best, _ = choose_tile(Y)
                    records += best[4]
                    residual += best[6]
                    exact += int(not best[6] or not any(best[6]))
                    total += 1
            rows.append({
                "image": entry["key"],
                "size": size,
                "tiles": total,
                "exact": exact,
                "records": records,
                "residual_zstd9": len(Z9.compress(residual)) if residual else 0,
            })
    return rows


def main():
    files = [
        ("banana", "natural", "JPEG", "data/06-sxz5-data/raw/banana.jpg", "dev"),
        ("gull", "natural", "JPEG", "data/06-sxz5-data/raw/gull.jpg", "val"),
        ("python-logo", "graphics", "PNG", "phases/07-next/python-logo.png", "dev"),
        ("transparency", "graphics", "BMP", "data/06-sxz5-data/corpus/transparency.bmp", "val"),
        ("exif", "screenshot/document", "PNG", "phases/07-next/exif.png", "dev"),
        ("fig1_class_hits", "screenshot/document", "PNG", "phases/11-cgmc/figures/fig1_class_hits.png", "val"),
    ]
    payload = {"phase": 15, "episode": 1, "tile": TILE, "files": []}
    image_entries = []
    for key, category, fmt, relative, split in files:
        path = ROOT / relative
        im, pixels, mode, size, cropped, box = image_pixels(path, crop=256 if key != "python-logo" else None)
        pixels = pixels.copy()
        math = math_image(pixels, TILE)
        A = len(Z9.compress(pixels.tobytes()))
        D, predictor = spatial_prediction(pixels)
        buf = io.BytesIO()
        Image.fromarray(pixels[:, :, 0] if pixels.shape[2] == 1 else pixels).save(buf, format="PNG", optimize=True, compress_level=9)
        E = len(buf.getvalue())
        entry = {
            "key": key,
            "category": category,
            "format": fmt,
            "split": split,
            "original_file": relative,
            "original_bytes": path.stat().st_size,
            "original_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "original_mode": mode,
            "original_size": list(size),
            "tested_size": [int(pixels.shape[1]), int(pixels.shape[0])],
            "cropped": cropped,
            "crop_box": list(box),
            "channels": int(pixels.shape[2]),
            "decoded_pixel_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
            "A_zstd9": A,
            "B_math_raw": math["B_math_raw"],
            "C_math_zstd9": math["C_math_zstd9"],
            "D_spatial": D,
            "D_predictor": predictor,
            "E_png": E,
            "F_jxl": None,
            "control_C": math["control_C"],
            "records": math["records"],
            "residual_bytes": math["residual_bytes"],
            "residual_zstd9": math["residual_zstd9"],
            "exact_pixels": math["exact_pixels"],
            "total_channel_pixels": math["total_channel_pixels"],
            "exact_fraction": math["exact_fraction"],
            "verified": math["verified"],
            "families": math["families"],
            "examples": math["examples"],
            "residual_entropy": math["residual_entropy"],
        }
        entry["_pixels"] = pixels
        image_entries.append(entry)
        payload["files"].append({k: v for k, v in entry.items() if not k.startswith("_")})
        print(f"{key}: C={entry['C_math_zstd9']} A={A} D={D} E={E} exact={entry['exact_fraction']:.3f} rec={entry['records']}", flush=True)
    payload["region_study"] = region_study(image_entries)
    payload["elapsed_s"] = time.perf_counter() - START
    target = ROOT / "lab/sxz-image-math/results/phase15.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({"elapsed_s": payload["elapsed_s"], "files": [{k: e[k] for k in ("key", "A_zstd9", "C_math_zstd9", "D_spatial", "E_png", "exact_fraction")} for e in payload["files"]]}, indent=1))


if __name__ == "__main__":
    main()
