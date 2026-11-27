#!/usr/bin/env python3
"""Audit the original Phase 18 integer Haar implementation against a minimal
standard recursive approximation-only Haar lifting reference."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_phase18_original as orig  # noqa: E402
import run_phase18 as corrected  # noqa: E402


def trace_current(values: list[int]) -> tuple[list[int], list[dict]]:
    arr = list(values)
    n = len(arr)
    step = n
    levels = []
    while step >= 2:
        half = step // 2
        for start in range(0, n, step):
            for index in range(half):
                a = arr[start + index]
                b = arr[start + half + index]
                difference = b - a
                average = a + difference // 2
                arr[start + index] = average
                arr[start + half + index] = difference
        max_abs = max(abs(value) for value in arr)
        levels.append(
            {
                "step": step,
                "half": half,
                "blocks": n // step,
                "max_abs_after_level": max_abs,
                "min": min(arr),
                "max": max(arr),
            }
        )
        step = half
    return arr, levels


def ref_haar(values: list[int]) -> list[int]:
    arr = list(values)
    n = len(arr)
    current = n
    while current >= 2:
        half = current // 2
        for index in range(half):
            a = arr[index]
            b = arr[half + index]
            difference = b - a
            average = a + difference // 2
            arr[index] = average
            arr[half + index] = difference
        current = half
    return arr


def ref_inverse(coeffs: list[int]) -> list[int]:
    arr = list(coeffs)
    n = len(arr)
    current = 2
    while current <= n:
        half = current // 2
        for index in range(half):
            average = arr[index]
            difference = arr[half + index]
            a = average - difference // 2
            b = a + difference
            arr[index] = a
            arr[half + index] = b
        current *= 2
    return arr


def reference_levels(values: list[int]) -> tuple[list[int], list[dict]]:
    arr = list(values)
    n = len(arr)
    current = n
    levels = []
    while current >= 2:
        half = current // 2
        for index in range(half):
            a = arr[index]
            b = arr[half + index]
            difference = b - a
            average = a + difference // 2
            arr[index] = average
            arr[half + index] = difference
        approx = arr[:half]
        details = arr[half:current]
        levels.append(
            {
                "current_length": current,
                "approx_min": min(approx),
                "approx_max": max(approx),
                "detail_min": min(details),
                "detail_max": max(details),
                "max_abs_in_current": max(abs(v) for v in arr[:current]),
            }
        )
        current = half
    return arr, levels


def main() -> None:
    dev = json.loads((ROOT / "lab/sxz-spectral/results/phase18-dev-original.json").read_text(encoding="utf8"))
    val = json.loads((ROOT / "lab/sxz-spectral/results/phase18-original.json").read_text(encoding="utf8"))
    selected = val["selected"]
    report = {
        "source": {
            "file": "scripts/run_phase18_original.py",
            "forward_lines": "97-112",
            "inverse_lines": "115-130",
            "forward_loop": "for start in range(0, n, step)",
            "inverse_loop": "for start in range(0, n, step)",
        },
        "selected_configurations": {},
        "levels": {},
        "invariants": {},
        "root_cause": (
            "The original loop processed every block of length step at every level. "
            "After the first level, the second half contains detail coefficients, so "
            "the next level decomposed details as well as approximations. This is a "
            "full wavelet-packet transform, not the standard recursive Haar lifting "
            "that decomposes only the approximation segment."
        ),
    }

    cases = (("7zr", 4096), ("ecg", 4096))
    for name, size in cases:
        relative = next(rel for key, rel, _kind in orig.FILES if key == name)
        data = (ROOT / relative).read_bytes()[-size:]
        config = selected[name][str(size)]
        block_length = config["block_length"]
        assert config["transform"] == "haar"
        assert config["representation"] == "bytes"
        report["selected_configurations"][name] = config
        current_max = 0
        current_values = set()
        ref_max = 0
        ref_values = set()
        level_stats = []
        mismatch_blocks = 0
        for offset in range(0, size, block_length):
            block = data[offset : offset + block_length]
            cur, cur_levels = trace_current(list(block))
            ref, ref_levels = reference_levels(list(block))
            current_max = max(current_max, max(abs(v) for v in cur))
            ref_max = max(ref_max, max(abs(v) for v in ref))
            current_values.update(cur)
            ref_values.update(ref)
            if cur != ref:
                mismatch_blocks += 1
            if not level_stats:
                level_stats = cur_levels
        report["levels"][name] = {
            "block_length": block_length,
            "current_per_block_first_block": level_stats,
            "current_max_abs_all_blocks": current_max,
            "reference_max_abs_all_blocks": ref_max,
            "current_distinct_values": len(current_values),
            "reference_distinct_values": len(ref_values),
            "blocks_current_differs_from_reference": mismatch_blocks,
            "reported_max_abs_in_episode": val["validation"]["files"][
                next(i for i, f in enumerate(val["validation"]["files"]) if f["name"] == name)
            ]["regions"]["4096"]["max_abs"],
        }
        # Exact reconstruction assertions for the original and reference maps.
        block = data[:block_length]
        cur, _ = trace_current(list(block))
        assert orig.haar_inverse(cur) == list(block)
        ref, _ = reference_levels(list(block))
        assert ref_inverse(ref) == list(block)
        # Standard invariants on the reference transform.
        for offset in range(0, size, block_length):
            block = data[offset : offset + block_length]
            coeffs, levels = reference_levels(list(block))
            for level in levels:
                assert 0 <= level["approx_min"] <= level["approx_max"] <= 255
                assert -255 <= level["detail_min"] <= level["detail_max"] <= 255
                assert level["max_abs_in_current"] <= 255
            assert max(abs(v) for v in coeffs) <= 255
            assert len(set(coeffs)) <= 511
        report["invariants"][name] = {
            "reference_approx_range_ok": True,
            "reference_detail_range_ok": True,
            "reference_max_abs_le_255": True,
            "reference_distinct_le_511": True,
            "current_max_abs_le_255": current_max <= 255,
            "current_distinct_le_511": len(current_values) <= 511,
        }

    # Confirm the reported statistics belong to the selected Haar records and
    # compare with the FWHT row for the same regions.
    provenance = {}
    for file_record in val["validation"]["files"]:
        name = file_record["name"]
        region = file_record["regions"]["4096"]
        dev_file = next(f for f in dev["files"] if f["name"] == name)
        dev_rows = dev_file["regions"]["4096"]["rows"]
        fwht = [row for row in dev_rows if row["transform"] == "fwht"]
        provenance[name] = {
            "selected_transform": region["transform"],
            "selected_representation": region["representation"],
            "reported_max_abs": region["max_abs"],
            "reported_distinct": region["distinct_values"],
            "selected_is_haar_bytes": region["transform"] == "haar"
            and region["representation"] == "bytes",
            "fwht_max_abs_values": sorted({row["max_abs"] for row in fwht}),
        }
    report["reported_statistics_provenance"] = provenance
    corrected_evidence = {}
    for name, size in cases:
        relative = next(rel for key, rel, _kind in orig.FILES if key == name)
        data = (ROOT / relative).read_bytes()[-size:]
        config = selected[name][str(size)]
        block_length = config["block_length"]
        max_abs = 0
        distinct = set()
        exact = True
        reference_equal = True
        for offset in range(0, size, block_length):
            block = list(data[offset : offset + block_length])
            coeffs = corrected.haar_forward(block)
            max_abs = max(max_abs, max(abs(v) for v in coeffs))
            distinct.update(coeffs)
            exact = exact and corrected.haar_inverse(coeffs) == block
            reference_equal = reference_equal and coeffs == ref_haar(block)
        corrected_evidence[name] = {
            "max_abs": max_abs,
            "distinct_values": len(distinct),
            "inverse_exact": exact,
            "equals_reference": reference_equal,
            "max_abs_le_255": max_abs <= 255,
            "distinct_le_511": len(distinct) <= 511,
        }
    report["corrected_implementation"] = corrected_evidence
    report["assertions"] = {
        "original_inverse_exact": True,
        "reference_inverse_exact": True,
        "reference_range_invariants": True,
        "corrected_equals_reference": all(item["equals_reference"] for item in corrected_evidence.values()),
        "corrected_range_invariants": all(item["max_abs_le_255"] and item["distinct_le_511"] for item in corrected_evidence.values()),
        "reported_stats_are_selected_haar_bytes": all(
            item["selected_is_haar_bytes"] for item in provenance.values()
        ),
    }
    out = ROOT / "lab/sxz-spectral/results/phase18-haar-audit.json"
    out.write_text(json.dumps(report, indent=1) + "\n", encoding="utf8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
