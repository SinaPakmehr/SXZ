"""Phase 14 Episode 3: nonlinear GF(2) equation discovery (bounded)."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "lab" / "sxz-amrd"))

from amrd.inference import bm_fit

START = time.perf_counter()
BUDGET = 180.0
REGION = 4096
WINDOW = 1024
WINDOW_STARTS = (0, 8192, 16384, 24576)
CONTEXTS = (8, 16)


def features(bits, n, L, quadratic=True):
    value = 1
    index = 1
    for i in range(1, L + 1):
        if bits[n - i]:
            value |= 1 << index
        index += 1
    if quadratic:
        for i in range(1, L + 1):
            for j in range(i + 1, L + 1):
                if bits[n - i] and bits[n - j]:
                    value |= 1 << index
                index += 1
    return value


def feature_count(L, quadratic=True):
    return 1 + L + (L * (L - 1) // 2 if quadratic else 0)


def gauss(rows, F):
    pivots = {}
    inconsistent = False
    mask = (1 << F) - 1
    for row in rows:
        while row & mask:
            feature_part = row & mask
            column = feature_part.bit_length() - 1
            if column in pivots:
                row ^= pivots[column]
            else:
                pivots[column] = row
                break
        if not (row & mask) and ((row >> F) & 1):
            inconsistent = True
    rank = len(pivots)
    # Particular solution with free variables zero.
    solution = 0
    for column in sorted(pivots):
        row = pivots[column]
        rhs = (row >> F) & 1
        parity = ((row & ((1 << column) - 1)) & solution).bit_count() & 1
        if rhs ^ parity:
            solution |= 1 << column
    return solution, rank, F - rank, inconsistent, pivots


def predict(feature_value, solution):
    return (feature_value & solution).bit_count() & 1


def simple(bits):
    if len(bits) == 0:
        return True
    if np.all(bits == bits[0]):
        return True
    for period in range(1, min(64, len(bits) // 2) + 1):
        if np.array_equal(bits[period:], bits[:-period]):
            return True
    return False


def evaluate_sequence(bits, L, quadratic, window_starts=WINDOW_STARTS):
    F = feature_count(L, quadratic)
    stats = Counter()
    records = []
    for start in window_starts:
        window = bits[start : start + WINDOW]
        if len(window) < WINDOW:
            continue
        if simple(window):
            stats["simple_windows"] += 1
            continue
        rows = []
        half = WINDOW // 2
        for n in range(L, half):
            f = features(window, n, L, quadratic)
            rows.append(f | (int(window[n]) << F))
        solution, rank, nullity, inconsistent, _ = gauss(rows, F)
        stats["windows"] += 1
        stats["rank_sum"] += rank
        stats["nullity_sum"] += nullity
        stats["inconsistent"] += int(inconsistent)
        if inconsistent:
            stats["inconsistent_windows"] += 1
            continue
        train_ok = all(predict(features(window, n, L, quadratic), solution) == int(window[n]) for n in range(L, half))
        valid_correct = sum(
            int(predict(features(window, n, L, quadratic), solution) == int(window[n]))
            for n in range(half, WINDOW)
        )
        valid_ok = valid_correct == WINDOW - half
        stats["train_exact"] += int(train_ok)
        stats["valid_exact"] += int(valid_ok)
        stats["valid_correct"] += valid_correct
        stats["valid_total"] += WINDOW - half
        if valid_ok:
            stats["underdetermined"] += int(nullity > 0)
            records.append({
                "start": start,
                "context": L,
                "degree": 2 if quadratic else 1,
                "rank": rank,
                "nullity": nullity,
                "underdetermined": nullity > 0,
                "solution_terms": int(solution),
                "F": F,
            })
    return stats, records


def relation_features(window, n, L, y):
    # [1, x_i, x_i x_j, y, y*x_i]
    value = 1
    index = 1
    xs = [int(window[n - i]) for i in range(1, L + 1)]
    for x in xs:
        if x:
            value |= 1 << index
        index += 1
    for i in range(L):
        for j in range(i + 1, L):
            if xs[i] and xs[j]:
                value |= 1 << index
            index += 1
    y_index = index
    if y:
        value |= 1 << y_index
    index += 1
    for x in xs:
        if y and x:
            value |= 1 << index
        index += 1
    return value, y_index, index


def nullspace_basis(pivots, F, limit=8):
    pivots = dict(pivots)
    free = [column for column in range(F) if column not in pivots]
    basis = []
    for column in free[:limit]:
        vector = 1 << column
        for pivot in sorted(pivots):
            row = pivots[pivot]
            if ((row & vector).bit_count() & 1):
                vector |= 1 << pivot
        basis.append(vector)
    return basis, len(free)


def evaluate_implicit(bits, L, window_starts=(0, 8192)):
    F = 1 + L + L * (L - 1) // 2 + 1 + L
    stats = Counter()
    found = []
    for start in window_starts:
        window = bits[start : start + WINDOW]
        if len(window) < WINDOW or simple(window):
            continue
        rows = []
        half = WINDOW // 2
        for n in range(L, half):
            f, _, _ = relation_features(window, n, L, int(window[n]))
            rows.append(f)  # homogeneous = 0
        _, rank, nullity, inconsistent, pivots = gauss(rows, F)
        stats["windows"] += 1
        stats["rank_sum"] += rank
        stats["nullity_sum"] += nullity
        if inconsistent:
            stats["inconsistent"] += 1
            continue
        basis, free = nullspace_basis(pivots, F, limit=8)
        candidates = list(basis)
        for i in range(min(8, len(basis))):
            for j in range(i + 1, min(8, len(basis))):
                candidates.append(basis[i] ^ basis[j])
        for vector in candidates:
            if vector == 0:
                continue
            # Require a y-dependent term.
            y_start = 1 + L + L * (L - 1) // 2
            if not any((vector >> (y_start + k)) & 1 for k in range(L + 1)):
                stats["input_only"] += 1
                continue
            good = True
            correct = 0
            total = 0
            for n in range(half, WINDOW):
                f0, _, _ = relation_features(window, n, L, 0)
                f1, _, _ = relation_features(window, n, L, 1)
                v0 = (vector & f0).bit_count() & 1
                v1 = (vector & f1).bit_count() & 1
                y = int(window[n])
                if v0 == v1:
                    good = False
                    break
                predicted = 1 if v1 else 0
                correct += int(predicted == y)
                total += 1
            if good and correct == total:
                stats["predictive"] += 1
                found.append({"start": start, "context": L, "F": F, "nullity": nullity, "vector_bits": vector.bit_length()})
    return stats, found


def file_bits(data: bytes):
    raw = np.frombuffer(data, dtype=np.uint8)
    sequences = [("packed", np.unpackbits(raw, bitorder="little"))]
    for bit in range(8):
        sequences.append((f"bit{bit}", ((raw >> bit) & 1).astype(np.uint8)))
    return sequences


def main():
    files = [
        ("book1", "TXT", ROOT / "datasets/06-sxz5-data/book1"),
        ("7zr.exe", "EXE", ROOT / "datasets/03-audit-assets/7zr.exe"),
        ("irs1040.pdf", "PDF", ROOT / "datasets/06-sxz5-data/raw/irs1040.pdf"),
        ("hopper.bmp", "BMP", ROOT / "phases/09-msmc/hopper.bmp"),
        ("ecg-holdout.bin", "ECG", ROOT / "datasets/05-sxz4-corpus/ecg-holdout.bin"),
        ("model-weights.bin", "weights", ROOT / "datasets/06-compare-corpus/model-weights.bin"),
    ]
    payload = {"phase": 14, "episode": 3, "contexts": CONTEXTS, "window_bits": WINDOW, "files": []}
    total_dev = Counter()
    total_val = Counter()
    for key, category, path in files:
        if time.perf_counter() - START > BUDGET - 5:
            payload["partial"] = True
            break
        raw = path.read_bytes()
        dev_off = 0
        val_off = max(REGION, (len(raw) - REGION) // 2)
        if val_off + REGION > len(raw):
            val_off = len(raw) - REGION
        dev = raw[dev_off : dev_off + REGION]
        val = raw[val_off : val_off + REGION]
        dev_configs = {}
        for L in CONTEXTS:
            for quadratic in (True, False):
                agg = Counter()
                recs = []
                for rep_name, sequence in file_bits(dev):
                    stats, records = evaluate_sequence(sequence, L, quadratic)
                    agg.update(stats)
                    recs.extend(records)
                dev_configs[(L, quadratic)] = (agg, recs)
        # Freeze the configuration with the best dev validation count/accuracy.
        best_key = max(
            dev_configs,
            key=lambda key: (
                dev_configs[key][0].get("valid_exact", 0),
                -dev_configs[key][0].get("inconsistent_windows", 0),
                key[0],
                key[1],
            ),
        )
        L, quadratic = best_key
        val_stats = Counter()
        val_recs = []
        for rep_name, sequence in file_bits(val):
            stats, records = evaluate_sequence(sequence, L, quadratic)
            val_stats.update(stats)
            val_recs.extend(records)
        # Implicit relations on a small fixed subset, both contexts.
        implicit = {}
        for Lrel in CONTEXTS:
            agg = Counter()
            found = []
            for rep_name, sequence in file_bits(dev):
                stats, recs = evaluate_implicit(sequence, Lrel)
                agg.update(stats)
                found.extend(recs)
            implicit[str(Lrel)] = {"stats": dict(agg), "found": found[:5]}
        implicit_val = {}
        for Lrel in CONTEXTS:
            agg = Counter()
            found = []
            for rep_name, sequence in file_bits(val):
                stats, recs = evaluate_implicit(sequence, Lrel)
                agg.update(stats)
                found.extend(recs)
            implicit_val[str(Lrel)] = {"stats": dict(agg), "found": found[:5]}
        entry = {
            "key": key,
            "category": category,
            "file_bytes": len(raw),
            "dev_offset": dev_off,
            "val_offset": val_off,
            "dev_configs": {
                f"L{L}_{'quad' if quadratic else 'lin'}": dict(stats)
                for (L, quadratic), (stats, recs) in dev_configs.items()
            },
            "frozen": {"L": L, "degree": 2 if quadratic else 1},
            "val": dict(val_stats),
            "val_models": val_recs[:5],
            "implicit": implicit,
            "implicit_val": implicit_val,
        }
        payload["files"].append(entry)
        total_dev.update(dev_configs[best_key][0])
        total_val.update(val_stats)
        print(f"{key}: freeze L{L} degree{2 if quadratic else 1} dev_valid={dev_configs[best_key][0].get('valid_exact',0)} val_valid={val_stats.get('valid_exact',0)}", flush=True)
    payload["total_dev"] = dict(total_dev)
    payload["total_val"] = dict(total_val)
    payload["elapsed_s"] = time.perf_counter() - START
    target = Path(__file__).resolve().parents[1] / "results" / "episode3.json"
    target.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf8")
    print(json.dumps({"elapsed_s": payload["elapsed_s"], "total_dev": payload["total_dev"], "total_val": payload["total_val"]}, indent=1))


if __name__ == "__main__":
    main()
