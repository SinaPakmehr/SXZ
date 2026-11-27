#!/usr/bin/env python3
"""Phase 19 Episode 1: exact sparse XOR dictionary compositions.

Aligned blocks are binary vectors over GF(2).  A bounded data-derived atom
dictionary is learned from frequent blocks and frequent pairwise XOR
differences.  Blocks are encoded as literals, one atom, or XOR of two/three
distinct atoms.  Dictionaries are charged in every archive; the decoder needs
no external training data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import sys
import time
from collections import Counter
from pathlib import Path

import zstandard as zstd

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[2]
sys.path.insert(0, str(ROOT / "lab/sxz-emar/scripts"))
import run_phase17 as ep1  # noqa: E402

RESULTS = ROOT / "lab/sxz-xordict/results"
MAGIC = b"SXZ19D1"
MAGIC_E = b"SXZ19E1"
Z9 = ep1.Z9
Z19 = ep1.Z19
LZMA_FILTERS = ep1.LZMA_FILTERS
FILES = ep1.FILES

BLOCK_LENGTHS = (8, 16, 32, 64)
CAPACITIES = (16, 32, 64)
SIZES = (4096,)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def uvarint(value: int) -> bytes:
    return ep1.uvarint(value)


def read_uvarint(buf: bytes, pos: int) -> tuple[int, int]:
    return ep1.read_uvarint(buf, pos)


def split_blocks(data: bytes, length: int) -> list[int]:
    return [
        int.from_bytes(data[offset : offset + length], "big")
        for offset in range(0, len(data), length)
    ]


def block_bytes(value: int, length: int) -> bytes:
    return value.to_bytes(length, "big")


def is_constant(value: int, length: int) -> bool:
    data = block_bytes(value, length)
    return len(set(data)) == 1


def gf2_rank(atoms: list[int]) -> int:
    basis: dict[int, int] = {}
    for value in atoms:
        current = value
        while current:
            pivot = current.bit_length() - 1
            if pivot in basis:
                current ^= basis[pivot]
            else:
                basis[pivot] = current
                break
    return len(basis)


def candidate_atoms(blocks: list[int], length: int, capacity: int) -> list[int]:
    counts = Counter(blocks)
    top_blocks = [value for value, _count in counts.most_common(min(len(counts), 4 * capacity))]
    xor_counts: Counter[int] = Counter()
    xor_source = top_blocks[: min(64, len(top_blocks))]
    for left_index in range(len(xor_source)):
        for right_index in range(left_index):
            xor_counts[xor_source[left_index] ^ xor_source[right_index]] += 1
    candidates = list(dict.fromkeys(top_blocks + [value for value, _count in xor_counts.most_common(4 * capacity)]))
    return candidates[: min(len(candidates), 4 * capacity)]


def best_cost_two(
    block: int,
    atoms: list[int],
    atom_index: dict[int, int],
    length: int,
) -> int:
    cost = length + 1  # literal tag + raw block
    if block in atom_index:
        cost = min(cost, 2)
    for atom in atoms:
        other = block ^ atom
        if other in atom_index and other != atom:
            cost = min(cost, 3)
            break
    return cost


def learn_atoms(blocks: list[int], length: int, capacity: int) -> tuple[list[int], dict]:
    candidates = candidate_atoms(blocks, length, capacity)
    sample = blocks[:: max(1, len(blocks) // 96)][:96]
    atoms: list[int] = []
    atom_index: dict[int, int] = {}
    selected = set()
    stats = {"candidate_pool": len(candidates), "steps": 0, "estimated_gain": 0}
    for _ in range(capacity):
        current_costs = [best_cost_two(block, atoms, atom_index, length) for block in sample]
        best = None
        for candidate in candidates:
            if candidate in selected:
                continue
            gain = 0
            for block, current in zip(sample, current_costs):
                new = current
                if block == candidate:
                    new = min(new, 2)
                else:
                    other = block ^ candidate
                    if other in atom_index and other != candidate:
                        new = min(new, 3)
                gain += current - new
            score = gain - (length + 1)
            if best is None or (score, candidate) > (best[0], best[1]):
                best = (score, candidate)
        if best is None or best[0] <= 0:
            break
        chosen = best[1]
        atom_index[chosen] = len(atoms)
        atoms.append(chosen)
        selected.add(chosen)
        stats["steps"] += 1
        stats["estimated_gain"] += best[0]
    stats["dictionary_count"] = len(atoms)
    stats["rank"] = gf2_rank(atoms)
    return atoms, stats


def find_encoding(
    block: int,
    atoms: list[int],
    atom_index: dict[int, int],
    length: int,
    max_atoms: int,
) -> tuple[int, list[int], bytes | None]:
    best_tag = 0
    best_ids: list[int] = []
    best_cost = length + 1
    if block in atom_index:
        best_tag = 1
        best_ids = [atom_index[block]]
        best_cost = 2
    if max_atoms >= 2:
        found = None
        for atom in atoms:
            other = block ^ atom
            other_id = atom_index.get(other)
            if other_id is None or other == atom:
                continue
            pair = sorted((atom_index[atom], other_id))
            if found is None or pair < found:
                found = pair
        if found is not None and 3 < best_cost:
            best_tag, best_ids, best_cost = 2, found, 3
    if max_atoms >= 3:
        found = None
        for left in range(len(atoms)):
            for right in range(left):
                other = block ^ atoms[left] ^ atoms[right]
                other_id = atom_index.get(other)
                if other_id is None or other_id in (left, right):
                    continue
                triple = sorted((left, right, other_id))
                if found is None or triple < found:
                    found = triple
        if found is not None and 4 < best_cost:
            best_tag, best_ids, best_cost = 3, found, 4
    if best_tag == 0:
        return 0, [], block_bytes(block, length)
    return best_tag, best_ids, None


def build_archive(
    blocks: list[int],
    length: int,
    atoms: list[int],
    max_atoms: int,
) -> tuple[bytes, dict]:
    atom_index = {value: index for index, value in enumerate(atoms)}
    header = bytearray(MAGIC)
    header += uvarint(length)
    header += uvarint(len(blocks))
    header += uvarint(len(atoms))
    header.append(max_atoms)
    atom_data = b"".join(block_bytes(value, length) for value in atoms)
    references = bytearray()
    tag_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    literal_bytes = 0
    reference_bytes = 0
    nontrivial_multi_bytes = 0
    nontrivial_multi_blocks = 0
    representatives = []
    for block_index, block in enumerate(blocks):
        tag, ids, literal = find_encoding(block, atoms, atom_index, length, max_atoms)
        tag_counts[tag] += 1
        references.append(tag)
        if tag == 0:
            literal_bytes += len(literal)
            references += literal
        else:
            for identifier in ids:
                references += uvarint(identifier)
            reference_bytes += 1 + len(ids)
            if tag >= 2:
                atom_values = [atoms[identifier] for identifier in ids]
                zero_involved = any(value == 0 for value in atom_values)
                constant = is_constant(block, length)
                if not zero_involved and not constant:
                    nontrivial_multi_blocks += 1
                    nontrivial_multi_bytes += length
                    if len(representatives) < 5:
                        representatives.append(
                            {
                                "block_index": block_index,
                                "offset": block_index * length,
                                "tag": tag,
                                "atom_ids": ids,
                                "atom_values_hex": [block_bytes(value, length).hex() for value in atom_values],
                                "block_hex": block_bytes(block, length).hex(),
                                "block_is_constant": constant,
                                "zero_atom_involved": zero_involved,
                            }
                        )
    archive = bytes(header) + atom_data + bytes(references)
    source_bytes = len(blocks) * length
    meta = {
        "block_length": length,
        "block_count": len(blocks),
        "dictionary_count": len(atoms),
        "dictionary_rank": gf2_rank(atoms),
        "max_atoms": max_atoms,
        "header_bytes": len(header),
        "dictionary_bytes": len(atom_data),
        "reference_bytes": reference_bytes,
        "literal_bytes": literal_bytes,
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
        "tag_counts": {str(tag): count for tag, count in tag_counts.items()},
        "composition_coverage": (tag_counts[1] + tag_counts[2] + tag_counts[3]) / len(blocks),
        "multi_composition_coverage": (tag_counts[2] + tag_counts[3]) / len(blocks),
        "nontrivial_multi_blocks": nontrivial_multi_blocks,
        "nontrivial_multi_coverage": nontrivial_multi_bytes / source_bytes,
        "representatives": representatives,
        "source_bytes": source_bytes,
    }
    return archive, meta


def decode_archive(archive: bytes) -> tuple[bytes, dict]:
    if archive[: len(MAGIC)] != MAGIC:
        raise ValueError("bad dictionary magic")
    pos = len(MAGIC)
    length, pos = read_uvarint(archive, pos)
    block_count, pos = read_uvarint(archive, pos)
    dictionary_count, pos = read_uvarint(archive, pos)
    max_atoms = archive[pos]
    pos += 1
    atoms = []
    for _ in range(dictionary_count):
        atoms.append(int.from_bytes(archive[pos : pos + length], "big"))
        pos += length
    output = bytearray()
    for _ in range(block_count):
        tag = archive[pos]
        pos += 1
        if tag == 0:
            output += archive[pos : pos + length]
            pos += length
            continue
        ids = []
        for _ in range(tag):
            identifier, pos = read_uvarint(archive, pos)
            ids.append(identifier)
        value = 0
        for identifier in ids:
            value ^= atoms[identifier]
        output += block_bytes(value, length)
    if pos != len(archive):
        raise ValueError("trailing dictionary bytes")
    return bytes(output), {
        "block_length": length,
        "block_count": block_count,
        "dictionary_count": dictionary_count,
        "max_atoms": max_atoms,
    }


def build_basis(blocks: list[int], length: int) -> tuple[bytes, dict]:
    header = bytearray(MAGIC_E)
    header += uvarint(length)
    header += uvarint(len(blocks))
    data = b"".join(block_bytes(block, length) for block in blocks)
    archive = bytes(header) + data
    return archive, {
        "block_length": length,
        "block_count": len(blocks),
        "basis_rank": 8 * length,
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
    }


def decode_basis(archive: bytes) -> bytes:
    if archive[: len(MAGIC_E)] != MAGIC_E:
        raise ValueError("bad basis magic")
    pos = len(MAGIC_E)
    length, pos = read_uvarint(archive, pos)
    block_count, pos = read_uvarint(archive, pos)
    total = length * block_count
    if len(archive) - pos != total:
        raise ValueError("bad basis length")
    return archive[pos:]


def ordinary_atoms(blocks: list[int], length: int, capacity: int) -> list[int]:
    counts = Counter(blocks)
    return [value for value, _count in counts.most_common(capacity)]


def lzma2_compress(data: bytes) -> bytes:
    return lzma.compress(data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)


def lzma2_decompress(data: bytes) -> bytes:
    return lzma.decompress(data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)


def run_controls(data: bytes) -> dict:
    out = {}
    cases = (
        ("A_zstd9", Z9.compress, zstd.ZstdDecompressor().decompress, 0),
        ("B_zstd19", Z19.compress, zstd.ZstdDecompressor().decompress, 0),
        ("C_lzma2", lzma2_compress, lzma2_decompress, 1),
    )
    for name, compressor, decompressor, extra in cases:
        started = time.perf_counter()
        blob = compressor(data)
        encode_s = time.perf_counter() - started
        started = time.perf_counter()
        decoded = decompressor(blob)
        decode_s = time.perf_counter() - started
        if decoded != data:
            raise RuntimeError(f"{name} failed")
        out[name] = {
            "size_bytes": len(blob) + extra,
            "encode_s": round(encode_s, 5),
            "decode_s": round(decode_s, 5),
            "decoded_ok": True,
        }
    return out


# ---------------------------------------------------------------------------
# experiments


def dev_search_region(data: bytes, size: int) -> dict:
    rows = []
    for length in BLOCK_LENGTHS:
        blocks = split_blocks(data, length)
        for capacity in CAPACITIES:
            atoms, atom_stats = learn_atoms(blocks, length, capacity)
            archive, meta = build_archive(blocks, length, atoms, 2)
            rows.append(
                {
                    "block_length": length,
                    "capacity": capacity,
                    "atoms": len(atoms),
                    "rank": meta["dictionary_rank"],
                    "max_atoms": 2,
                    "F_bytes": len(archive),
                    "G_bytes": meta["compressed_bytes"],
                    "composition_coverage": meta["composition_coverage"],
                    "multi_coverage": meta["multi_composition_coverage"],
                    "nontrivial_multi_coverage": meta["nontrivial_multi_coverage"],
                    "tag_counts": meta["tag_counts"],
                    "estimated_gain": atom_stats["estimated_gain"],
                }
            )
    best_two = min(rows, key=lambda row: (row["G_bytes"], row["F_bytes"], row["block_length"], row["capacity"]))
    best_length = best_two["block_length"]
    best_capacity = best_two["capacity"]
    blocks = split_blocks(data, best_length)
    atoms, atom_stats = learn_atoms(blocks, best_length, best_capacity)
    archive_three, meta_three = build_archive(blocks, best_length, atoms, 3)
    row_three = {
        "block_length": best_length,
        "capacity": best_capacity,
        "atoms": len(atoms),
        "rank": meta_three["dictionary_rank"],
        "max_atoms": 3,
        "F_bytes": len(archive_three),
        "G_bytes": meta_three["compressed_bytes"],
        "composition_coverage": meta_three["composition_coverage"],
        "multi_coverage": meta_three["multi_composition_coverage"],
        "nontrivial_multi_coverage": meta_three["nontrivial_multi_coverage"],
        "tag_counts": meta_three["tag_counts"],
        "estimated_gain": atom_stats["estimated_gain"],
    }
    rows.append(row_three)
    selected = row_three if row_three["G_bytes"] < best_two["G_bytes"] else best_two
    selected_atoms = atoms if selected["max_atoms"] == 3 else learn_atoms(blocks, best_length, best_capacity)[0]
    selected_archive, selected_meta = build_archive(
        blocks, best_length, selected_atoms, selected["max_atoms"]
    )
    if decode_archive(selected_archive)[0] != data:
        raise RuntimeError("selected development dictionary failed reconstruction")
    return {
        "size": size,
        "rows": rows,
        "best_two": best_two,
        "selected": selected,
        "selected_atoms": selected_atoms,
        "selected_meta": selected_meta,
        "selected_exact": True,
    }


def run_dev_file(name: str) -> dict:
    relative, kind = next((rel, kind) for key, rel, kind in FILES if key == name)
    path = ROOT / relative
    data = path.read_bytes()
    available = [size for size in SIZES if len(data) >= 2 * size]
    skipped = [
        {"size": size, "reason": "two disjoint 4 KiB regions unavailable"}
        for size in SIZES
        if size not in available
    ]
    file_record = {
        "name": name,
        "kind": kind,
        "path": relative,
        "file_bytes": len(data),
        "file_sha256": sha256(data),
        "available_sizes": available,
        "skipped_sizes": skipped,
        "regions": {},
    }
    selected = {}
    for size in available:
        region = data[:size]
        result = dev_search_region(region, size)
        file_record["regions"][str(size)] = {
            "split": "dev",
            "offset": 0,
            "length": size,
            "sha256": sha256(region),
            "rows": result["rows"],
            "best_two": result["best_two"],
            "selected": result["selected"],
        }
        chosen = result["selected"]
        selected[str(size)] = {
            "block_length": chosen["block_length"],
            "capacity": chosen["capacity"],
            "max_atoms": chosen["max_atoms"],
            "dev_F_bytes": chosen["F_bytes"],
            "dev_G_bytes": chosen["G_bytes"],
        }
    return {"file": file_record, "selected": selected}


def run_dev(only: str | None = None) -> dict:
    started = time.perf_counter()
    files = []
    selected = {}
    for name, _relative, _kind in FILES:
        if only and name != only:
            continue
        result = run_dev_file(name)
        files.append(result["file"])
        selected[name] = result["selected"]
    return {
        "split": "dev",
        "elapsed_s": round(time.perf_counter() - started, 3),
        "files": files,
        "selected": selected,
    }


def measure_mode(target_data: bytes, train_data: bytes, config: dict) -> dict:
    length = config["block_length"]
    capacity = config["capacity"]
    max_atoms = config["max_atoms"]
    target_blocks = split_blocks(target_data, length)
    train_blocks = split_blocks(train_data, length)
    started = time.perf_counter()
    atoms, atom_stats = learn_atoms(train_blocks, length, capacity)
    f_archive, f_meta = build_archive(target_blocks, length, atoms, max_atoms)
    encode_s = time.perf_counter() - started
    started = time.perf_counter()
    f_decoded = decode_archive(f_archive)[0]
    decode_s = time.perf_counter() - started
    if f_decoded != target_data:
        raise RuntimeError("F dictionary failed reconstruction")
    started = time.perf_counter()
    f_compressed = Z9.compress(f_archive)
    compress_s = time.perf_counter() - started
    if decode_archive(zstd.ZstdDecompressor().decompress(f_compressed))[0] != target_data:
        raise RuntimeError("G dictionary failed reconstruction")

    d_atoms = ordinary_atoms(train_blocks, length, capacity)
    d_archive, d_meta = build_archive(target_blocks, length, d_atoms, 1)
    d_decoded = decode_archive(d_archive)[0]
    if d_decoded != target_data:
        raise RuntimeError("D dictionary failed reconstruction")
    d_zstd = Z9.compress(d_archive)

    df_archive, df_meta = build_archive(target_blocks, length, atoms, 1)
    if decode_archive(df_archive)[0] != target_data:
        raise RuntimeError("D_F ablation failed reconstruction")
    df_zstd = Z9.compress(df_archive)

    e_archive, e_meta = build_basis(target_blocks, length)
    if decode_basis(e_archive) != target_data:
        raise RuntimeError("E basis failed reconstruction")
    e_zstd = Z9.compress(e_archive)

    controls = run_controls(target_data)
    baseline_name, baseline_bytes = min(
        (
            ("A_zstd9", controls["A_zstd9"]["size_bytes"]),
            ("B_zstd19", controls["B_zstd19"]["size_bytes"]),
            ("C_lzma2", controls["C_lzma2"]["size_bytes"]),
            ("D", len(d_archive)),
            ("D_zstd", len(d_zstd)),
            ("E", len(e_archive)),
            ("E_zstd", len(e_zstd)),
            ("D_F", len(df_archive)),
            ("D_F_zstd", len(df_zstd)),
        ),
        key=lambda item: (item[1], item[0]),
    )
    return {
        "config": {"block_length": length, "capacity": capacity, "max_atoms": max_atoms},
        "atoms": len(atoms),
        "dictionary_rank": f_meta["dictionary_rank"],
        "dictionary_bytes": f_meta["dictionary_bytes"],
        "reference_bytes": f_meta["reference_bytes"],
        "literal_bytes": f_meta["literal_bytes"],
        "header_bytes": f_meta["header_bytes"],
        "F_bytes": len(f_archive),
        "G_bytes": len(f_compressed),
        "D_bytes": len(d_archive),
        "D_zstd_bytes": len(d_zstd),
        "D_F_bytes": len(df_archive),
        "D_F_zstd_bytes": len(df_zstd),
        "E_bytes": len(e_archive),
        "E_zstd_bytes": len(e_zstd),
        "controls": controls,
        "baseline_name": baseline_name,
        "baseline_bytes": baseline_bytes,
        "F_vs_D_F": round(len(f_archive) / len(df_archive), 6),
        "G_vs_D_F_zstd": round(len(f_compressed) / len(df_zstd), 6),
        "G_vs_baseline": round(len(f_compressed) / baseline_bytes, 6),
        "saving_vs_baseline": round(1.0 - len(f_compressed) / baseline_bytes, 6),
        "tag_counts": f_meta["tag_counts"],
        "composition_coverage": f_meta["composition_coverage"],
        "multi_composition_coverage": f_meta["multi_composition_coverage"],
        "nontrivial_multi_blocks": f_meta["nontrivial_multi_blocks"],
        "nontrivial_multi_coverage": f_meta["nontrivial_multi_coverage"],
        "representatives": f_meta["representatives"],
        "encode_s": round(encode_s, 5),
        "compress_s": round(compress_s, 5),
        "decode_s": round(decode_s, 5),
        "decoded_ok": True,
        "decoded_sha256": sha256(f_decoded),
    }


def run_val(dev_payload: dict, only: str | None = None) -> dict:
    started = time.perf_counter()
    selected = dev_payload["selected"]
    files = []
    for name, relative, kind in FILES:
        if only and name != only:
            continue
        path = ROOT / relative
        data = path.read_bytes()
        available = [size for size in SIZES if len(data) >= 2 * size]
        file_record = {
            "name": name,
            "kind": kind,
            "path": relative,
            "file_bytes": len(data),
            "file_sha256": sha256(data),
            "available_sizes": available,
            "regions": {},
        }
        for size in available:
            key = str(size)
            config = selected.get(name, {}).get(key)
            if config is None:
                continue
            dev_data = data[:size]
            val_data = data[-size:]
            file_record["regions"][key] = {
                "dev_transfer": measure_mode(val_data, dev_data, config),
                "local": measure_mode(val_data, val_data, config),
            }
        files.append(file_record)
    return {
        "split": "val",
        "elapsed_s": round(time.perf_counter() - started, 3),
        "files": files,
    }


def file_aggregates(val_payload: dict) -> list[dict]:
    rows = []
    for file_record in val_payload["files"]:
        for mode in ("dev_transfer", "local"):
            regions = [
                file_record["regions"][size][mode]
                for size in file_record["regions"]
                if mode in file_record["regions"][size]
            ]
            if not regions:
                continue
            total_g = sum(region["G_bytes"] for region in regions)
            total_base = sum(region["baseline_bytes"] for region in regions)
            coverage = sum(region["nontrivial_multi_coverage"] for region in regions) / len(regions)
            rows.append(
                {
                    "name": file_record["name"],
                    "mode": mode,
                    "G": total_g,
                    "baseline": total_base,
                    "saving_vs_baseline": round(1.0 - total_g / total_base, 6),
                    "primary_pass": (1.0 - total_g / total_base) >= 0.01,
                    "nontrivial_multi_coverage": coverage,
                    "secondary_candidate": coverage >= 0.10 and (1.0 - total_g / total_base) < 0.01,
                }
            )
    return rows


def compute_gate(val_payload: dict) -> dict:
    rows = file_aggregates(val_payload)
    primary = [row["name"] for row in rows if row["primary_pass"]]
    secondary = [row["name"] for row in rows if row["secondary_candidate"]]
    return {
        "files": rows,
        "primary": {
            "min_saving": 0.01,
            "min_files": 2,
            "qualifying": primary,
            "passed": len(primary) >= 2,
        },
        "secondary": {
            "min_nontrivial_multi_coverage": 0.10,
            "min_files": 2,
            "qualifying": secondary,
            "passed": len(secondary) >= 2,
        },
        "passed": len(primary) >= 2 or len(secondary) >= 2,
    }


def protocol_dict() -> dict:
    return {
        "phase": 19,
        "episode": 1,
        "status": "frozen before experiments",
        "codec": "bounded exact sparse XOR dictionary v1.0",
        "block_lengths": list(BLOCK_LENGTHS),
        "dictionary_capacities": list(CAPACITIES),
        "max_composition_atoms": 3,
        "learning_modes": ["dev_transfer", "local"],
        "gate": {
            "primary": {"min_saving": 0.01, "min_files": 2},
            "secondary": {
                "min_nontrivial_multi_coverage": 0.10,
                "min_files": 2,
                "require_encoding_bottleneck": True,
            },
        },
        "baseline": "min(A,B,C,D,D_zstd,E,E_zstd,D_F,D_F_zstd) per region",
        "controls": {
            "A": "zstd-9 raw",
            "B": "zstd-19 raw",
            "C": "raw LZMA2 +1",
            "D": "ordinary single-atom block dictionary",
            "E": "fixed 8L-bit GF(2) basis representation",
            "D_F": "F dictionary with composition disabled (matched ablation)",
            "F": "learned dictionary with 1/2/3-atom sparse XOR compositions",
            "G": "F + zstd-9",
        },
        "budget_s": 180,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf8")


def print_dev(payload: dict) -> None:
    print(f"{'file':8} {'L':>3} {'C':>3} {'max':>3} {'F':>7} {'G':>7} {'tags':>30}")
    for file_record in payload["files"]:
        for size_key, region in file_record["regions"].items():
            selected = region["selected"]
            print(
                f"{file_record['name']:8} {selected['block_length']:3d} {selected['capacity']:3d} "
                f"{selected['max_atoms']:3d} {selected['F_bytes']:7d} {selected['G_bytes']:7d} "
                f"{selected['tag_counts']}"
            )
    print(f"dev elapsed {payload['elapsed_s']} s")


def print_val(payload: dict) -> None:
    print(f"{'file':8} {'mode':12} {'L':>3} {'C':>3} {'max':>3} {'F':>7} {'G':>7} {'D_F':>7} {'base':>7} {'G/base':>7} {'multiN':>7}")
    for file_record in payload["validation"]["files"]:
        for size_key, region in file_record["regions"].items():
            for mode in ("dev_transfer", "local"):
                record = region[mode]
                print(
                    f"{file_record['name']:8} {mode:12} {record['config']['block_length']:3d} "
                    f"{record['config']['capacity']:3d} {record['config']['max_atoms']:3d} "
                    f"{record['F_bytes']:7d} {record['G_bytes']:7d} {record['D_F_bytes']:7d} "
                    f"{record['baseline_bytes']:7d} {record['G_vs_baseline']:7.3f} "
                    f"{record['nontrivial_multi_coverage']:7.3f}"
                )
    print(json.dumps(payload["gate"], indent=1))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "val", "both"), default="both")
    parser.add_argument("--file", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--probe", nargs=2, metavar=("FILE", "SIZE"))
    args = parser.parse_args()
    if args.probe:
        probe(args.probe[0], int(args.probe[1]))
        return
    selftest()
    if args.selftest:
        return

    started = time.perf_counter()
    if args.split == "dev":
        dev = run_dev(only=args.file)
        payload = {
            "phase": 19,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        out = Path(args.out) if args.out else RESULTS / "phase19-dev.json"
        write_json(out, payload)
        print_dev(payload)
    elif args.split == "val":
        dev = json.loads((RESULTS / "phase19-dev.json").read_text(encoding="utf8"))
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 19,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase19.json"
        write_json(out, payload)
        print_val(payload)
    else:
        dev = run_dev(only=args.file)
        dev_payload = {
            "phase": 19,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        write_json(RESULTS / "phase19-dev.json", dev_payload)
        print_dev(dev_payload)
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 19,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase19.json"
        write_json(out, payload)
        print_val(payload)


def probe(name: str, size: int) -> None:
    path = next(ROOT / relative for key, relative, _kind in FILES if key == name)
    data = path.read_bytes()[:size]
    if len(data) < size:
        print(name, size, "unavailable")
        return
    for length in BLOCK_LENGTHS:
        blocks = split_blocks(data, length)
        for capacity in CAPACITIES:
            atoms, stats = learn_atoms(blocks, length, capacity)
            archive, meta = build_archive(blocks, length, atoms, 3)
            print(
                f"{name} {size} L={length:2d} C={capacity:2d} atoms={len(atoms):2d} "
                f"rank={meta['dictionary_rank']:2d} F={len(archive):5d} G={meta['compressed_bytes']:5d} "
                f"tags={meta['tag_counts']} multi={meta['nontrivial_multi_coverage']:.3f}"
            )


def selftest() -> None:
    # Tiny exact XOR dictionary test.
    blocks = [0x01, 0x02, 0x03, 0x08, 0x0B]
    length = 8
    atoms = [0x01, 0x02, 0x08]
    expected = b"".join(block_bytes(block, length) for block in blocks)
    archive, meta = build_archive(blocks, length, atoms, 3)
    if decode_archive(archive)[0] != expected:
        raise AssertionError("dictionary archive")
    if meta["tag_counts"]["3"] != 1 or meta["tag_counts"]["2"] != 1:
        raise AssertionError("composition tags")
    basis, _basis_meta = build_basis(blocks, length)
    if decode_basis(basis) != expected:
        raise AssertionError("basis archive")
    print("selftest: XOR dictionary, compositions, basis decode: ok")


if __name__ == "__main__":
    main()
