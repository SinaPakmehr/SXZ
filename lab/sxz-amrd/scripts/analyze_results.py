"""Build derived Episode 1 tables: costs, BM statistics and top discoveries."""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

import numpy as np

PHASE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_ROOT))

from amrd.economics import evaluate_model, union_bit_coverage
from amrd.panel import PANEL, load_sample
from amrd.representations import REP_BY_NAME, extract_symbols
from amrd.scanner import ScannedModel

ALGEBRAIC = {"poly1", "poly2", "poly3", "affine1", "affine2"}


def as_model(record):
    return ScannedModel(**record)


def bits_of(values):
    return "".join(str(int(value)) for value in values)


def equation(model, bits):
    family = model.family
    params = model.params
    if family == "const":
        return f"X[n] = {int(params[0])} for n = 0..{model.count - 1}"
    if family == "periodic":
        pattern = ", ".join(str(int(value)) for value in params[0])
        return f"X[n] = pattern[n mod {model.order}], pattern = [{pattern}]"
    if family.startswith("poly"):
        initials = [int(value) for value in params]
        terms = [str(initials[0])]
        for index in range(1, len(initials)):
            coefficient = initials[index]
            if index == 1:
                terms.append(f"{coefficient}*n")
            else:
                terms.append(f"{coefficient}*C(n,{index})")
        return "X[n] = " + " + ".join(terms) + f"  (mod 2^{bits})"
    if family == "affine1":
        a, c, x0 = (int(value) for value in params)
        return f"X[n] = {a}*X[n-1] + {c}, X[0] = {x0}  (mod 2^{bits})"
    if family == "affine2":
        a, b, c, x0, x1 = (int(value) for value in params)
        return (
            f"X[n] = {a}*X[n-1] + {b}*X[n-2] + {c}, "
            f"X[0] = {x0}, X[1] = {x1}  (mod 2^{bits})"
        )
    if family == "bm":
        taps, seed = int(params[0]), int(params[1])
        indices = [j for j in range(1, model.order + 1) if (taps >> (j - 1)) & 1]
        seed_bits = [(seed >> index) & 1 for index in range(model.order)]
        terms = " XOR ".join(f"s[n-{j}]" for j in indices) if indices else "0"
        return (
            f"s[n] = {terms}, order {model.order}, "
            f"seed {bits_of(seed_bits)}"
        )
    return family


def values_head(model, data):
    rep = REP_BY_NAME[model.rep]
    symbols = extract_symbols(data, rep, model.align)
    if rep.is_bit:
        values = symbols[model.start : model.start + 16]
        return bits_of(values)
    values = symbols[model.start : model.start + 8]
    return ", ".join(str(int(value)) for value in values)


def main():
    results = Path(__file__).resolve().parents[1] / "results"
    panel = json.loads((results / "panel.json").read_text(encoding="utf8"))
    samples = {item.name: load_sample(item)[0] for item in PANEL}
    family_stats = {}
    bm_orders = []
    bm_lc = []
    evaluated = []
    profitable_bit_models = []
    algebraic_eval = []
    raw_profitable = 0
    backend_profitable = 0
    with4b = 0
    total_models = 0

    for file in panel["files"]:
        data = samples[file["name"]]
        for record in file["models"]:
            model = as_model(record)
            entry = evaluate_model(model, data)
            entry["file"] = file["name"]
            entry["bits"] = REP_BY_NAME[model.rep].sym_bits
            evaluated.append(entry)
            total_models += 1
            stats = family_stats.setdefault(
                model.family,
                {
                    "models": 0,
                    "record_bytes": [],
                    "span_bytes": [],
                    "raw_profitable": 0,
                    "backend_profitable": 0,
                    "with_4b": 0,
                    "savings_backend_min": [],
                },
            )
            stats["models"] += 1
            stats["record_bytes"].append(model.record_bytes)
            stats["span_bytes"].append(model.span_bytes)
            if entry["raw_profitable"]:
                stats["raw_profitable"] += 1
                raw_profitable += 1
            if entry["backend_profitable"]:
                stats["backend_profitable"] += 1
                backend_profitable += 1
                if model.start_bit is not None:
                    profitable_bit_models.append(model)
            if entry["with_4b_overhead"]:
                stats["with_4b"] += 1
                with4b += 1
            stats["savings_backend_min"].append(entry["savings_backend_min"])
            if model.family in ALGEBRAIC:
                algebraic_eval.append(entry)
            if model.family == "bm":
                bm_orders.append(model.order)
                bm_lc.append(model.order / max(1, model.fit_len))

    evaluated_by_key = {
        (item["file"], item["family"], item["rep"], item["start"], item["count"]): item
        for item in evaluated
    }

    cost_table = {}
    for family, stats in sorted(family_stats.items()):
        cost_table[family] = {
            "models": stats["models"],
            "record_bytes_min": min(stats["record_bytes"]),
            "record_bytes_median": statistics.median(stats["record_bytes"]),
            "record_bytes_mean": round(statistics.mean(stats["record_bytes"]), 3),
            "record_bytes_max": max(stats["record_bytes"]),
            "span_bytes_total": sum(stats["span_bytes"]),
            "raw_profitable": stats["raw_profitable"],
            "backend_profitable": stats["backend_profitable"],
            "with_4b": stats["with_4b"],
            "best_backend_saving": max(stats["savings_backend_min"]),
        }

    profitable_word_bytes = 0
    for file in panel["files"]:
        data = samples[file["name"]]
        mask = np.zeros(len(data), dtype=bool)
        for record in file["models"]:
            model = as_model(record)
            if model.start_byte is None:
                continue
            entry = evaluated_by_key[
                (file["name"], model.family, model.rep, model.start, model.count)
            ]
            if entry["backend_profitable"]:
                mask[model.start_byte : model.end_byte] = True
        profitable_word_bytes += int(mask.sum())
    profitable_bit_positions = union_bit_coverage(
        profitable_bit_models, panel["totals"]["scanned_bytes"]
    )

    bm_summary = {
        "models": len(bm_orders),
        "order_min": min(bm_orders) if bm_orders else None,
        "order_median": statistics.median(bm_orders) if bm_orders else None,
        "order_max": max(bm_orders) if bm_orders else None,
        "order_le_8": sum(1 for value in bm_orders if value <= 8),
        "order_9_16": sum(1 for value in bm_orders if 9 <= value <= 16),
        "order_17_32": sum(1 for value in bm_orders if 17 <= value <= 32),
        "order_33_64": sum(1 for value in bm_orders if 33 <= value <= 64),
        "normalized_lc_min": min(bm_lc) if bm_lc else None,
        "normalized_lc_median": statistics.median(bm_lc) if bm_lc else None,
        "normalized_lc_max": max(bm_lc) if bm_lc else None,
    }

    candidates = []
    for file in panel["files"]:
        data = samples[file["name"]]
        for record in file["models"]:
            model = as_model(record)
            entry = evaluated_by_key[
                (file["name"], model.family, model.rep, model.start, model.count)
            ]
            if not model.exact:
                continue
            family_rank = {
                "affine2": 100,
                "poly3": 90,
                "poly2": 80,
                "affine1": 70,
                "bm": 60,
                "poly1": 50,
                "periodic": 40,
                "const": 30,
            }.get(model.family, 0)
            if model.family == "bm":
                family_rank += max(0, 24 - model.order)
            score = family_rank + 10 * math.log10(max(1, model.span_bytes))
            candidates.append((score, file["name"], model, entry))
    candidates.sort(key=lambda item: (-item[0], -item[2].span_bytes, item[1]))
    selected = []
    per_family = Counter()
    per_file = Counter()
    per_file_family = Counter()
    for score, file_name, model, entry in candidates:
        family_key = (file_name, model.family)
        if (
            per_family[model.family] >= 4
            or per_file[file_name] >= 2
            or per_file_family[family_key] >= 1
        ):
            continue
        selected.append((score, file_name, model, entry))
        per_family[model.family] += 1
        per_file[file_name] += 1
        per_file_family[family_key] += 1
        if len(selected) >= 10:
            break

    top = []
    for score, file_name, model, entry in selected:
        bits = REP_BY_NAME[model.rep].sym_bits
        top.append(
            {
                "file": file_name,
                "family": model.family,
                "rep": model.rep,
                "align": model.align,
                "start": model.start,
                "count": model.count,
                "order": model.order,
                "window": model.window,
                "fit_len": model.fit_len,
                "val_len": model.val_len,
                "span_bytes": model.span_bytes,
                "record_bytes": model.record_bytes,
                "equation": equation(model, bits),
                "values_head": values_head(model, samples[file_name]),
                "zstd19": entry["zstd19"],
                "lzma2": entry["lzma2"],
                "savings_backend_min": entry["savings_backend_min"],
                "backend_profitable": entry["backend_profitable"],
                "exact": model.exact,
                "score": round(score, 3),
            }
        )

    aggregate = Counter()
    for file in panel["files"]:
        for key, value in file["scan"]["stats"].items():
            if key.startswith("affine"):
                aggregate[key] += int(value)

    from amrd.inference import detect_affine2

    singular_values = [1, 4, 10, 22, 46, 94, 190, 382, 766, 1534, 3070, 6142]
    singular_array = np.asarray(singular_values, dtype=np.uint16)
    singular_stats = {}
    singular_result = detect_affine2(
        singular_array[:8], singular_array[8:], 16, singular_stats
    )

    output = {
        "episode": 1,
        "panel": {
            "totals": panel["totals"],
            "peak_memory_mb": panel["peak_memory_mb"],
        },
        "models_evaluated": total_models,
        "profitable": {
            "raw_profitable_models": raw_profitable,
            "backend_profitable_models": backend_profitable,
            "with_4b_overhead_models": with4b,
            "word_profitable_union_bytes": profitable_word_bytes,
            "bit_profitable_union_positions": profitable_bit_positions,
        },
        "algebraic": {
            "models": len(algebraic_eval),
            "backend_profitable": sum(
                1 for item in algebraic_eval if item["backend_profitable"]
            ),
            "raw_profitable": sum(1 for item in algebraic_eval if item["raw_profitable"]),
            "span_bytes": sum(item["span_bytes"] for item in algebraic_eval),
        },
        "family_cost": cost_table,
        "bm": bm_summary,
        "modular": dict(aggregate),
        "singular_control": {
            "detected": singular_result is not None,
            "stats": singular_stats,
            "sequence": singular_values,
        },
        "top": top,
        "top_candidates_total": len(candidates),
    }
    target = results / "analysis.json"
    target.write_text(json.dumps(output, indent=1) + "\n", encoding="utf8")
    print(
        json.dumps(
            {
                key: output[key]
                for key in ("models_evaluated", "profitable", "algebraic", "bm")
            },
            indent=1,
        )
    )
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
