#!/usr/bin/env python3
"""Exhaustive structural XOR census for Phase 19 Episode 1.

The census is independent of dictionary selection and encoding.  It enumerates
all unordered pairs of distinct block values, groups them by XOR, and finds
exact A^B=C and A^B=C^D relationships.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "lab/sxz-emar/scripts"))
import run_phase17 as ep1  # noqa: E402

RESULTS = ROOT / "lab/sxz-xordict/results"
LENGTHS = (8, 16, 32, 64)


def split_blocks(data: bytes, length: int) -> list[int]:
    return [
        int.from_bytes(data[offset : offset + length], "big")
        for offset in range(0, len(data), length)
    ]


def block_data(value: int, length: int) -> bytes:
    return value.to_bytes(length, "big")


def classify(value: int, length: int, counts: Counter) -> tuple[bool, bool, bool, bool, int]:
    data = block_data(value, length)
    zero = value == 0
    constant = len(set(data)) == 1
    short_period = False
    period_found = 0
    for period in range(2, max(2, length // 4) + 1):
        if length % period:
            continue
        if all(data[index] == data[index % period] for index in range(length)):
            short_period = True
            period_found = period
            break
    repeated = counts[value] > 1
    return zero, constant, short_period, repeated, period_found


def gf2_rank(values: list[int]) -> int:
    basis: dict[int, int] = {}
    for value in values:
        current = value
        while current:
            pivot = current.bit_length() - 1
            if pivot in basis:
                current ^= basis[pivot]
            else:
                basis[pivot] = current
                break
    return len(basis)


def census_region(data: bytes, length: int) -> dict:
    blocks = split_blocks(data, length)
    counts = Counter(blocks)
    distinct = sorted(counts)
    value_set = set(distinct)
    pair_groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    pair_count = 0
    for left_index in range(len(distinct)):
        left = distinct[left_index]
        for right_index in range(left_index):
            right = distinct[right_index]
            pair_groups[left ^ right].append((left, right))
            pair_count += 1

    categories = {}
    for value in distinct:
        categories[value] = classify(value, length, counts)

    triples = set()
    three_equations = 0
    groups_with_target = 0
    quadruples = set()
    for result, pairs in pair_groups.items():
        if result in value_set:
            groups_with_target += 1
            for left, right in pairs:
                if left != result and right != result:
                    triples.add(frozenset((left, right, result)))
                    three_equations += 1
        for first, second in itertools.combinations(pairs, 2):
            values = (first[0], first[1], second[0], second[1])
            if len(set(values)) == 4:
                quadruples.add(frozenset(values))

    all_values = set()
    for triple in triples:
        all_values.update(triple)
    for quadruple in quadruples:
        all_values.update(quadruple)

    def coverage(values: set[int]) -> int:
        return sum(counts[value] * length for value in values)

    nontrivial_values = set()
    for value in all_values:
        zero, constant, short_period, repeated, _period = categories[value]
        if not zero and not constant and not short_period and not repeated:
            nontrivial_values.add(value)

    category_values = {
        "zero": set(),
        "constant": set(),
        "short_period": set(),
        "repeated": set(),
    }
    for value in all_values:
        zero, constant, short_period, repeated, _period = categories[value]
        if zero:
            category_values["zero"].add(value)
        if constant:
            category_values["constant"].add(value)
        if short_period:
            category_values["short_period"].add(value)
        if repeated:
            category_values["repeated"].add(value)

    # Relationships where all participating values satisfy the category.
    category_relationships = {}
    for category in category_values:
        selected = set()
        for triple in triples:
            if all(
                (
                    categories[value][0]
                    if category == "zero"
                    else categories[value][1]
                    if category == "constant"
                    else categories[value][2]
                    if category == "short_period"
                    else categories[value][3]
                )
                for value in triple
            ):
                selected.update(triple)
        for quadruple in quadruples:
            if all(
                (
                    categories[value][0]
                    if category == "zero"
                    else categories[value][1]
                    if category == "constant"
                    else categories[value][2]
                    if category == "short_period"
                    else categories[value][3]
                )
                for value in quadruple
            ):
                selected.update(quadruple)
        category_relationships[category] = {
            "values": len(selected & all_values),
            "coverage_bytes": coverage(selected & all_values),
        }

    source_bytes = len(blocks) * length
    dependency = None
    if nontrivial_values and coverage(nontrivial_values) / source_bytes >= 0.10:
        first = {}
        for index, value in enumerate(blocks):
            if value not in first:
                first[value] = index
        supported_values = []
        supported_occurrences = 0
        for target in sorted(nontrivial_values):
            position = first[target]
            support = None
            for quadruple in quadruples:
                if target not in quadruple:
                    continue
                candidate = list(quadruple - {target})
                if all(first[value] < position for value in candidate):
                    support = candidate
                    break
            if support is not None:
                supported_values.append(target)
                supported_occurrences += counts[target]
        id_bits = max(1, (len(blocks) - 1).bit_length())
        compact_ref_bytes = (2 + 3 * id_bits + 7) // 8
        varint_ref_bytes = 1 + 3 * 2
        dependency = {
            "nontrivial_values": len(nontrivial_values),
            "supported_values": len(supported_values),
            "supported_occurrences": supported_occurrences,
            "supported_source_bytes": supported_occurrences * length,
            "dependency_rank": gf2_rank(list(nontrivial_values)),
            "compact_ref_bytes": compact_ref_bytes,
            "varint_ref_bytes": varint_ref_bytes,
            "compact_net_saving_bytes": supported_occurrences
            * (length + 1 - compact_ref_bytes),
            "varint_net_saving_bytes": supported_occurrences
            * (length + 1 - varint_ref_bytes),
            "note": (
                "positions precede the target; each target counted once; no circular "
                "or overlapping target savings. This is an upper-bound diagnostic, "
                "not a new codec."
            ),
        }
    return {
        "block_count": len(blocks),
        "distinct_values": len(distinct),
        "pair_count": pair_count,
        "xor_groups": len(pair_groups),
        "groups_with_target": groups_with_target,
        "three_equations": three_equations,
        "three_value_triples": len(triples),
        "four_value_quadruples": len(quadruples),
        "relationship_values": len(all_values),
        "relationship_coverage_bytes": coverage(all_values),
        "relationship_coverage_fraction": coverage(all_values) / source_bytes,
        "nontrivial_values": len(nontrivial_values),
        "nontrivial_coverage_bytes": coverage(nontrivial_values),
        "nontrivial_coverage_fraction": coverage(nontrivial_values) / source_bytes,
        "zero_values": sum(1 for value in distinct if categories[value][0]),
        "constant_values": sum(1 for value in distinct if categories[value][1]),
        "short_period_values": sum(1 for value in distinct if categories[value][2]),
        "repeated_values": sum(1 for value in distinct if categories[value][3]),
        "repeated_block_occurrences": sum(count for count in counts.values() if count > 1),
        "category_relationships": category_relationships,
        "dependency_analysis": dependency,
        "top_xor_groups": sorted(
            ((len(pairs), result) for result, pairs in pair_groups.items()),
            reverse=True,
        )[:5],
    }


def main() -> None:
    started = time.perf_counter()
    files = []
    for name, relative, kind in ep1.FILES:
        data = (ROOT / relative).read_bytes()
        if len(data) < 8192:
            continue
        record = {
            "name": name,
            "kind": kind,
            "file_bytes": len(data),
            "file_sha256": hashlib.sha256(data).hexdigest(),
            "sizes": {},
        }
        for length in LENGTHS:
            dev = census_region(data[:4096], length)
            val = census_region(data[-4096:], length)
            record["sizes"][str(length)] = {"dev": dev, "val": val}
        files.append(record)

    aggregate = {}
    for length in LENGTHS:
        for split in ("dev", "val"):
            regions = [file["sizes"][str(length)][split] for file in files]
            keys = (
                "block_count",
                "distinct_values",
                "pair_count",
                "xor_groups",
                "groups_with_target",
                "three_equations",
                "three_value_triples",
                "four_value_quadruples",
                "relationship_values",
                "relationship_coverage_bytes",
                "nontrivial_values",
                "nontrivial_coverage_bytes",
                "zero_values",
                "constant_values",
                "short_period_values",
                "repeated_values",
                "repeated_block_occurrences",
            )
            entry = {key: sum(region[key] for region in regions) for key in keys}
            entry["regions"] = len(regions)
            entry["relationship_coverage_fraction"] = entry["relationship_coverage_bytes"] / (
                entry["block_count"] * length
            )
            entry["nontrivial_coverage_fraction"] = entry["nontrivial_coverage_bytes"] / (
                entry["block_count"] * length
            )
            entry["category_relationships"] = {}
            for category in ("zero", "constant", "short_period", "repeated"):
                entry["category_relationships"][category] = {
                    "coverage_bytes": sum(
                        region["category_relationships"][category]["coverage_bytes"]
                        for region in regions
                    ),
                    "values": sum(
                        region["category_relationships"][category]["values"]
                        for region in regions
                    ),
                }
            aggregate[f"{length}_{split}"] = entry

    output = {
        "phase": 19,
        "audit": "exhaustive structural XOR census",
        "lengths": list(LENGTHS),
        "regions": "first and last disjoint 4 KiB regions",
        "files": files,
        "aggregate": aggregate,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "reporting_corrections": {
            "single_atom_blocks": {"7zr": 44, "bbc": 2, "irs1040": 23},
            "reconstruction_count": (
                "12 paired F/G checks equal 24 individual archives: six files x two "
                "modes x two variants (F exact and G compressed)."
            ),
            "selected_vs_available": (
                "Episode 1 selected zero multi-atom encodings. This census measures "
                "available exact relationships independently of selection."
            ),
        },
    }
    out = RESULTS / "phase19-xor-audit.json"
    out.write_text(json.dumps(output, indent=1) + "\n", encoding="utf8")
    print(json.dumps(output["aggregate"], indent=1))
    print("elapsed", output["elapsed_s"])


if __name__ == "__main__":
    main()
