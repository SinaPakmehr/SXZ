#!/usr/bin/env python3
"""Phase 20 Episode 1: structural attribution of exact algebraic dependencies.

No new compression codec.  This script audits the Phase 19 7zr finding,
maps it into the PE image, and runs a bounded exhaustive census on independent
executables and non-executable comparison files.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import lzma
import os
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[3]
SYSTEM_ROOT = Path(os.environ.get("SystemRoot", ""))
sys.path.insert(0, str(ROOT / "lab/sxz-emar/scripts"))
import run_phase17 as ep1  # noqa: E402

RESULTS = ROOT / "lab/sxz-attribution/results"
MASK64 = (1 << 64) - 1
BLOCK = 8
Z9 = ep1.Z9
Z19 = ep1.Z19
LZMA_FILTERS = ep1.LZMA_FILTERS

EXES = (
    SYSTEM_ROOT / "System32/notepad.exe",
    SYSTEM_ROOT / "System32/cmd.exe",
    SYSTEM_ROOT / "System32/kernel32.dll",
    SYSTEM_ROOT / "System32/advapi32.dll",
    SYSTEM_ROOT / "System32/WindowsPowerShell/v1.0/powershell.exe",
)
NONEXE = (
    "datasets/corpus/book1",
    "datasets/corpus/bbc.rss.xml",
    "datasets/corpus/irs1040.pdf",
    "datasets/corpus/hopper.bmp",
    "datasets/corpus/ecg-holdout.bin",
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_pe(path: Path) -> tuple[bytes, list[dict]] | None:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
        return None
    coff = e_lfanew + 4
    machine, section_count, _timestamp, _symptr, _nsyms, optional_size, _chars = struct.unpack_from(
        "<HHIIIHH", data, coff
    )
    section_table = coff + 20 + optional_size
    sections = []
    for index in range(section_count):
        offset = section_table + index * 40
        name = data[offset : offset + 8].rstrip(b"\0").decode("latin1", "replace")
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from(
            "<IIII", data, offset + 8
        )
        sections.append(
            {
                "name": name,
                "virtual_address": virtual_address,
                "virtual_size": virtual_size,
                "raw_pointer": raw_pointer,
                "raw_size": raw_size,
            }
        )
    return data, sections


def section_at(sections: list[dict], offset: int) -> str:
    for section in sections:
        start = section["raw_pointer"]
        end = start + section["raw_size"]
        if start <= offset < end:
            return section["name"]
    return "overlay"


def select_regions(data: bytes, sections: list[dict]) -> list[dict]:
    regions = []
    used = set()

    def add(label: str, offset: int) -> None:
        if offset < 0 or offset + 4096 > len(data) or offset in used:
            return
        used.add(offset)
        regions.append(
            {
                "label": label,
                "offset": offset,
                "section": section_at(sections, offset),
                "end_section": section_at(sections, offset + 4095),
            }
        )

    for section in sections:
        name = section["name"]
        start = section["raw_pointer"]
        size = section["raw_size"]
        if size < 4096:
            continue
        if name in (".text", ".rdata", ".data", ".rsrc"):
            aligned = ((start + 4095) // 4096) * 4096
            if aligned + 4096 <= start + size:
                add(name[1:], aligned)
        elif name == ".reloc":
            tail = start + size - 4096
            add("reloc-tail", tail)
    add("uniform", ((len(data) // 2) // 4096) * 4096)
    return regions


def split_blocks(data: bytes, offset: int) -> list[int]:
    return [
        int.from_bytes(data[position : position + 8], "big")
        for position in range(offset, offset + 4096, 8)
    ]


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


def classify(value: int, counts: Counter[int]) -> tuple[bool, bool, bool, bool]:
    data = value.to_bytes(8, "big")
    zero = value == 0
    constant = len(set(data)) == 1
    short_period = False
    for period in (2, 4):
        if all(data[index] == data[index % period] for index in range(8)):
            short_period = True
            break
    repeated = counts[value] > 1
    return zero, constant, short_period, repeated


def basis_summary(values: list[int], counts: Counter[int]) -> dict | None:
    if not values:
        return None
    basis: dict[int, int] = {}
    for value in values:
        current = value
        for pivot in sorted(basis, reverse=True):
            if current >> pivot & 1:
                current ^= basis[pivot]
        if current:
            basis[current.bit_length() - 1] = current
    pivots = sorted(basis, reverse=True)
    weights = []
    for value in values:
        current = value
        mask = 0
        for bit, pivot in enumerate(pivots):
            if current >> pivot & 1:
                current ^= basis[pivot]
                mask ^= 1 << bit
        if current:
            raise AssertionError("basis does not span value")
        weights.append(mask.bit_count())
    occurrence_sum = sum(counts[value] for value in values)
    literal_payload = occurrence_sum * 8
    literal_with_tag = occurrence_sum * 9
    basis_payload = len(pivots) * 8
    refs_one_byte = sum(1 + weight for weight in weights)
    compact_bits = sum(2 + weight * 5 for weight in weights)
    compact_bytes = (compact_bits + 7) // 8
    return {
        "values": len(values),
        "rank": len(pivots),
        "nullity": len(values) - len(pivots),
        "weights": dict(sorted(Counter(weights).items())),
        "max_weight": max(weights),
        "average_weight": round(sum(weights) / len(weights), 6),
        "basis_payload_bytes": basis_payload,
        "literal_payload_bytes": literal_payload,
        "literal_with_tag_bytes": literal_with_tag,
        "ref_cost_one_byte_ids": refs_one_byte,
        "total_one_byte_ids": basis_payload + refs_one_byte,
        "compact_ref_bytes": compact_bytes,
        "total_compact": basis_payload + compact_bytes,
        "credible_advantage": min(basis_payload + refs_one_byte, basis_payload + compact_bytes)
        < literal_payload,
    }


def additive_summary(distinct: list[int], counts: Counter[int]) -> dict:
    value_set = set(distinct)
    pair_sums: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for left_index in range(len(distinct)):
        left = distinct[left_index]
        for right_index in range(left_index):
            right = distinct[right_index]
            pair_sums[(left + right) & MASK64].append((left, right))
    add3 = set()
    for result, pairs in pair_sums.items():
        if result in value_set:
            for left, right in pairs:
                if left != result and right != result:
                    add3.add(frozenset((left, right, result)))
    add4_values = set()
    add4_count = 0
    for pairs in pair_sums.values():
        if len(pairs) < 2:
            continue
        degree: Counter[int] = Counter()
        for left, right in pairs:
            degree[left] += 1
            degree[right] += 1
        valid = len(pairs) * (len(pairs) - 1) // 2 - sum(
            count * (count - 1) // 2 for count in degree.values()
        )
        if valid:
            add4_count += valid
            for left, right in pairs:
                add4_values.add(left)
                add4_values.add(right)
    return {
        "add3_equations": len(add3),
        "add3_values": len(set().union(*add3)) if add3 else 0,
        "add3_coverage_bytes": sum(
            counts[value] * 8 for value in (set().union(*add3) if add3 else set())
        ),
        "add4_equations": add4_count,
        "add4_values": len(add4_values),
        "add4_coverage_bytes": sum(counts[value] * 8 for value in add4_values),
    }


def xor_census(blocks: list[int]) -> dict:
    counts = Counter(blocks)
    distinct = sorted(counts)
    value_set = set(distinct)
    pair_groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for left_index in range(len(distinct)):
        left = distinct[left_index]
        for right_index in range(left_index):
            right = distinct[right_index]
            pair_groups[left ^ right].append((left, right))
    triples = set()
    quads = set()
    for result, pairs in pair_groups.items():
        if result in value_set:
            for left, right in pairs:
                if left != result and right != result:
                    triples.add(frozenset((left, right, result)))
        for first, second in itertools.combinations(pairs, 2):
            values = (first[0], first[1], second[0], second[1])
            if len(set(values)) == 4:
                quads.add(frozenset(values))
    values = set()
    for item in triples | quads:
        values.update(item)
    category_values = {
        "zero": set(),
        "constant": set(),
        "short_period": set(),
        "repeated": set(),
    }
    for value in values:
        zero, constant, short_period, repeated = classify(value, counts)
        if zero:
            category_values["zero"].add(value)
        if constant:
            category_values["constant"].add(value)
        if short_period:
            category_values["short_period"].add(value)
        if repeated:
            category_values["repeated"].add(value)
    nontrivial = values - set().union(*category_values.values())
    active_lanes = Counter()
    shared_lane_hist = Counter()
    lane_explained = 0
    for quadruple in quads:
        lanes = [value.to_bytes(8, "big") for value in quadruple]
        active = sum(1 for lane in range(8) if len({item[lane] for item in lanes}) > 1)
        active_lanes[active] += 1
        shared_lane_hist[8 - active] += 1
        if active <= 2:
            lane_explained += 1
    return {
        "blocks": len(blocks),
        "distinct": len(distinct),
        "rank": gf2_rank(distinct),
        "nullity": len(distinct) - gf2_rank(distinct),
        "three_equations": len(triples),
        "four_quadruples": len(quads),
        "relationship_values": len(values),
        "relationship_coverage_bytes": sum(counts[value] * 8 for value in values),
        "relationship_coverage_fraction": sum(counts[value] * 8 for value in values) / 4096,
        "nontrivial_values": len(nontrivial),
        "nontrivial_coverage_bytes": sum(counts[value] * 8 for value in nontrivial),
        "nontrivial_coverage_fraction": sum(counts[value] * 8 for value in nontrivial) / 4096,
        "category_coverage": {
            category: {
                "values": len(items),
                "coverage_bytes": sum(counts[value] * 8 for value in items),
            }
            for category, items in category_values.items()
        },
        "active_lane_histogram": dict(sorted(active_lanes.items())),
        "shared_lane_histogram": dict(sorted(shared_lane_hist.items())),
        "active_lanes_le_2": lane_explained,
        "basis": basis_summary(sorted(values), counts),
        "distinct_values_list": distinct,
        "relationship_values_list": sorted(values),
        "quadruples_list": [sorted(item) for item in quads],
    }


def shfl(data: bytes, width: int) -> tuple[bytes, bytes]:
    body_len = len(data) - len(data) % width
    body = b"".join(data[lane:body_len:width] for lane in range(width))
    return body, data[body_len:]


def compression_controls(data: bytes) -> dict:
    candidates = {
        "A_zstd9": len(Z9.compress(data)),
        "B_zstd19": len(Z19.compress(data)),
        "C_lzma2": len(lzma.compress(data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)) + 1,
        "delta_zstd9": len(Z9.compress(ep1.delta_encode(data))) + 1,
        "xor_zstd9": len(Z9.compress(bytes([data[0]]) + bytes(
            data[index] ^ data[index - 1] for index in range(1, len(data))
        ))) + 1,
    }
    for width in (2, 4, 8):
        body, trailing = shfl(data, width)
        candidates[f"shuffle{width}_zstd9"] = len(Z9.compress(body)) + 1 + len(trailing)
    try:
        bcj = lzma.compress(
            data,
            format=lzma.FORMAT_RAW,
            filters=[{"id": lzma.FILTER_X86}, {"id": lzma.FILTER_LZMA2, "preset": 6}],
        )
        candidates["bcj_x86_lzma2"] = len(bcj) + 1
    except Exception:
        candidates["bcj_x86_lzma2"] = 10**9
    best = min(candidates, key=lambda name: (candidates[name], name))
    return {"sizes": candidates, "best": best, "best_bytes": candidates[best]}


def apply_full_region_cost(census: dict) -> None:
    basis = census.get("basis")
    controls = census.get("controls")
    if not basis or not controls:
        return
    occurrences = census["relationship_coverage_bytes"] // 8
    other_blocks = census["blocks"] - occurrences
    subset = min(basis["total_one_byte_ids"], basis["total_compact"])
    full = subset + other_blocks * 9
    basis["full_region_estimate_bytes"] = full
    basis["credible_advantage"] = full < controls["best_bytes"]


def census_region(data: bytes, offset: int) -> dict:
    blocks = split_blocks(data, offset)
    census = xor_census(blocks)
    census["additive"] = additive_summary(census["distinct_values_list"], Counter(blocks))
    census["controls"] = compression_controls(data[offset : offset + 4096])
    apply_full_region_cost(census)
    # Remove bulky per-value lists from the final record.
    census.pop("distinct_values_list", None)
    census.pop("relationship_values_list", None)
    census.pop("quadruples_list", None)
    return census


def main() -> None:
    started = time.perf_counter()
    original_path = ROOT / "datasets/corpus/7zr.exe"
    original_data, original_sections = parse_pe(original_path)
    original_offset = len(original_data) - 4096
    original_blocks = split_blocks(original_data, original_offset)
    original_census = xor_census(original_blocks)
    original_values = set(original_census["relationship_values_list"])
    value_offsets = defaultdict(list)
    for index, value in enumerate(original_blocks):
        if value in original_values:
            value_offsets[value].append(original_offset + index * 8)
    section_counts = Counter()
    for offsets in value_offsets.values():
        for absolute in offsets:
            section_counts[section_at(original_sections, absolute)] += 1

    reloc_section = next(
        (section for section in original_sections if section["name"] == ".reloc"), None
    )
    reloc_blocks = []
    if reloc_section:
        raw = original_data[
            reloc_section["raw_pointer"] : reloc_section["raw_pointer"] + reloc_section["raw_size"]
        ]
        pos = 0
        while pos + 8 <= len(raw):
            page, size = struct.unpack_from("<II", raw, pos)
            if size < 8 or pos + size > len(raw):
                break
            reloc_blocks.append((reloc_section["raw_pointer"] + pos, page, size))
            pos += size
    participant_reloc = Counter()
    participant_reloc_blocks = set()
    participant_pages = set()
    entry_alignments = Counter()
    for offsets in value_offsets.values():
        for absolute in offsets:
            for block_start, page, size in reversed(reloc_blocks):
                if block_start <= absolute < block_start + size:
                    participant_reloc_blocks.add(block_start)
                    participant_pages.add(page)
                    within = absolute - block_start
                    if within >= 8:
                        entry_alignments[(within - 8) % 2] += 1
                    participant_reloc[block_start] += 1
                    break
    original_census["additive"] = additive_summary(
        original_census["distinct_values_list"], Counter(original_blocks)
    )
    original_census["controls"] = compression_controls(original_data[-4096:])
    apply_full_region_cost(original_census)
    original_census["attribution"] = {
        "region_offset": original_offset,
        "region_section": section_at(original_sections, original_offset),
        "participant_section_counts": dict(section_counts),
        "participant_values": len(original_values),
        "participant_occurrences": sum(len(values) for values in value_offsets.values()),
        "participant_bytes": sum(len(values) for values in value_offsets.values()) * 8,
        "reloc_blocks": len(reloc_blocks),
        "participant_reloc_blocks": len(participant_reloc_blocks),
        "participant_pages": len(participant_pages),
        "entry_alignment": dict(entry_alignments),
        "section_layout": original_sections,
    }
    original_census.pop("distinct_values_list", None)
    original_census.pop("relationship_values_list", None)
    original_census.pop("quadruples_list", None)

    independent = []
    for path in EXES:
        parsed = parse_pe(path)
        if not parsed:
            continue
        data, sections = parsed
        file_record = {
            "name": path.name,
            "path": "SystemRoot/" + str(path.relative_to(SYSTEM_ROOT)).replace("\\", "/"),
            "bytes": len(data),
            "sha256": sha256(data),
            "sections": [section["name"] for section in sections],
            "regions": [],
        }
        for region in select_regions(data, sections):
            census = census_region(data, region["offset"])
            file_record["regions"].append({**region, **census})
        independent.append(file_record)

    nonexec = []
    for relative in NONEXE:
        data = (ROOT / relative).read_bytes()
        offset = ((len(data) // 2) // 4096) * 4096
        if offset + 4096 > len(data):
            offset = max(0, len(data) - 4096)
        record = census_region(data, offset)
        nonexec.append(
            {
                "name": Path(relative).name,
                "path": relative,
                "bytes": len(data),
                "sha256": sha256(data),
                "offset": offset,
                **record,
            }
        )

    qualifying = []
    for file_record in independent:
        best = max(
            file_record["regions"],
            key=lambda region: region["nontrivial_coverage_fraction"],
        )
        if best["nontrivial_coverage_fraction"] >= 0.10:
            qualifying.append(
                {
                    "file": file_record["name"],
                    "section": best["section"],
                    "offset": best["offset"],
                    "nontrivial_coverage_fraction": best["nontrivial_coverage_fraction"],
                    "basis": best["basis"],
                    "controls": best["controls"],
                }
            )
    credible = [
        item
        for item in qualifying
        if item["basis"] is not None and item["basis"]["credible_advantage"]
    ]

    output = {
        "phase": 20,
        "audit": "structural attribution of exact algebraic dependencies",
        "original_7zr": original_census,
        "independent_executables": independent,
        "nonexecutables": nonexec,
        "gate": {
            "min_nontrivial_coverage": 0.10,
            "min_independent_files": 2,
            "qualifying_files": qualifying,
            "credible_cost_advantage_files": credible,
            "passed": len(qualifying) >= 2 and bool(credible),
        },
        "reporting_corrections": {
            "single_atom_blocks": {"7zr": 44, "bbc": 2, "irs1040": 23},
            "reconstruction_count": "12 paired F/G checks = 24 individual archives (6 files x 2 modes x 2 variants)",
            "reference_cost": "payload-only bound is 32*(8-4)=128 bytes compact and 32*(8-7)=32 bytes varint; the earlier 160/64 added a literal tag on one side only",
            "coverage_reconciliation": "L8 validation total 936 bytes vs nontrivial 872; difference 64 = BBC 3 repeated values (48) + hopper 1 repeated value (16); zero/constant/short-period contribute 0",
        },
        "elapsed_s": round(time.perf_counter() - started, 3),
    }
    out = RESULTS / "phase20-attribution.json"
    out.write_text(json.dumps(output, indent=1) + "\n", encoding="utf8")
    print(json.dumps(output["gate"], indent=1))
    print("elapsed", output["elapsed_s"])


if __name__ == "__main__":
    main()
