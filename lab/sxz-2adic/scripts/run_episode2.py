"""Phase 14 Episode 2: coordinate-based function discovery (bounded)."""

from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter
from itertools import product
from pathlib import Path

import numpy as np
import zstandard as zstd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "lab" / "sxz-amrd"))

from amrd.inference import detect_affine1, detect_affine2

START = time.perf_counter()
BUDGET = 180.0
REGION = 4096
WIDTHS = (16, 64, 256)
Z9 = zstd.ZstdCompressor(level=9)
Z19 = zstd.ZstdCompressor(level=19)
FAMILIES = ("poly", "add", "xor")


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


def width_bytes(symbol: int) -> int:
    return 1 if symbol == 8 else 2


def matrix(data: bytes, symbol: int, W: int):
    if symbol == 8:
        arr = np.frombuffer(data, dtype=np.uint8).astype(np.uint64)
    else:
        arr = np.frombuffer(data, dtype="<u2").astype(np.uint64)
    H = len(arr) // W
    return arr[: H * W].reshape(H, W), H


def mod_mask(bits: int) -> int:
    return (1 << bits) - 1


def binom_table(n: int, bits: int):
    table = np.zeros((4, n), dtype=np.uint64)
    mod = 1 << bits
    for k in range(4):
        for x in range(n):
            table[k, x] = math.comb(x, k) % mod
    return table


def poly_coeffs(X, H, W, bits):
    mod = 1 << bits
    a = {}
    for i in range(4):
        for j in range(4 - i):
            if i >= H or j >= W:
                a[(i, j)] = 0
                continue
            total = 0
            for u in range(i + 1):
                for v in range(j + 1):
                    sign = -1 if ((i - u + j - v) & 1) else 1
                    total += sign * math.comb(i, u) * math.comb(j, v) * int(X[u, v])
            a[(i, j)] = total % mod
    return a


def poly_eval(a, H, W, bits):
    mod = 1 << bits
    br = binom_table(H, bits)
    bc = binom_table(W, bits)
    F = np.zeros((H, W), dtype=np.uint64)
    for (i, j), coef in a.items():
        if not coef:
            continue
        F = (F + coef * br[i][:, None] * bc[j][None, :]) % mod
    return F


def seq_describe(seq, bits):
    mod = 1 << bits
    wb = width_bytes(bits)
    n = len(seq)
    if n and np.all(seq == seq[0]):
        return "const", 1 + wb + len(uvarint(n)), seq, None
    if n >= 2:
        d1 = (seq[1:] - seq[:-1]) % mod
        if np.all(d1 == d1[0]):
            return "poly1", 1 + 2 * wb + len(uvarint(n)), seq, None
        if len(d1) >= 2:
            d2 = (d1[1:] - d1[:-1]) % mod
            if np.all(d2 == d2[0]):
                return "poly2", 1 + 3 * wb + len(uvarint(n)), seq, None
            if len(d2) >= 2:
                d3 = (d2[1:] - d2[:-1]) % mod
                if np.all(d3 == d3[0]):
                    return "poly3", 1 + 4 * wb + len(uvarint(n)), seq, None
    if n >= 6:
        half = n // 2
        stats = {}
        shape = detect_affine1(seq[:half], seq[half:], bits, stats)
        if shape is not None:
            return "affine1", 1 + 3 * wb + len(uvarint(n)), seq, None
        shape = detect_affine2(seq[:half], seq[half:], bits, stats)
        if shape is not None:
            return "affine2", 1 + 5 * wb + len(uvarint(n)), seq, None
    return "raw", 1 + n * wb + len(uvarint(n)), seq, None


def component_cost(seq, bits):
    kind, cost, _, _ = seq_describe(seq, bits)
    return kind, cost


def residual_bytes(res, symbol):
    if symbol == 8:
        return res.astype(np.uint8).tobytes()
    return res.astype("<u2").tobytes()


def best_transform(data: bytes):
    def delta(x):
        arr = np.frombuffer(x, dtype=np.uint8)
        out = np.empty_like(arr)
        out[0] = arr[0]
        out[1:] = (arr[1:] - arr[:-1]) & 255
        return out.tobytes()

    def shuffle(x, w):
        body = len(x) - len(x) % w
        return b"".join(x[lane:body:w] for lane in range(w)) + x[body:]

    def bitplanes(x):
        arr = np.frombuffer(x, dtype=np.uint8)
        return b"".join(np.packbits((arr >> bit) & 1, bitorder="big").tobytes() for bit in range(8))

    cands = [("identity", data, 6), ("delta", delta(data), 7)]
    for w in (2, 3, 4):
        cands.append((f"shuffle{w}", shuffle(data, w), 7))
    s3 = shuffle(data, 3)
    cands.append(("shuffle3_delta", delta(s3), 9))
    cands.append(("bitplanes", bitplanes(data), 7))
    return min((zlen + meta, name) for name, body, meta in cands for zlen in [len(Z9.compress(body))])


def evaluate(data: bytes, symbol: int, W: int):
    X, H = matrix(data, symbol, W)
    bits = 8 if symbol == 8 else 16
    mod = 1 << bits
    wb = width_bytes(symbol)
    candidates = {}
    # A: polynomial
    a = poly_coeffs(X, H, W, bits)
    F = poly_eval(a, H, W, bits)
    res = (X - F) % mod
    coeff_bytes = 2 * 4 * wb + 8
    candidates["poly"] = {
        "F": F, "res": res, "record": coeff_bytes + 8,
        "coeffs": {f"{i},{j}": int(v) for (i, j), v in a.items()},
    }
    # B: additive
    U = X[:, 0].copy()
    V = (X[0, :] - X[0, 0]) % mod
    Fadd = (U[:, None] + V[None, :]) % mod
    kU, cU = component_cost(U, bits)
    kV, cV = component_cost(V, bits)
    candidates["add"] = {
        "F": Fadd, "res": (X - Fadd) % mod,
        "record": 8 + cU + cV + 2,
        "components": (kU, kV),
    }
    # C: XOR
    Ux = X[:, 0].copy()
    Vx = X[0, :] ^ X[0, 0]
    Fxor = Ux[:, None] ^ Vx[None, :]
    kUx, cUx = component_cost(Ux, bits)
    kVx, cVx = component_cost(Vx, bits)
    candidates["xor"] = {
        "F": Fxor, "res": X ^ Fxor,
        "record": 8 + cUx + cVx + 2,
        "components": (kUx, kVx),
    }
    out = {}
    for family, item in candidates.items():
        res = item["res"]
        exact = bool(np.all(res == 0))
        rb = residual_bytes(res.astype(np.uint64), symbol)
        out[family] = {
            "symbol": symbol,
            "W": W,
            "H": H,
            "bits": bits,
            "record": int(item["record"]),
            "exact": exact,
            "B_math_raw": int(item["record"] + len(rb) + 16),
            "C_math_zstd9": int(item["record"] + len(Z9.compress(rb)) + 16),
            "residual_entropy": entropy(rb) if rb else 0.0,
            "coeffs": item.get("coeffs"),
            "components": item.get("components"),
            "verified": bool(np.array_equal(
                (item["F"] + res) % mod, X
            )) if family != "xor" else bool(np.array_equal(item["F"] ^ res, X)),
        }
    return out, len(data)


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = np.bincount(np.frombuffer(data, dtype=np.uint8), minlength=256)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts if c)


def correction():
    path = Path(__file__).resolve().parents[1] / "results" / "phase14.json"
    old = json.loads(path.read_text(encoding="utf8"))
    f = next(item for item in old["files"] if item["key"] == "7zr.exe")
    raw = (ROOT / f["path"]).read_bytes()
    chunk = raw[597163 : 597163 + 5461]
    bits = np.unpackbits(np.frombuffer(chunk, dtype=np.uint8), bitorder="little")
    rows = []
    for m in [item for item in f["models"] if item["nontrivial"]]:
        span = bits[m["start"] : m["start"] + m["span"]]
        nw = len(span) // 16
        tail = len(span) % 16
        words = [sum(int(span[k * 16 + b]) << b for b in range(16)) for k in range(nw)]
        ds = [(words[k + 1] - words[k]) & 65535 for k in range(nw - 1)]
        d0 = Counter(ds).most_common(1)[0][0]
        pos = next((k for k in range(nw) if words[k] != (words[0] + k * d0) & 65535), None)
        carry = 0
        ok = pos is None
        if pos is not None:
            for c in (1, 65535):
                if all(((words[0] + k * d0 + (c if k >= pos else 0)) & 65535) == words[k] for k in range(nw)):
                    ok = True
                    carry = c
                    break
        ap_record = 2 + 2 + 1 + 1 + 1 + (tail + 7) // 8 + len(uvarint(len(span))) + len(uvarint(m["start"])) + 2
        rows.append({
            "span": len(span),
            "nw": nw,
            "tail": tail,
            "d": d0,
            "carry_pos": pos,
            "carry": carry,
            "ap_exact": ok,
            "ap_record": ap_record,
            "rational_record": m["record_bytes"],
        })
    return rows


def main():
    files = [
        ("book1", "TXT", ROOT / "datasets/06-sxz5-data/book1"),
        ("7zr.exe", "EXE", ROOT / "datasets/03-audit-assets/7zr.exe"),
        ("irs1040.pdf", "PDF", ROOT / "datasets/06-sxz5-data/raw/irs1040.pdf"),
        ("hopper.bmp", "BMP", ROOT / "phases/09-msmc/hopper.bmp"),
        ("ecg-holdout.bin", "ECG", ROOT / "datasets/05-sxz4-corpus/ecg-holdout.bin"),
        ("model-weights.bin", "weights", ROOT / "datasets/06-compare-corpus/model-weights.bin"),
    ]
    correction_rows = correction()
    payload = {"phase": 14, "episode": 2, "files": [], "correction": correction_rows}
    for key, category, path in files:
        raw = path.read_bytes()
        dev_off = 0
        val_off = max(REGION, (len(raw) - REGION) // 2)
        if val_off + REGION > len(raw):
            val_off = len(raw) - REGION
        if val_off < REGION:
            val_off = REGION
        dev = raw[dev_off : dev_off + REGION]
        val = raw[val_off : val_off + REGION]
        dev_candidates = []
        for symbol in (8, 16):
            for W in WIDTHS:
                if symbol == 16 and (REGION // 2) % W:
                    continue
                cand, _ = evaluate(dev, symbol, W)
                for family, item in cand.items():
                    dev_candidates.append((item["C_math_zstd9"], symbol, W, family, item))
        dev_candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        best = dev_candidates[0]
        # Freeze the best requested layout/family and refit on validation.
        val_candidates = []
        for symbol in (8, 16):
            for W in WIDTHS:
                if symbol == 16 and (REGION // 2) % W:
                    continue
                cand, _ = evaluate(val, symbol, W)
                for family, item in cand.items():
                    val_candidates.append((item["C_math_zstd9"], symbol, W, family, item))
        val_best = next(item for item in val_candidates if item[1:4] == best[1:4])
        A = len(Z9.compress(val))
        D_total, D_name = best_transform(val)
        entry = {
            "key": key,
            "category": category,
            "file_bytes": len(raw),
            "dev_offset": dev_off,
            "val_offset": val_off,
            "dev_bytes": len(dev),
            "val_bytes": len(val),
            "dev_best": {"saving_vs_zstd9": best[0], "symbol": best[1], "W": best[2], "family": best[3], "record": best[4]["record"], "exact": best[4]["exact"], "verified": best[4]["verified"]},
            "val_best": {"saving_vs_zstd9": val_best[0], "symbol": val_best[1], "W": val_best[2], "family": val_best[3], "record": val_best[4]["record"], "exact": val_best[4]["exact"], "verified": val_best[4]["verified"], "B": val_best[4]["B_math_raw"], "C": val_best[4]["C_math_zstd9"], "entropy": val_best[4]["residual_entropy"], "coeffs": val_best[4]["coeffs"], "components": val_best[4]["components"]},
            "A_zstd9": A,
            "D_transform": D_name,
            "D_total": D_total,
        }
        entry["promising"] = val_best[0] < min(A, D_total)
        payload["files"].append(entry)
        print(f"{key}: dev {best[3]} W{best[2]} s{best[1]} C={best[0]} | val C={val_best[0]} A={A} D={D_total} promising={entry['promising']}", flush=True)
    payload["elapsed_s"] = time.perf_counter() - START
    target = Path(__file__).resolve().parents[1] / "results" / "episode2.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({"elapsed_s": payload["elapsed_s"], "correction": correction_rows, "files": payload["files"]}, indent=1))


if __name__ == "__main__":
    main()
