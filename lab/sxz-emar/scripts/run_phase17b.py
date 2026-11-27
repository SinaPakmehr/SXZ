#!/usr/bin/env python3
"""Phase 17 Episode 2: exact reduced ordered BDD representation.

Three representations over the position-bit coordinates of a byte region:
  separate: eight Boolean bit-plane ROBDDs, separate node dictionaries
  shared:   eight Boolean bit-plane ROBDDs, one shared node dictionary
  mtbdd:    one multi-terminal BDD whose terminals are byte values

Both ROBDD reductions are applied: merge identical (var, low, high) nodes and
eliminate nodes whose low and high children are identical.  Graphs are built
bottom-up and serialized level-wise with compact variable-length references.
All decoding starts from the serialized bytes alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab/sxz-emar/results"
MAGIC_BDD = b"SXZ17B1"
MAGIC_D2 = b"SXZ17D2"
Z9 = zstd.ZstdCompressor(level=9)
Z19 = zstd.ZstdCompressor(level=19)
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]

REPRS = ("separate", "shared", "mtbdd")
ORDERS = ("msb", "lsb", "odd-even", "reversed-grouping")
SIZES = (4096, 16384, 65536)
FILES = (
    ("book1", "datasets/corpus/book1", "text"),
    ("bbc", "datasets/corpus/bbc.rss.xml", "structured text"),
    ("7zr", "datasets/corpus/7zr.exe", "executable"),
    ("irs1040", "datasets/corpus/irs1040.pdf", "pdf"),
    ("hopper", "datasets/corpus/hopper.bmp", "bmp"),
    ("ecg", "datasets/corpus/ecg-holdout.bin", "ecg"),
)

_ORDER_CACHE: dict[tuple[int, int], tuple[list[int], list[int]]] = {}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("negative uvarint")
    out = bytearray()
    while True:
        byte = value & 127
        value >>= 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def read_uvarint(buf: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated uvarint")
        byte = buf[pos]
        pos += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, pos
        shift += 7
        if shift > 63:
            raise ValueError("uvarint too long")


# ---------------------------------------------------------------------------
# variable orders and coordinate mapping


def order_bits(k: int, order_id: int) -> list[int]:
    if order_id == 0:  # MSB first
        return list(range(k - 1, -1, -1))
    if order_id == 1:  # LSB first
        return list(range(k))
    if order_id == 2:  # odd bit indices, then even bit indices
        return list(range(1, k, 2)) + list(range(0, k, 2))
    if order_id == 3:  # reversed grouping: even, then odd
        return list(range(0, k, 2)) + list(range(1, k, 2))
    raise ValueError("bad order id")


def order_positions(k: int, order_id: int) -> tuple[list[int], list[int]]:
    key = (k, order_id)
    if key in _ORDER_CACHE:
        return _ORDER_CACHE[key]
    bits = order_bits(k, order_id)
    total = 1 << k
    positions = [0] * total
    for q in range(total):
        index = 0
        for depth, bit in enumerate(bits):
            if q >> (k - 1 - depth) & 1:
                index |= 1 << bit
        positions[q] = index
    _ORDER_CACHE[key] = (bits, positions)
    return bits, positions


def ordered_bytes(data: bytes, positions: list[int]) -> bytes:
    return bytes(data[index] for index in positions)


# ---------------------------------------------------------------------------
# bottom-up reduced graph construction


def _new_stats() -> dict:
    return {
        "candidates": 0,
        "eliminated_equal_children": 0,
        "merged_identical_nodes": 0,
        "created_nodes": 0,
    }


def _reduce_levels(
    leaves: list[int],
    bits: list[int],
    terminal_count: int,
    unique: dict[tuple[int, int, int], int],
    nodes: list[tuple[int, int, int]],
    stats: dict,
    eliminate_redundant: bool,
) -> int:
    ids = leaves
    for level in range(len(bits) - 1, -1, -1):
        variable = bits[level]
        output = []
        for index in range(0, len(ids), 2):
            low = ids[index]
            high = ids[index + 1]
            stats["candidates"] += 1
            if eliminate_redundant and low == high:
                stats["eliminated_equal_children"] += 1
                output.append(low)
                continue
            key = (variable, low, high)
            existing = unique.get(key)
            if existing is not None:
                stats["merged_identical_nodes"] += 1
                output.append(existing)
                continue
            node_id = terminal_count + len(nodes)
            unique[key] = node_id
            nodes.append((variable, low, high))
            stats["created_nodes"] += 1
            output.append(node_id)
        ids = output
    return ids[0]


def _finalize_graph(
    nodes: list[tuple[int, int, int]],
    roots: list[int],
    bits: list[int],
    terminal_count: int,
) -> tuple[list[tuple[int, int, int]], list[int], list[int]]:
    depth_of_variable = {bit: depth for depth, bit in enumerate(bits)}
    levels: list[list[int]] = [[] for _ in bits]
    for node_id, (variable, _low, _high) in enumerate(nodes):
        depth = depth_of_variable[variable]
        levels[depth].append(node_id)
    order = [node_id for level in levels for node_id in level]
    remap = {old: terminal_count + index for index, old in enumerate(order)}

    def remap_ref(ref: int) -> int:
        if ref < terminal_count:
            return ref
        return remap[ref - terminal_count]

    new_nodes = []
    for old in order:
        variable, low, high = nodes[old]
        new_nodes.append((variable, remap_ref(low), remap_ref(high)))
    new_roots = [remap_ref(root) for root in roots]
    level_counts = [len(level) for level in levels]
    # All children must be later in level-wise order.
    for node_id, (_variable, low, high) in enumerate(new_nodes):
        absolute = terminal_count + node_id
        if low >= terminal_count and low <= absolute:
            raise AssertionError("low child not after parent")
        if high >= terminal_count and high <= absolute:
            raise AssertionError("high child not after parent")
    return new_nodes, level_counts, new_roots


def _reachable_nodes(nodes: list[tuple[int, int, int]], root: int, terminal_count: int) -> set[int]:
    seen: set[int] = set()
    stack = [root]
    while stack:
        ref = stack.pop()
        if ref < terminal_count:
            continue
        index = ref - terminal_count
        if index in seen:
            continue
        seen.add(index)
        _variable, low, high = nodes[index]
        if low >= terminal_count:
            stack.append(low)
        if high >= terminal_count:
            stack.append(high)
    return seen


def build_bdd(
    data: bytes,
    order_id: int,
    repr_id: int,
    eliminate_redundant: bool = True,
) -> dict:
    total = len(data)
    if total <= 0 or total & (total - 1):
        raise ValueError("region length must be a positive power of two")
    k = total.bit_length() - 1
    bits, positions = order_positions(k, order_id)
    ordered = data if order_id == 0 else ordered_bytes(data, positions)
    stats = _new_stats()
    graphs: list[list[tuple[int, int, int]]] = []
    roots: list[int] = []
    graph_roots: list[list[int]] = []

    if repr_id == 2:
        terminals = sorted(set(ordered))
        terminal_map = {value: index for index, value in enumerate(terminals)}
        leaves = [terminal_map[value] for value in ordered]
        unique: dict[tuple[int, int, int], int] = {}
        nodes: list[tuple[int, int, int]] = []
        root = _reduce_levels(
            leaves, bits, len(terminals), unique, nodes, stats, eliminate_redundant
        )
        graphs = [nodes]
        roots = [root]
        graph_roots = [[root]]
    else:
        terminals = [0, 1]
        terminal_count = 2
        if repr_id == 0:
            for plane in range(8):
                leaves = [(value >> plane) & 1 for value in ordered]
                unique = {}
                nodes = []
                root = _reduce_levels(
                    leaves, bits, terminal_count, unique, nodes, stats, eliminate_redundant
                )
                graphs.append(nodes)
                roots.append(root)
                graph_roots.append([root])
        elif repr_id == 1:
            unique = {}
            nodes = []
            for plane in range(8):
                leaves = [(value >> plane) & 1 for value in ordered]
                root = _reduce_levels(
                    leaves, bits, terminal_count, unique, nodes, stats, eliminate_redundant
                )
                roots.append(root)
            graphs = [nodes]
            graph_roots = [roots]
        else:
            raise ValueError("bad representation id")

    finalized_graphs = []
    finalized_roots = []
    level_counts_all = []
    for nodes, roots_for_graph in zip(graphs, graph_roots):
        new_nodes, level_counts, new_roots = _finalize_graph(
            nodes, roots_for_graph, bits, len(terminals)
        )
        finalized_graphs.append(new_nodes)
        leveled_roots = []
        for root in new_roots:
            leveled_roots.append(root)
        finalized_roots.extend(leveled_roots)
        level_counts_all.append(level_counts)

    shared_across_planes = 0
    if repr_id == 1 and finalized_graphs:
        node_usage: Counter[int] = Counter()
        for root in finalized_roots:
            for node in _reachable_nodes(finalized_graphs[0], root, len(terminals)):
                node_usage[node] += 1
        shared_across_planes = sum(1 for count in node_usage.values() if count >= 2)

    node_total = sum(len(graph) for graph in finalized_graphs)
    terminal_count = len(terminals)
    return {
        "data": data,
        "order_id": order_id,
        "order": ORDERS[order_id],
        "repr_id": repr_id,
        "repr": REPRS[repr_id],
        "k": k,
        "N": total,
        "bits": bits,
        "positions": positions,
        "terminals": terminals,
        "graphs": finalized_graphs,
        "graph_roots": graph_roots,
        "roots": finalized_roots,
        "level_counts": level_counts_all,
        "stats": stats,
        "node_total": node_total,
        "terminal_count": terminal_count,
        "shared_across_planes": shared_across_planes,
    }


# ---------------------------------------------------------------------------
# compact level-wise serialization


def _encode_records(graphs: list[list[tuple[int, int, int]]], mode: int, terminal_count: int) -> bytes:
    out = bytearray()
    for nodes in graphs:
        for index, (_variable, low, high) in enumerate(nodes):
            node_id = terminal_count + index
            for child in (low, high):
                if mode == 0:
                    out += uvarint(child)
                else:
                    if child < terminal_count:
                        out += uvarint(child)
                    else:
                        delta = child - node_id
                        if delta <= 0:
                            raise AssertionError("non-positive child delta")
                        out += uvarint(terminal_count + delta - 1)
    return bytes(out)


def serialize_bdd(build: dict) -> tuple[bytes, dict]:
    graphs = build["graphs"]
    terminals = build["terminals"]
    terminal_count = build["terminal_count"]
    roots = build["roots"]
    graph_count = len(graphs)
    records0 = _encode_records(graphs, 0, terminal_count)
    records1 = _encode_records(graphs, 1, terminal_count)
    if len(records0) <= len(records1):
        mode = 0
        records = records0
    else:
        mode = 1
        records = records1

    header = bytearray(MAGIC_BDD)
    header.append(build["repr_id"])
    header.append(build["order_id"])
    header += uvarint(build["N"])
    header.append(build["k"])
    header += uvarint(terminal_count)
    header += bytes(terminals)
    header.append(graph_count)
    for graph_index, nodes in enumerate(graphs):
        roots_for_graph = (
            roots[graph_index : graph_index + 1]
            if graph_count == 8
            else roots
        )
        header += uvarint(len(roots_for_graph))
        for root in roots_for_graph:
            header += uvarint(root)
        header += uvarint(len(nodes))
        for count in build["level_counts"][graph_index]:
            header += uvarint(count)
    header.append(mode)
    archive = bytes(header) + records
    meta = {
        "repr": build["repr"],
        "repr_id": build["repr_id"],
        "order": build["order"],
        "order_id": build["order_id"],
        "N": build["N"],
        "k": build["k"],
        "terminal_count": terminal_count,
        "nonterminal_count": build["node_total"],
        "node_total": build["node_total"],
        "level_counts": build["level_counts"],
        "stats": build["stats"],
        "shared_across_planes": build["shared_across_planes"],
        "roots": roots,
        "mode": mode,
        "header_bytes": len(header),
        "record_bytes": len(records),
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
    }
    return archive, meta


def _decode_ref(code: int, node_id: int, terminal_count: int, mode: int) -> int:
    if mode == 0:
        return code
    if code < terminal_count:
        return code
    return node_id + 1 + (code - terminal_count)


def decode_bdd(archive: bytes) -> tuple[bytes, dict]:
    if archive[: len(MAGIC_BDD)] != MAGIC_BDD:
        raise ValueError("bad BDD magic")
    pos = len(MAGIC_BDD)
    repr_id = archive[pos]
    pos += 1
    order_id = archive[pos]
    pos += 1
    total, pos = read_uvarint(archive, pos)
    k = archive[pos]
    pos += 1
    terminal_count, pos = read_uvarint(archive, pos)
    terminals = list(archive[pos : pos + terminal_count])
    pos += terminal_count
    graph_count = archive[pos]
    pos += 1
    graph_roots = []
    graph_counts = []
    level_counts = []
    for _ in range(graph_count):
        root_count, pos = read_uvarint(archive, pos)
        roots = []
        for _ in range(root_count):
            root, pos = read_uvarint(archive, pos)
            roots.append(root)
        node_count, pos = read_uvarint(archive, pos)
        counts = []
        for _ in range(k):
            count, pos = read_uvarint(archive, pos)
            counts.append(count)
        if sum(counts) != node_count:
            raise ValueError("level count mismatch")
        graph_roots.append(roots)
        graph_counts.append(node_count)
        level_counts.append(counts)
    mode = archive[pos]
    pos += 1
    bits, positions = order_positions(k, order_id)
    graphs = []
    for graph_index in range(graph_count):
        nodes = []
        for depth, count in enumerate(level_counts[graph_index]):
            variable = bits[depth]
            for _ in range(count):
                node_id = terminal_count + len(nodes)
                low_code, pos = read_uvarint(archive, pos)
                high_code, pos = read_uvarint(archive, pos)
                low = _decode_ref(low_code, node_id, terminal_count, mode)
                high = _decode_ref(high_code, node_id, terminal_count, mode)
                nodes.append((variable, low, high))
        graphs.append(nodes)
    if pos != len(archive):
        raise ValueError("trailing archive bytes")

    depth_of_variable = {bit: depth for depth, bit in enumerate(bits)}
    ordered = bytearray(total)
    if repr_id == 2:
        nodes = graphs[0]
        root = graph_roots[0][0]
        for q in range(total):
            ref = root
            while ref >= terminal_count:
                variable, low, high = nodes[ref - terminal_count]
                depth = depth_of_variable[variable]
                bit = (q >> (k - 1 - depth)) & 1
                ref = high if bit else low
            ordered[q] = terminals[ref]
    else:
        if repr_id == 0:
            plane_graphs = graphs
            plane_roots = [graph_roots[index][0] for index in range(8)]
        else:
            plane_graphs = [graphs[0]] * 8
            plane_roots = graph_roots[0]
        for q in range(total):
            value = 0
            for plane in range(8):
                nodes = plane_graphs[plane]
                ref = plane_roots[plane]
                while ref >= terminal_count:
                    variable, low, high = nodes[ref - terminal_count]
                    depth = depth_of_variable[variable]
                    bit = (q >> (k - 1 - depth)) & 1
                    ref = high if bit else low
                value |= (ref & 1) << plane
            ordered[q] = value

    out = bytearray(total)
    for q, original in enumerate(positions):
        out[original] = ordered[q]
    meta = {
        "repr_id": repr_id,
        "order_id": order_id,
        "N": total,
        "k": k,
        "terminal_count": terminal_count,
        "graph_count": graph_count,
        "node_total": sum(graph_counts),
        "mode": mode,
    }
    return bytes(out), meta


# ---------------------------------------------------------------------------
# controls


def delta_encode(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    out[0] = data[0]
    for index in range(1, len(data)):
        out[index] = (data[index] - data[index - 1]) & 255
    return bytes(out)


def delta_decode(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    out[0] = data[0]
    for index in range(1, len(data)):
        out[index] = (data[index] + out[index - 1]) & 255
    return bytes(out)


def shuffle_encode(data: bytes, width: int = 3) -> tuple[bytes, bytes]:
    body_len = len(data) - (len(data) % width)
    body = b"".join(data[lane:body_len:width] for lane in range(width))
    return body, data[body_len:]


def shuffle_decode(body: bytes, trailing: bytes, width: int = 3) -> bytes:
    lane_len = len(body) // width
    out = bytearray(len(body))
    for index in range(len(body)):
        out[index] = body[(index % width) * lane_len + index // width]
    return bytes(out) + trailing


def global_apply(data: bytes, param: int, op: str) -> bytes:
    if op == "add":
        return bytes((byte + param) & 255 for byte in data)
    if op == "xor":
        return bytes(byte ^ param for byte in data)
    raise ValueError("bad global op")


def choose_global(data: bytes, op: str) -> int:
    sample = data[: min(len(data), 8192)]
    compressor = zstd.ZstdCompressor(level=1)
    best_param = 0
    best_size = None
    for param in range(256):
        size = len(compressor.compress(global_apply(sample, param, op)))
        if best_size is None or size < best_size:
            best_size = size
            best_param = param
    return best_param


def bitplane_transform(data: bytes, order_id: int) -> tuple[bytes, dict]:
    total = len(data)
    k = total.bit_length() - 1
    _bits, positions = order_positions(k, order_id)
    ordered = data if order_id == 0 else ordered_bytes(data, positions)
    plane_size = total // 8
    planes = []
    for plane in range(8):
        packed = bytearray(plane_size)
        for q in range(total):
            if (ordered[q] >> plane) & 1:
                packed[q >> 3] |= 1 << (7 - (q & 7))
        planes.append(bytes(packed))
    transformed = b"".join(planes)
    header = bytearray(MAGIC_D2)
    header.append(order_id)
    header += uvarint(total)
    payload = Z9.compress(transformed)
    return bytes(header) + payload, {
        "order_id": order_id,
        "header_bytes": len(header),
        "payload_bytes": len(payload),
        "transformed_sha256": sha256(transformed),
    }


def decode_bitplane(archive: bytes) -> bytes:
    if archive[: len(MAGIC_D2)] != MAGIC_D2:
        raise ValueError("bad D2 magic")
    order_id = archive[len(MAGIC_D2)]
    pos = len(MAGIC_D2) + 1
    total, pos = read_uvarint(archive, pos)
    k = total.bit_length() - 1
    _bits, positions = order_positions(k, order_id)
    transformed = zstd.ZstdDecompressor().decompress(archive[pos:])
    plane_size = total // 8
    if len(transformed) != 8 * plane_size:
        raise ValueError("bad bit-plane length")
    ordered = bytearray(total)
    for plane in range(8):
        plane_data = transformed[plane * plane_size : (plane + 1) * plane_size]
        for q in range(total):
            if plane_data[q >> 3] >> (7 - (q & 7)) & 1:
                ordered[q] |= 1 << plane
    out = bytearray(total)
    for q, original in enumerate(positions):
        out[original] = ordered[q]
    return bytes(out)


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
# development search and validation


def file_available_sizes(file_bytes: int) -> tuple[list[int], list[dict]]:
    available = []
    skipped = []
    for size in SIZES:
        if file_bytes >= 2 * size:
            available.append(size)
        else:
            skipped.append(
                {
                    "size": size,
                    "reason": "two disjoint regions unavailable",
                    "file_bytes": file_bytes,
                    "needed_bytes": 2 * size,
                }
            )
    return available, skipped


def reachable_for_roots(build: dict) -> list[int]:
    terminals = build["terminal_count"]
    graphs = build["graphs"]
    roots = build["roots"]
    if build["repr_id"] == 0:
        return [
            len(_reachable_nodes(graphs[index], root, terminals))
            for index, root in enumerate(roots)
        ]
    return [len(_reachable_nodes(graphs[0], root, terminals)) for root in roots]


def dev_search_region(data: bytes, size: int) -> dict:
    rows = []
    for repr_id, repr_name in enumerate(REPRS):
        for order_id, order_name in enumerate(ORDERS):
            started = time.perf_counter()
            build = build_bdd(data, order_id, repr_id)
            archive, meta = serialize_bdd(build)
            encode_s = time.perf_counter() - started
            rows.append(
                {
                    "repr": repr_name,
                    "repr_id": repr_id,
                    "order": order_name,
                    "order_id": order_id,
                    "node_total": meta["nonterminal_count"],
                    "terminal_count": meta["terminal_count"],
                    "exact_bytes": meta["exact_bytes"],
                    "compressed_bytes": meta["compressed_bytes"],
                    "mode": meta["mode"],
                    "stats": meta["stats"],
                    "shared_across_planes": meta["shared_across_planes"],
                    "encode_s": round(encode_s, 4),
                }
            )
    best_g = min(
        rows,
        key=lambda row: (
            row["compressed_bytes"],
            row["exact_bytes"],
            row["repr_id"],
            row["order_id"],
        ),
    )
    best_f = min(
        rows,
        key=lambda row: (
            row["exact_bytes"],
            row["compressed_bytes"],
            row["repr_id"],
            row["order_id"],
        ),
    )
    build = build_bdd(data, best_g["order_id"], best_g["repr_id"])
    archive, _meta = serialize_bdd(build)
    decoded, _decoded_meta = decode_bdd(archive)
    if decoded != data:
        raise RuntimeError("selected development BDD failed exact reconstruction")
    return {
        "size": size,
        "rows": rows,
        "best_g": best_g,
        "best_f": best_f,
        "selected_exact": True,
    }


def run_dev_file(name: str) -> dict:
    relative, kind = next((rel, kind) for key, rel, kind in FILES if key == name)
    path = ROOT / relative
    data = path.read_bytes()
    available, skipped = file_available_sizes(len(data))
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
            **result,
        }
        best = result["best_g"]
        selected[str(size)] = {
            "repr": best["repr"],
            "repr_id": best["repr_id"],
            "order": best["order"],
            "order_id": best["order_id"],
            "dev_node_total": best["node_total"],
            "dev_terminal_count": best["terminal_count"],
            "dev_exact_bytes": best["exact_bytes"],
            "dev_compressed_bytes": best["compressed_bytes"],
            "dev_stats": best["stats"],
        }
    return {"file": file_record, "selected": selected}


def run_dev(only: str | None = None) -> dict:
    started = time.perf_counter()
    tasks = [name for name, _relative, _kind in FILES if not only or name == only]
    workers = min(len(tasks), max(1, (os.cpu_count() or 2) - 1), 6)
    if len(tasks) <= 1 or workers == 1:
        results = [run_dev_file(name) for name in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(run_dev_file, tasks))
    files = [result["file"] for result in results]
    selected = {result["file"]["name"]: result["selected"] for result in results}
    return {
        "split": "dev",
        "elapsed_s": round(time.perf_counter() - started, 3),
        "files": files,
        "selected": selected,
    }


def validate_region(data: bytes, size: int, offset: int, config: dict) -> dict:
    repr_id = config["repr_id"]
    order_id = config["order_id"]
    started = time.perf_counter()
    build = build_bdd(data, order_id, repr_id)
    archive, meta = serialize_bdd(build)
    encode_s = time.perf_counter() - started
    started = time.perf_counter()
    compressed = Z9.compress(archive)
    compress_s = time.perf_counter() - started
    started = time.perf_counter()
    decoded, _decoded_meta = decode_bdd(archive)
    decode_s = time.perf_counter() - started
    if decoded != data:
        raise RuntimeError("selected BDD failed exact reconstruction")
    started = time.perf_counter()
    decoded_g, _decoded_g_meta = decode_bdd(zstd.ZstdDecompressor().decompress(compressed))
    decode_g_s = time.perf_counter() - started
    if decoded_g != data:
        raise RuntimeError("compressed BDD failed exact reconstruction")

    d_archive, d_meta = bitplane_transform(data, order_id)
    started = time.perf_counter()
    d_decoded = decode_bitplane(d_archive)
    d_decode_s = time.perf_counter() - started
    if d_decoded != data:
        raise RuntimeError("bit-plane control failed exact reconstruction")

    started = time.perf_counter()
    e_build = build_bdd(data, order_id, repr_id, eliminate_redundant=False)
    e_archive, e_meta = serialize_bdd(e_build)
    e_encode_s = time.perf_counter() - started
    started = time.perf_counter()
    e_decoded, _e_decoded_meta = decode_bdd(e_archive)
    e_decode_s = time.perf_counter() - started
    if e_decoded != data:
        raise RuntimeError("no-redundant control failed exact reconstruction")
    e_zstd_bytes = len(Z9.compress(e_archive))

    controls = run_controls(data)
    baseline_name, baseline_bytes = min(
        (
            ("A_zstd9", controls["A_zstd9"]["size_bytes"]),
            ("B_zstd19", controls["B_zstd19"]["size_bytes"]),
            ("C_lzma2", controls["C_lzma2"]["size_bytes"]),
            ("D", len(d_archive)),
            ("E", len(e_archive)),
            ("E_zstd9", e_zstd_bytes),
        ),
        key=lambda item: (item[1], item[0]),
    )
    root_reachable = reachable_for_roots(build)
    representative_root = max(range(len(root_reachable)), key=lambda index: root_reachable[index])
    return {
        "split": "val",
        "offset": offset,
        "length": size,
        "sha256": sha256(data),
        "repr": meta["repr"],
        "repr_id": repr_id,
        "order": meta["order"],
        "order_id": order_id,
        "N": size,
        "k": meta["k"],
        "terminal_count": meta["terminal_count"],
        "nonterminal_count": meta["nonterminal_count"],
        "node_total": meta["node_total"],
        "level_counts": meta["level_counts"],
        "mode": meta["mode"],
        "stats": meta["stats"],
        "shared_across_planes": meta["shared_across_planes"],
        "root_reachable": root_reachable,
        "representative_root": {
            "index": representative_root,
            "reachable_nodes": root_reachable[representative_root],
        },
        "F_bytes": meta["exact_bytes"],
        "G_bytes": len(compressed),
        "D_bytes": len(d_archive),
        "E_bytes": len(e_archive),
        "E_zstd9_bytes": e_zstd_bytes,
        "E_stats": e_meta["stats"],
        "controls": controls,
        "baseline_name": baseline_name,
        "baseline_bytes": baseline_bytes,
        "G_vs_baseline": round(len(compressed) / baseline_bytes, 6),
        "saving_vs_baseline": round(1.0 - len(compressed) / baseline_bytes, 6),
        "F_vs_N": round(meta["exact_bytes"] / size, 6),
        "G_vs_N": round(len(compressed) / size, 6),
        "node_vs_N": round(meta["nonterminal_count"] / size, 6),
        "encode_s": round(encode_s, 5),
        "compress_s": round(compress_s, 5),
        "decode_s": round(decode_s, 5),
        "decode_g_s": round(decode_g_s, 5),
        "d_decode_s": round(d_decode_s, 5),
        "e_encode_s": round(e_encode_s, 5),
        "e_decode_s": round(e_decode_s, 5),
        "decoded_ok": True,
        "decoded_g_ok": True,
        "decoded_e_ok": True,
        "decoded_sha256": sha256(decoded),
        "decoded_g_sha256": sha256(decoded_g),
        "decoded_e_sha256": sha256(e_decoded),
    }


def run_val_file(name: str, selected_for_file: dict) -> dict:
    relative, kind = next((rel, kind) for key, rel, kind in FILES if key == name)
    path = ROOT / relative
    data = path.read_bytes()
    available, skipped = file_available_sizes(len(data))
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
    for size in available:
        key = str(size)
        if key not in selected_for_file:
            raise ValueError(f"missing frozen selection for {name} {size}")
        region = data[-size:]
        file_record["regions"][key] = validate_region(
            region, size, len(data) - size, selected_for_file[key]
        )
    return file_record


def run_val(dev_payload: dict, only: str | None = None) -> dict:
    started = time.perf_counter()
    selected = dev_payload["selected"]
    tasks = [
        (name, selected.get(name, {}))
        for name, _relative, _kind in FILES
        if not only or name == only
    ]
    workers = min(len(tasks), max(1, (os.cpu_count() or 2) - 1), 6)
    if len(tasks) <= 1 or workers == 1:
        files = [run_val_file(name, selected_for_file) for name, selected_for_file in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            files = list(
                pool.map(
                    run_val_file,
                    [task[0] for task in tasks],
                    [task[1] for task in tasks],
                )
            )
    return {
        "split": "val",
        "elapsed_s": round(time.perf_counter() - started, 3),
        "files": files,
    }


def file_aggregates(val_payload: dict) -> list[dict]:
    rows = []
    for file_record in val_payload["files"]:
        regions = list(file_record["regions"].values())
        if not regions:
            continue
        sum_g = sum(region["G_bytes"] for region in regions)
        sum_f = sum(region["F_bytes"] for region in regions)
        sum_base = sum(region["baseline_bytes"] for region in regions)
        sum_n = sum(region["length"] for region in regions)
        sum_nodes = sum(region["nonterminal_count"] for region in regions)
        rows.append(
            {
                "name": file_record["name"],
                "sizes": [region["length"] for region in regions],
                "N": sum_n,
                "F": sum_f,
                "G": sum_g,
                "baseline": sum_base,
                "saving_vs_baseline": round(1.0 - sum_g / sum_base, 6),
                "primary_pass": (1.0 - sum_g / sum_base) >= 0.01,
                "node_ratio": round(sum_nodes / sum_n, 6),
                "F_ratio": round(sum_f / sum_n, 6),
            }
        )
    return rows


def compute_gate(val_payload: dict) -> dict:
    files = file_aggregates(val_payload)
    qualifying = [row["name"] for row in files if row["primary_pass"]]
    return {
        "files": files,
        "primary": {
            "min_saving": 0.01,
            "min_files": 2,
            "qualifying_files": qualifying,
            "passed": len(qualifying) >= 2,
        },
        "passed": len(qualifying) >= 2,
    }


# ---------------------------------------------------------------------------
# self-test


def selftest() -> None:
    # tiny explicit Boolean functions on three variables
    data = bytes((0, 1, 2, 3, 4, 5, 6, 7))
    for repr_id in range(3):
        for order_id in range(4):
            build = build_bdd(data, order_id, repr_id)
            archive, meta = serialize_bdd(build)
            decoded, dmeta = decode_bdd(archive)
            if decoded != data:
                raise AssertionError((repr_id, order_id))
            if meta["exact_bytes"] != len(archive):
                raise AssertionError("size mismatch")
    # no-redundant variant must also reconstruct
    for repr_id in range(3):
        build = build_bdd(data, 0, repr_id, eliminate_redundant=False)
        archive, _meta = serialize_bdd(build)
        decoded, _dmeta = decode_bdd(archive)
        if decoded != data:
            raise AssertionError("no-redundant reconstruction")
    # bit-plane control
    archive, _meta = bitplane_transform(data, 1)
    if decode_bitplane(archive) != data:
        raise AssertionError("bit-plane control")
    print("selftest: BDD representations, reductions, orders, bit-plane control: ok")


# ---------------------------------------------------------------------------
# probe


def probe(name: str, size: int) -> None:
    path = next(ROOT / relative for key, relative, _kind in FILES if key == name)
    data = path.read_bytes()[:size]
    if len(data) < size:
        print(name, size, "unavailable")
        return
    for repr_id, repr_name in enumerate(REPRS):
        for order_id, order_name in enumerate(ORDERS):
            started = time.perf_counter()
            build = build_bdd(data, order_id, repr_id)
            archive, meta = serialize_bdd(build)
            elapsed = time.perf_counter() - started
            print(
                f"{name} {size} {repr_name:8} {order_name:18} "
                f"nodes={meta['nonterminal_count']:7d} exact={meta['exact_bytes']:8d} "
                f"zstd={meta['compressed_bytes']:8d} mode={meta['mode']} "
                f"stats={meta['stats']} time={elapsed:.3f}"
            )


def protocol_dict() -> dict:
    return {
        "phase": 17,
        "episode": 2,
        "codec": "exact reduced ordered BDD representation v1.0",
        "representations": list(REPRS),
        "orders": list(ORDERS),
        "sizes": list(SIZES),
        "region_rule": (
            "first and last disjoint equal regions; skip when file_bytes < 2*size; "
            "no padding"
        ),
        "selection": "per file/size smallest decision-diagram+zstd9 (G) on dev, frozen before validation",
        "reductions": [
            "merge identical (variable, low, high) nodes",
            "eliminate nodes whose low and high children are identical",
        ],
        "serialization": (
            "level-wise records; mode 0 absolute varints, mode 1 delta varints; "
            "roots, terminals, order, levels and counts charged"
        ),
        "controls": {
            "A": "zstd-9 raw",
            "B": "zstd-19 raw",
            "C": "raw LZMA2 preset 6 +1 byte",
            "D": "matched bit-plane + coordinate transform + zstd-9",
            "E": "selected representation without redundant-variable elimination (exact)",
            "E_zstd9": "same no-redundant graph + zstd-9",
            "F": "exact selected decision diagram",
            "G": "selected decision diagram + zstd-9",
        },
        "gate": {
            "min_saving": 0.01,
            "min_files": 2,
            "baseline": "min(A,B,C,D,E,E_zstd9) per region, summed per file",
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf8")


def print_dev(payload: dict) -> None:
    print(f"{'file':8} {'size':>6} {'repr':9} {'order':18} {'nodes':>7} {'term':>5} {'F':>8} {'G':>8} {'share':>6}")
    for file_record in payload["files"]:
        for size_key, region in file_record["regions"].items():
            best = region["best_g"]
            print(
                f"{file_record['name']:8} {int(size_key):6d} {best['repr']:9} {best['order']:18} "
                f"{best['node_total']:7d} {best['terminal_count']:5d} {best['exact_bytes']:8d} "
                f"{best['compressed_bytes']:8d} {best['shared_across_planes']:6d}"
            )
    print(f"dev elapsed {payload['elapsed_s']} s")


def print_val(payload: dict) -> None:
    print(
        f"{'file':8} {'size':>6} {'repr':9} {'order':18} {'nodes':>7} {'F':>8} {'G':>8} "
        f"{'D':>8} {'E':>8} {'Ez':>8} {'A':>8} {'base':>8} {'G/base':>7}"
    )
    for file_record in payload["validation"]["files"]:
        for size_key, region in file_record["regions"].items():
            print(
                f"{file_record['name']:8} {int(size_key):6d} {region['repr']:9} {region['order']:18} "
                f"{region['nonterminal_count']:7d} {region['F_bytes']:8d} {region['G_bytes']:8d} "
                f"{region['D_bytes']:8d} {region['E_bytes']:8d} {region['E_zstd9_bytes']:8d} "
                f"{region['controls']['A_zstd9']['size_bytes']:8d} {region['baseline_bytes']:8d} "
                f"{region['G_vs_baseline']:7.3f}"
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
            "phase": 17,
            "episode": 2,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        out = Path(args.out) if args.out else RESULTS / "phase17b-dev.json"
        write_json(out, payload)
        print_dev(payload)
    elif args.split == "val":
        dev_path = RESULTS / "phase17b-dev.json"
        dev = json.loads(dev_path.read_text(encoding="utf8"))
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 17,
            "episode": 2,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase17b.json"
        write_json(out, payload)
        print_val(payload)
    else:
        dev = run_dev(only=args.file)
        dev_payload = {
            "phase": 17,
            "episode": 2,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        write_json(RESULTS / "phase17b-dev.json", dev_payload)
        print_dev(dev_payload)
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 17,
            "episode": 2,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase17b.json"
        write_json(out, payload)
        print_val(payload)


if __name__ == "__main__":
    main()
