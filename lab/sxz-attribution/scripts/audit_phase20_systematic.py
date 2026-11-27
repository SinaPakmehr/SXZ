#!/usr/bin/env python3
"""Phase 20 final algebraic cost audit: systematic GF(2) coefficient masks.

Basis vectors are selected directly from original participating vectors and
stored literally.  Dependent vectors use one packed r-bit mask each, with a
continuous bitstream (no per-mask byte padding).  Full-region archives charge
basis positions, reconstruction order, occurrence mapping, literals,
metadata and framing.  No new general-purpose codec is introduced.
"""

from __future__ import annotations

import hashlib
import itertools
import json
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
MAGIC = b"SXZ20A1"
Z9 = ep1.Z9


def uvarint(value: int) -> bytes:
    return ep1.uvarint(value)


def read_uvarint(buf: bytes, pos: int) -> tuple[int, int]:
    return ep1.read_uvarint(buf, pos)


def pack_bits(values: list[int], width: int) -> bytes:
    if width == 0:
        return b""
    buffer = 0
    bits = 0
    out = bytearray()
    for value in values:
        buffer = (buffer << width) | value
        bits += width
        while bits >= 8:
            bits -= 8
            out.append((buffer >> bits) & 255)
            buffer &= (1 << bits) - 1
    if bits:
        out.append((buffer << (8 - bits)) & 255)
    return bytes(out)


def unpack_bits(data: bytes, count: int, width: int) -> list[int]:
    if width == 0:
        return [0] * count
    total_bits = len(data) * 8
    buffer = int.from_bytes(data, "big")
    return [
        (buffer >> (total_bits - (index + 1) * width)) & ((1 << width) - 1)
        for index in range(count)
    ]


def relationship_values(blocks: list[int]) -> list[int]:
    counts = Counter(blocks)
    distinct = sorted(counts)
    value_set = set(distinct)
    groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for left_index in range(len(distinct)):
        left = distinct[left_index]
        for right_index in range(left_index):
            right = distinct[right_index]
            groups[left ^ right].append((left, right))
    quads = set()
    for result, pairs in groups.items():
        if result in value_set:
            continue
        for first, second in itertools.combinations(pairs, 2):
            values = (first[0], first[1], second[0], second[1])
            if len(set(values)) == 4:
                quads.add(frozenset(values))
    values = set()
    for quad in quads:
        values.update(quad)
    return sorted(values)


def select_basis(values: list[int], first: dict[int, int]) -> tuple[list[int], list[int], dict]:
    by_position = sorted(values, key=lambda value: first[value])
    rank_basis: dict[int, int] = {}
    basis_values = []
    basis_positions = []
    for value in by_position:
        current = value
        for pivot in sorted(rank_basis, reverse=True):
            if current >> pivot & 1:
                current ^= rank_basis[pivot]
        if current:
            rank_basis[current.bit_length() - 1] = current
            basis_values.append(value)
            basis_positions.append(first[value])
    # RREF-style pivot representation in terms of the original basis values.
    reduced: dict[int, int] = {}
    combos: dict[int, int] = {}
    for index, value in enumerate(basis_values):
        current = value
        combo = 1 << index
        for pivot in sorted(reduced, reverse=True):
            if current >> pivot & 1:
                current ^= reduced[pivot]
                combo ^= combos[pivot]
        if not current:
            raise AssertionError("selected basis is not independent")
        reduced[current.bit_length() - 1] = current
        combos[current.bit_length() - 1] = combo
    dependent_values = [value for value in by_position if value not in set(basis_values)]
    masks = []
    for value in dependent_values:
        current = value
        combo = 0
        for pivot in sorted(reduced, reverse=True):
            if current >> pivot & 1:
                current ^= reduced[pivot]
                combo ^= combos[pivot]
        if current:
            raise AssertionError("basis does not span target")
        masks.append(combo)
    return basis_values, dependent_values, {
        "basis_positions": basis_positions,
        "masks": masks,
        "rank": len(basis_values),
        "dependent_positions": [first[value] for value in dependent_values],
    }


def build_header(
    mode: int,
    has_mapping: bool,
    block_count: int,
    region_bytes: int,
    n: int,
    r: int,
    dep: int,
    basis_width: int,
    dep_width: int,
    basis_positions: list[int],
    dep_positions: list[int],
    payload_lengths: list[int],
) -> bytes:
    header = bytearray(MAGIC)
    header.append(mode)
    header.append(1 if has_mapping else 0)
    header += uvarint(block_count)
    header += uvarint(region_bytes)
    header += uvarint(n)
    header += uvarint(r)
    header += uvarint(dep)
    header.append(basis_width)
    header.append(dep_width)
    for position in basis_positions:
        header += uvarint(position)
    for position in dep_positions:
        header += uvarint(position)
    for length in payload_lengths:
        header += uvarint(length)
    return bytes(header)


def build_systematic(
    blocks: list[int],
    values: list[int],
    basis: list[int],
    dependent: list[int],
    masks: list[int],
    mapping: bool,
) -> tuple[bytes, dict]:
    counts = Counter(blocks)
    first = {}
    for index, value in enumerate(blocks):
        if value not in first:
            first[value] = index
    basis_positions = [first[value] for value in basis]
    dep_positions = [first[value] for value in dependent]
    r = len(basis)
    dep = len(dependent)
    r_width = max(1, (r - 1).bit_length()) if r else 0
    dep_width = max(1, (dep - 1).bit_length()) if dep else 0
    basis_data = b"".join(value.to_bytes(8, "big") for value in basis)
    coeff_data = pack_bits([mask for mask in masks], r)
    value_to_class: dict[int, tuple[int, int]] = {}
    for index, value in enumerate(basis):
        value_to_class[value] = (1, index)
    for index, value in enumerate(dependent):
        value_to_class[value] = (2, index)

    tags = []
    basis_refs = []
    dep_refs = []
    literals = bytearray()
    if mapping:
        for block in blocks:
            entry = value_to_class.get(block)
            if entry is None:
                tags.append(0)
                literals += block.to_bytes(8, "big")
            elif entry[0] == 1:
                tags.append(1)
                basis_refs.append(entry[1])
            else:
                tags.append(2)
                dep_refs.append(entry[1])
    tag_data = pack_bits(tags, 2) if mapping else b""
    basis_ref_data = pack_bits(basis_refs, r_width) if mapping else b""
    dep_ref_data = pack_bits(dep_refs, dep_width) if mapping else b""
    payload_lengths = [
        len(basis_data),
        len(coeff_data),
        len(tag_data),
        len(basis_ref_data),
        len(dep_ref_data),
        len(literals),
    ]
    header = build_header(
        0,
        mapping,
        len(blocks),
        len(blocks) * 8,
        len(values),
        r,
        dep,
        r_width,
        dep_width,
        basis_positions,
        dep_positions,
        payload_lengths,
    )
    archive = (
        header
        + basis_data
        + coeff_data
        + tag_data
        + basis_ref_data
        + dep_ref_data
        + bytes(literals)
    )
    meta = {
        "mode": "systematic",
        "mapping": mapping,
        "n": len(values),
        "rank": r,
        "dependent": dep,
        "header_bytes": len(header),
        "basis_bytes": len(basis_data),
        "coefficient_bytes": len(coeff_data),
        "tag_bytes": len(tag_data),
        "basis_ref_bytes": len(basis_ref_data),
        "dependent_ref_bytes": len(dep_ref_data),
        "literal_bytes": len(literals),
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
    }
    return archive, meta


def build_ordinary(
    blocks: list[int],
    values: list[int],
    basis: list[int],
    dependent: list[int],
    mapping: bool,
) -> tuple[bytes, dict]:
    counts = Counter(blocks)
    first = {}
    for index, value in enumerate(blocks):
        if value not in first:
            first[value] = index
    ordered = basis + dependent
    basis_positions = [first[value] for value in basis]
    dep_positions = [first[value] for value in dependent]
    r = len(basis)
    dep = len(dependent)
    r_width = max(1, (r - 1).bit_length()) if r else 0
    dep_width = max(1, (dep - 1).bit_length()) if dep else 0
    value_data = b"".join(value.to_bytes(8, "big") for value in ordered)
    value_to_class = {}
    for index, value in enumerate(basis):
        value_to_class[value] = (1, index)
    for index, value in enumerate(dependent):
        value_to_class[value] = (2, index)
    tags = []
    basis_refs = []
    dep_refs = []
    literals = bytearray()
    if mapping:
        for block in blocks:
            entry = value_to_class.get(block)
            if entry is None:
                tags.append(0)
                literals += block.to_bytes(8, "big")
            elif entry[0] == 1:
                tags.append(1)
                basis_refs.append(entry[1])
            else:
                tags.append(2)
                dep_refs.append(entry[1])
    tag_data = pack_bits(tags, 2) if mapping else b""
    basis_ref_data = pack_bits(basis_refs, r_width) if mapping else b""
    dep_ref_data = pack_bits(dep_refs, dep_width) if mapping else b""
    payload_lengths = [
        len(value_data),
        0,
        len(tag_data),
        len(basis_ref_data),
        len(dep_ref_data),
        len(literals),
    ]
    header = build_header(
        1,
        mapping,
        len(blocks),
        len(blocks) * 8,
        len(values),
        r,
        dep,
        r_width,
        dep_width,
        basis_positions,
        dep_positions,
        payload_lengths,
    )
    archive = (
        header
        + value_data
        + tag_data
        + basis_ref_data
        + dep_ref_data
        + bytes(literals)
    )
    meta = {
        "mode": "ordinary",
        "mapping": mapping,
        "n": len(values),
        "rank": r,
        "dependent": dep,
        "header_bytes": len(header),
        "dictionary_bytes": len(value_data),
        "tag_bytes": len(tag_data),
        "basis_ref_bytes": len(basis_ref_data),
        "dependent_ref_bytes": len(dep_ref_data),
        "literal_bytes": len(literals),
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
    }
    return archive, meta


def build_literal(blocks: list[int]) -> tuple[bytes, dict]:
    header = bytearray(MAGIC)
    header.append(2)
    header.append(0)
    header += uvarint(len(blocks))
    header += uvarint(len(blocks) * 8)
    header += uvarint(0)
    header += uvarint(0)
    header += uvarint(0)
    header.append(0)
    header.append(0)
    for _ in range(6):
        header += uvarint(0)
    payload = b"".join(block.to_bytes(8, "big") for block in blocks)
    archive = bytes(header) + payload
    return archive, {
        "mode": "literal",
        "header_bytes": len(header),
        "literal_bytes": len(payload),
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
    }


def parse_header(archive: bytes) -> tuple[dict, int]:
    if archive[: len(MAGIC)] != MAGIC:
        raise ValueError("bad systematic magic")
    pos = len(MAGIC)
    mode = archive[pos]
    pos += 1
    has_mapping = bool(archive[pos])
    pos += 1
    block_count, pos = read_uvarint(archive, pos)
    region_bytes, pos = read_uvarint(archive, pos)
    n, pos = read_uvarint(archive, pos)
    r, pos = read_uvarint(archive, pos)
    dep, pos = read_uvarint(archive, pos)
    r_width = archive[pos]
    pos += 1
    dep_width = archive[pos]
    pos += 1
    basis_positions = []
    for _ in range(r):
        value, pos = read_uvarint(archive, pos)
        basis_positions.append(value)
    dep_positions = []
    for _ in range(dep):
        value, pos = read_uvarint(archive, pos)
        dep_positions.append(value)
    lengths = []
    for _ in range(6):
        value, pos = read_uvarint(archive, pos)
        lengths.append(value)
    return {
        "mode": mode,
        "mapping": has_mapping,
        "block_count": block_count,
        "region_bytes": region_bytes,
        "n": n,
        "r": r,
        "dep": dep,
        "r_width": r_width,
        "dep_width": dep_width,
        "basis_positions": basis_positions,
        "dep_positions": dep_positions,
        "lengths": lengths,
    }, pos


def decode_archive(archive: bytes) -> tuple[list[int] | bytes, dict]:
    header, pos = parse_header(archive)
    mode = header["mode"]
    lengths = header["lengths"]
    if mode == 2:
        payload = archive[pos:]
        return payload, header
    if mode == 0:
        basis_data = archive[pos : pos + lengths[0]]
        pos += lengths[0]
        coeff_data = archive[pos : pos + lengths[1]]
        pos += lengths[1]
        basis = [
            int.from_bytes(basis_data[index * 8 : (index + 1) * 8], "big")
            for index in range(header["r"])
        ]
        masks = unpack_bits(coeff_data, header["dep"], header["r"])
        dependent = []
        for mask in masks:
            value = 0
            for index in range(header["r"]):
                if mask >> index & 1:
                    value ^= basis[index]
            dependent.append(value)
        values = basis + dependent
    elif mode == 1:
        value_data = archive[pos : pos + lengths[0]]
        pos += lengths[0]
        values = [
            int.from_bytes(value_data[index * 8 : (index + 1) * 8], "big")
            for index in range(header["n"])
        ]
    else:
        raise ValueError("bad mode")
    if not header["mapping"]:
        return values, header
    tag_data = archive[pos : pos + lengths[2]]
    pos += lengths[2]
    basis_ref_data = archive[pos : pos + lengths[3]]
    pos += lengths[3]
    dep_ref_data = archive[pos : pos + lengths[4]]
    pos += lengths[4]
    literals = archive[pos : pos + lengths[5]]
    pos += lengths[5]
    if pos != len(archive):
        raise ValueError("trailing systematic bytes")
    tags = unpack_bits(tag_data, header["block_count"], 2)
    basis_refs = unpack_bits(basis_ref_data, tags.count(1), header["r_width"])
    dep_refs = unpack_bits(dep_ref_data, tags.count(2), header["dep_width"])
    basis_iter = iter(basis_refs)
    dep_iter = iter(dep_refs)
    literal_pos = 0
    output = bytearray()
    for tag in tags:
        if tag == 0:
            output += literals[literal_pos : literal_pos + 8]
            literal_pos += 8
        elif tag == 1:
            output += values[next(basis_iter)].to_bytes(8, "big")
        else:
            output += values[header["r"] + next(dep_iter)].to_bytes(8, "big")
    if len(output) != header["region_bytes"]:
        raise ValueError("bad reconstructed region")
    return bytes(output), header


def resolve_case_path(value: str) -> Path:
    if value.startswith("SystemRoot/"):
        return SYSTEM_ROOT / value[len("SystemRoot/") :]
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def region_controls(phase20: dict, name: str, offset: int) -> dict:
    if name == "7zr":
        return phase20["original_7zr"]["controls"]
    for file_record in phase20["independent_executables"]:
        if file_record["name"] == name:
            for region in file_record["regions"]:
                if region["offset"] == offset:
                    return region["controls"]
    return {}


def main() -> None:
    started = time.perf_counter()
    phase20 = json.loads((RESULTS / "phase20-attribution.json").read_text(encoding="utf8"))
    cases = []
    original_data = (ROOT / "datasets/corpus/7zr.exe").read_bytes()
    original_offset = len(original_data) - 4096
    cases.append(
        {
            "name": "7zr",
            "path": "datasets/corpus/7zr.exe",
            "offset": original_offset,
            "section": ".reloc",
        }
    )
    for file_record in phase20["independent_executables"]:
        best = max(
            file_record["regions"],
            key=lambda region: region["nontrivial_coverage_fraction"],
        )
        if best["nontrivial_coverage_fraction"] >= 0.10:
            cases.append(
                {
                    "name": file_record["name"],
                    "path": file_record["path"],
                    "offset": best["offset"],
                    "section": best["section"],
                }
            )

    rows = []
    for case in cases:
        path = resolve_case_path(case["path"])
        data = path.read_bytes()
        region = data[case["offset"] : case["offset"] + 4096]
        blocks = [
            int.from_bytes(region[index : index + 8], "big")
            for index in range(0, 4096, 8)
        ]
        values = relationship_values(blocks)
        first = {}
        for index, block in enumerate(blocks):
            if block not in first:
                first[block] = index
        basis, dependent, info = select_basis(values, first)
        masks = info["masks"]
        systematic, systematic_meta = build_systematic(
            blocks, values, basis, dependent, masks, True
        )
        systematic_dict, systematic_dict_meta = build_systematic(
            blocks, values, basis, dependent, masks, False
        )
        ordinary, ordinary_meta = build_ordinary(blocks, values, basis, dependent, True)
        ordinary_dict, ordinary_dict_meta = build_ordinary(
            blocks, values, basis, dependent, False
        )
        literal, literal_meta = build_literal(blocks)
        # Exact reconstruction checks.
        decoded_region, _decoded_header = decode_archive(systematic)
        if decoded_region != region:
            raise RuntimeError(f"systematic region decode failed: {case['name']}")
        if decode_archive(zstd.ZstdDecompressor().decompress(Z9.compress(systematic)))[0] != region:
            raise RuntimeError(f"systematic compressed decode failed: {case['name']}")
        decoded_values, _ = decode_archive(systematic_dict)
        if decoded_values != basis + dependent:
            raise RuntimeError(f"systematic dictionary decode failed: {case['name']}")
        if decode_archive(ordinary)[0] != region:
            raise RuntimeError(f"ordinary decode failed: {case['name']}")
        if decode_archive(literal)[0] != region:
            raise RuntimeError(f"literal decode failed: {case['name']}")
        controls = region_controls(phase20, case["name"], case["offset"])
        rows.append(
            {
                "name": case["name"],
                "section": case["section"],
                "offset": case["offset"],
                "values": len(values),
                "rank": len(basis),
                "dependent": len(dependent),
                "basis_positions_bytes": len(b"".join(uvarint(value) for value in info["basis_positions"])),
                "dependent_positions_bytes": len(b"".join(uvarint(value) for value in info["dependent_positions"])),
                "theoretical_systematic_payload": len(basis) * 8 + (len(dependent) * len(basis) + 7) // 8,
                "systematic": systematic_meta,
                "systematic_dict": systematic_dict_meta,
                "ordinary": ordinary_meta,
                "ordinary_dict": ordinary_dict_meta,
                "literal": literal_meta,
                "tagged_literal_bytes": len(values) * 9,
                "raw_literal_bytes": len(values) * 8,
                "controls": controls,
                "exact_reconstruction": True,
            }
        )
    output = {
        "phase": 20,
        "audit": "systematic GF(2) coefficient-mask cost audit",
        "cases": rows,
        "gate_unchanged": phase20["gate"],
        "note": (
            "Theoretical coefficient payload is basis_bytes + ceil(dependent*rank/8). "
            "Actual sizes include basis/dependent positions, ordering, mapping, tags, refs, literals, metadata and framing. "
            "No positive result is claimed from theoretical estimates."
        ),
        "elapsed_s": round(time.perf_counter() - started, 3),
    }
    out = RESULTS / "phase20-systematic-audit.json"
    out.write_text(json.dumps(output, indent=1) + "\n", encoding="utf8")
    print(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
