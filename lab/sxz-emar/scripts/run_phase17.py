#!/usr/bin/env python3
"""Phase 17 Episode 1: exact matrix/Tensor-Train representation over GF(256).

The field is GF(2^8) with irreducible polynomial 0x11B.  Addition is XOR;
multiplication and inversion use precomputed log/exp and multiplication
tables.  No floating point or approximation is used.

The file is a minimal exact implementation of:
  * deterministic finite-field RREF rank factorization M = U V
  * exact Tensor-Train decomposition by sequential rank factorization
  * balanced 2D/3D/4D, 4-ary and binary tensorizations
  * reversible linear, reversed-axis and odd/even bit orderings
  * serialized representation with explicit header and coefficient costs
"""

from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import math
import os
import sys
import time
import tracemalloc
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab/sxz-emar/results"
POLY = 0x11B
MAGIC_E = b"SXZ17E1"
MAGIC_D = b"SXZ17D1"
MAGIC_G = b"SXZ17G1"
Z9 = zstd.ZstdCompressor(level=9)
Z19 = zstd.ZstdCompressor(level=19)
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]

SHAPES = {
    4096: (
        ("2d", (64, 64)),
        ("3d", (16, 16, 16)),
        ("4d", (8, 8, 8, 8)),
        ("4power", (4, 4, 4, 4, 4, 4)),
        ("binary", (2,) * 12),
    ),
    16384: (
        ("2d", (128, 128)),
        ("3d", (16, 32, 32)),
        ("4d", (8, 16, 16, 8)),
        ("4power", (4,) * 7),
        ("binary", (2,) * 14),
    ),
    65536: (
        ("2d", (256, 256)),
        ("3d", (32, 32, 64)),
        ("4d", (16, 16, 16, 16)),
        ("4power", (4,) * 8),
        ("binary", (2,) * 16),
    ),
}
ORDERS = ("linear", "axis-reverse", "bit-odd-even")
FILES = (
    ("book1", "datasets/corpus/book1", "text"),
    ("bbc", "datasets/corpus/bbc.rss.xml", "structured text"),
    ("7zr", "datasets/corpus/7zr.exe", "executable"),
    ("irs1040", "datasets/corpus/irs1040.pdf", "pdf"),
    ("hopper", "datasets/corpus/hopper.bmp", "bmp"),
    ("ecg", "datasets/corpus/ecg-holdout.bin", "ecg"),
)
SIZES = (4096, 16384, 65536)


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
# GF(2^8), polynomial 0x11B


def _gf_mul_slow(a: int, b: int) -> int:
    product = 0
    for _ in range(8):
        if b & 1:
            product ^= a
        b >>= 1
        carry = a & 0x80
        a = (a << 1) & 0xFF
        if carry:
            a ^= 0x1B
    return product


def _build_gf() -> tuple[list[int], list[int], list[int], list[bytes]]:
    generator = None
    for candidate in range(2, 256):
        value = 1
        seen = set()
        for _ in range(255):
            seen.add(value)
            value = _gf_mul_slow(value, candidate)
        if len(seen) == 255:
            generator = candidate
            break
    if generator is None:
        raise RuntimeError("no GF(256) generator found")
    exp = [0] * 512
    log = [0] * 256
    value = 1
    for index in range(255):
        exp[index] = value
        log[value] = index
        value = _gf_mul_slow(value, generator)
    for index in range(255, 512):
        exp[index] = exp[index - 255]
    inverse = [0] * 256
    for value in range(1, 256):
        inverse[value] = exp[255 - log[value]]
    mul = [
        bytes(exp[(log[a] + log[b]) % 255] if a and b else 0 for b in range(256))
        for a in range(256)
    ]
    return exp, log, inverse, mul


EXP, LOG, INV, MUL = _build_gf()


def matmul_gf(left: list[bytes], right: list[bytes], m: int, k: int, n: int) -> list[bytes]:
    out = []
    for row_index in range(m):
        row = bytearray(n)
        left_row = left[row_index]
        for inner in range(k):
            factor = left_row[inner]
            if factor:
                table = MUL[factor]
                right_row = right[inner]
                for col in range(n):
                    row[col] ^= table[right_row[col]]
        out.append(bytes(row))
    return out


def factor_matrix(rows: list[bytes], m: int, n: int) -> tuple[int, list[int], list[bytes], list[bytes]]:
    """Exact RREF factorization M = U V over GF(256).

    U is formed by the pivot columns of the original matrix.  V is the
    non-zero RREF part.  Row operations are vectorized with bytes.translate
    and integer XOR; no floating point is involved.
    """
    if m == 0 or n == 0:
        return 0, [], [], []
    work = list(rows)
    for row in work:
        if len(row) != n:
            raise ValueError("matrix row length mismatch")
    pivots: list[int] = []
    rank = 0
    for col in range(n):
        pivot = -1
        for row_index in range(rank, m):
            if work[row_index][col]:
                pivot = row_index
                break
        if pivot < 0:
            continue
        if pivot != rank:
            work[rank], work[pivot] = work[pivot], work[rank]
        pivot_value = work[rank][col]
        if pivot_value != 1:
            work[rank] = work[rank].translate(MUL[INV[pivot_value]])
        pivot_row = work[rank]
        for row_index in range(m):
            if row_index == rank:
                continue
            factor = work[row_index][col]
            if factor:
                product = pivot_row.translate(MUL[factor])
                work[row_index] = (
                    int.from_bytes(work[row_index], "big") ^ int.from_bytes(product, "big")
                ).to_bytes(n, "big")
        pivots.append(col)
        rank += 1
        if rank == m:
            break
    u_rows = [bytes(row[col] for col in pivots) for row in rows]
    v_rows = [work[index] for index in range(rank)]
    return rank, pivots, u_rows, v_rows


# ---------------------------------------------------------------------------
# Tensor-Train decomposition and reconstruction


def shape_product(shape: tuple[int, ...]) -> int:
    value = 1
    for dim in shape:
        value *= dim
    return value


def tt_decompose(data: bytes, shape: tuple[int, ...]) -> dict:
    total = shape_product(shape)
    if len(data) != total:
        raise ValueError("tensor size mismatch")
    ranks = [1]
    max_ranks: list[int] = []
    full_rank_cuts: list[bool] = []
    cores: list[bytes] = []
    current = data
    rank_prev = 1
    left = 1
    for index, dim in enumerate(shape[:-1]):
        rows = rank_prev * dim
        if rows == 0 or len(current) % rows:
            raise ValueError("invalid TT step")
        cols = len(current) // rows
        matrix = [current[row * cols : (row + 1) * cols] for row in range(rows)]
        rank, _pivots, u_rows, v_rows = factor_matrix(matrix, rows, cols)
        core = b"".join(u_rows)
        if len(core) != rows * rank:
            raise ValueError("bad core length")
        cores.append(core)
        ranks.append(rank)
        left *= dim
        right = total // left
        maximum = min(left, right)
        max_ranks.append(maximum)
        full_rank_cuts.append(rank == maximum)
        current = b"".join(v_rows)
        rank_prev = rank
    last = rank_prev * shape[-1]
    if len(current) != last:
        raise ValueError("bad final core length")
    cores.append(current)
    ranks.append(1)
    coefficient_count = sum(len(core) for core in cores)
    return {
        "ranks": ranks,
        "max_ranks": max_ranks,
        "full_rank_cuts": full_rank_cuts,
        "full_rank": all(full_rank_cuts),
        "cores": cores,
        "coefficient_count": coefficient_count,
        "shape": shape,
    }


def xor_bytes(left: bytes, right: bytes) -> bytes:
    size = len(left)
    return (int.from_bytes(left, "big") ^ int.from_bytes(right, "big")).to_bytes(size, "big")


def tt_contract(
    current: bytes,
    core: bytes,
    prefix: int,
    dim: int,
    rank_prev: int,
    rank_next: int,
) -> bytes:
    out = bytearray(prefix * dim * rank_next)
    if rank_next == 1:
        for row in range(prefix):
            base = row * rank_prev
            out_base = row * dim
            for coordinate in range(dim):
                value = 0
                core_base = coordinate
                for inner in range(rank_prev):
                    factor = current[base + inner]
                    if factor:
                        value ^= MUL[factor][core[core_base]]
                    core_base += dim
                out[out_base + coordinate] = value
    else:
        for row in range(prefix):
            base = row * rank_prev
            out_base = row * dim * rank_next
            for coordinate in range(dim):
                accum = bytearray(rank_next)
                for inner in range(rank_prev):
                    factor = current[base + inner]
                    if factor:
                        start = (inner * dim + coordinate) * rank_next
                        product = core[start : start + rank_next].translate(MUL[factor])
                        accum = xor_bytes(accum, product)
                start = out_base + coordinate * rank_next
                out[start : start + rank_next] = accum
    return bytes(out)


def tt_reconstruct_2d(cores: list[bytes], shape: tuple[int, ...], ranks: list[int]) -> bytes:
    if len(shape) != 2 or len(cores) != 2:
        raise ValueError("not a matrix representation")
    rows, cols = shape
    rank = ranks[1]
    left = cores[0]
    right = cores[1]
    if len(left) != rows * rank or len(right) != rank * cols:
        raise ValueError("bad matrix core size")
    out = bytearray(rows * cols)
    for row in range(rows):
        accum = bytearray(cols)
        base = row * rank
        for inner in range(rank):
            factor = left[base + inner]
            if factor:
                product = right[inner * cols : (inner + 1) * cols].translate(MUL[factor])
                accum = xor_bytes(accum, product)
        out[row * cols : (row + 1) * cols] = accum
    return bytes(out)


def tt_reconstruct(cores: list[bytes], shape: tuple[int, ...], ranks: list[int]) -> bytes:
    if len(shape) != len(cores):
        raise ValueError("core count mismatch")
    if ranks[0] != 1 or ranks[-1] != 1:
        raise ValueError("bad boundary ranks")
    if len(shape) == 2:
        return tt_reconstruct_2d(cores, shape, ranks)
    current = cores[0]
    prefix = shape[0]
    rank_prev = ranks[1]
    if len(current) != prefix * rank_prev:
        raise ValueError("bad first core")
    for index in range(1, len(shape) - 1):
        dim = shape[index]
        rank_next = ranks[index + 1]
        current = tt_contract(current, cores[index], prefix, dim, rank_prev, rank_next)
        prefix *= dim
        rank_prev = rank_next
    dim = shape[-1]
    current = tt_contract(current, cores[-1], prefix, dim, rank_prev, 1)
    if len(current) != shape_product(shape):
        raise ValueError("bad reconstructed size")
    return current


# ---------------------------------------------------------------------------
# reversible coordinate orderings


def unravel(index: int, shape: tuple[int, ...]) -> list[int]:
    coords = [0] * len(shape)
    for position in range(len(shape) - 1, -1, -1):
        index, coords[position] = divmod(index, shape[position])
    return coords


def ravel(coords: list[int], shape: tuple[int, ...]) -> int:
    index = 0
    for coordinate, dim in zip(coords, shape):
        index = index * dim + coordinate
    return index


def group_bits(value: int, bits: int) -> int:
    even = [(value >> position) & 1 for position in range(0, bits, 2)]
    odd = [(value >> position) & 1 for position in range(1, bits, 2)]
    out = 0
    for bit in even + odd:
        out = (out << 1) | bit
    return out


def build_permutation(shape: tuple[int, ...], order_id: int) -> list[int]:
    total = shape_product(shape)
    if order_id == 0:
        return list(range(total))
    if order_id == 1:
        effective = tuple(reversed(shape))
        perm = [0] * total
        for new_index in range(total):
            coords = unravel(new_index, effective)
            old_index = ravel(list(reversed(coords)), shape)
            perm[new_index] = old_index
        return perm
    if order_id == 2:
        bits = total.bit_length() - 1
        perm = [0] * total
        for old_index in range(total):
            new_index = group_bits(old_index, bits)
            perm[new_index] = old_index
        return perm
    raise ValueError("unknown ordering")


def apply_order(data: bytes, shape: tuple[int, ...], order_id: int) -> bytes:
    if order_id == 0:
        return data
    perm = build_permutation(shape, order_id)
    return bytes(data[index] for index in perm)


def invert_order(data: bytes, shape: tuple[int, ...], order_id: int) -> bytes:
    if order_id == 0:
        return data
    perm = build_permutation(shape, order_id)
    out = bytearray(len(data))
    for index, original in enumerate(perm):
        out[original] = data[index]
    return bytes(out)


# ---------------------------------------------------------------------------
# representation archive


def build_representation(data: bytes, shape: tuple[int, ...], order_id: int) -> tuple[bytes, dict]:
    if shape_product(shape) != len(data):
        raise ValueError("shape does not match data")
    effective = tuple(reversed(shape)) if order_id == 1 else shape
    permuted = apply_order(data, shape, order_id)
    tt = tt_decompose(permuted, effective)
    kind = 0 if len(shape) == 2 else 1
    header = bytearray(MAGIC_E)
    header += uvarint(len(data))
    header.append(order_id)
    header += uvarint(POLY)
    header.append(len(shape))
    for dim in shape:
        header += uvarint(dim)
    header.append(kind)
    cuts = tt["ranks"][1:-1]
    header += uvarint(len(cuts))
    for rank in cuts:
        header += uvarint(rank)
    header += uvarint(tt["coefficient_count"])
    archive = bytes(header) + b"".join(tt["cores"])
    meta = {
        "shape": list(shape),
        "effective_shape": list(effective),
        "order_id": order_id,
        "order": ORDERS[order_id],
        "kind": kind,
        "ranks": tt["ranks"],
        "cuts": cuts,
        "max_ranks": tt["max_ranks"],
        "full_rank_cuts": tt["full_rank_cuts"],
        "full_rank": tt["full_rank"],
        "coefficient_count": tt["coefficient_count"],
        "header_bytes": len(header),
        "archive_bytes": len(archive),
    }
    return archive, meta


def decode_representation(archive: bytes) -> tuple[bytes, dict]:
    if archive[: len(MAGIC_E)] != MAGIC_E:
        raise ValueError("bad representation magic")
    pos = len(MAGIC_E)
    total, pos = read_uvarint(archive, pos)
    if pos >= len(archive):
        raise ValueError("truncated header")
    order_id = archive[pos]
    pos += 1
    poly, pos = read_uvarint(archive, pos)
    if poly != POLY:
        raise ValueError("bad field polynomial")
    if pos >= len(archive):
        raise ValueError("truncated header")
    dimensions = archive[pos]
    pos += 1
    shape = []
    for _ in range(dimensions):
        dim, pos = read_uvarint(archive, pos)
        shape.append(dim)
    if pos >= len(archive):
        raise ValueError("truncated header")
    kind = archive[pos]
    pos += 1
    cut_count, pos = read_uvarint(archive, pos)
    cuts = []
    for _ in range(cut_count):
        rank, pos = read_uvarint(archive, pos)
        cuts.append(rank)
    coefficient_count, pos = read_uvarint(archive, pos)
    if shape_product(tuple(shape)) != total:
        raise ValueError("shape/product mismatch")
    ranks = [1] + cuts + [1]
    effective = tuple(reversed(shape)) if order_id == 1 else tuple(shape)
    cores = []
    remaining = coefficient_count
    for index, dim in enumerate(effective):
        size = ranks[index] * dim * ranks[index + 1]
        if pos + size > len(archive):
            raise ValueError("truncated core")
        cores.append(archive[pos : pos + size])
        pos += size
        remaining -= size
    if remaining != 0 or pos != len(archive):
        raise ValueError("core length mismatch")
    permuted = tt_reconstruct(cores, effective, ranks)
    data = invert_order(permuted, tuple(shape), order_id)
    meta = {
        "shape": shape,
        "effective_shape": list(effective),
        "order_id": order_id,
        "order": ORDERS[order_id],
        "kind": kind,
        "ranks": ranks,
        "cuts": cuts,
        "coefficient_count": coefficient_count,
        "header_bytes": len(archive) - coefficient_count,
        "archive_bytes": len(archive),
    }
    return data, meta


# ---------------------------------------------------------------------------
# matched controls


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
    if not sample:
        return 0
    compressor = zstd.ZstdCompressor(level=1)
    best_param = 0
    best_size = None
    for param in range(256):
        size = len(compressor.compress(global_apply(sample, param, op)))
        if best_size is None or size < best_size:
            best_size = size
            best_param = param
    return best_param


def build_d(data: bytes, shape: tuple[int, ...], order_id: int) -> tuple[bytes, dict]:
    permuted = apply_order(data, shape, order_id)
    payload = Z9.compress(permuted)
    header = bytearray(MAGIC_D)
    header += uvarint(len(data))
    header.append(order_id)
    header.append(len(shape))
    for dim in shape:
        header += uvarint(dim)
    archive = bytes(header) + payload
    return archive, {
        "header_bytes": len(header),
        "payload_bytes": len(payload),
        "permuted_sha256": sha256(permuted),
    }


def decode_d(archive: bytes) -> bytes:
    if archive[: len(MAGIC_D)] != MAGIC_D:
        raise ValueError("bad D magic")
    pos = len(MAGIC_D)
    total, pos = read_uvarint(archive, pos)
    order_id = archive[pos]
    pos += 1
    dimensions = archive[pos]
    pos += 1
    shape = []
    for _ in range(dimensions):
        dim, pos = read_uvarint(archive, pos)
        shape.append(dim)
    if shape_product(tuple(shape)) != total:
        raise ValueError("bad D shape")
    permuted = zstd.ZstdDecompressor().decompress(archive[pos:])
    return invert_order(permuted, tuple(shape), order_id)


def build_g(data: bytes) -> tuple[bytes, dict]:
    candidates = []
    for family_id, family in enumerate(("delta", "shuffle3", "global-add", "global-xor")):
        trailing = b""
        param = 0
        if family == "delta":
            body = delta_encode(data)
        elif family == "shuffle3":
            body, trailing = shuffle_encode(data, 3)
        elif family == "global-add":
            param = choose_global(data, "add")
            body = global_apply(data, param, "add")
        elif family == "global-xor":
            param = choose_global(data, "xor")
            body = global_apply(data, param, "xor")
        else:
            raise ValueError("bad G family")
        payload = Z9.compress(body)
        header = bytearray(MAGIC_G)
        header.append(family_id)
        header.append(param)
        header += uvarint(len(data))
        header += uvarint(len(trailing))
        header += trailing
        archive = bytes(header) + payload
        candidates.append(
            (
                len(archive),
                family_id,
                archive,
                {
                    "family": family,
                    "param": param,
                    "trailing_bytes": len(trailing),
                    "header_bytes": len(header),
                    "payload_bytes": len(payload),
                },
            )
        )
    candidates.sort(key=lambda item: (item[0], item[1]))
    size, _family_id, archive, meta = candidates[0]
    meta["archive_bytes"] = size
    return archive, meta


def decode_g(archive: bytes) -> bytes:
    if archive[: len(MAGIC_G)] != MAGIC_G:
        raise ValueError("bad G magic")
    pos = len(MAGIC_G)
    family_id = archive[pos]
    param = archive[pos + 1]
    pos += 2
    total, pos = read_uvarint(archive, pos)
    trailing_len, pos = read_uvarint(archive, pos)
    trailing = archive[pos : pos + trailing_len]
    pos += trailing_len
    body = zstd.ZstdDecompressor().decompress(archive[pos:])
    if family_id == 0:
        output = delta_decode(body)
    elif family_id == 1:
        output = shuffle_decode(body, trailing, 3)
    elif family_id == 2:
        output = global_apply(body, (-param) & 255, "add")
    elif family_id == 3:
        output = global_apply(body, param, "xor")
    else:
        raise ValueError("bad G family id")
    if family_id != 1:
        output += trailing
    if len(output) != total:
        raise ValueError("bad G output size")
    return output


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
            raise RuntimeError(f"{name} control failed")
        out[name] = {
            "size_bytes": len(blob) + extra,
            "encode_s": round(encode_s, 5),
            "decode_s": round(decode_s, 5),
            "decoded_ok": True,
        }
    return out


# ---------------------------------------------------------------------------
# development search and frozen validation


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


def dev_search_region(data: bytes, size: int) -> dict:
    rows = []
    for shape_index, (shape_name, shape) in enumerate(SHAPES[size]):
        for order_id, order_name in enumerate(ORDERS):
            started = time.perf_counter()
            archive, meta = build_representation(data, shape, order_id)
            encode_s = time.perf_counter() - started
            compressed = Z9.compress(archive)
            rows.append(
                {
                    "shape_index": shape_index,
                    "shape_name": shape_name,
                    "shape": list(shape),
                    "order_id": order_id,
                    "order": order_name,
                    "E_bytes": len(archive),
                    "F_bytes": len(compressed),
                    "coefficient_count": meta["coefficient_count"],
                    "header_bytes": meta["header_bytes"],
                    "ranks": meta["ranks"],
                    "max_ranks": meta["max_ranks"],
                    "full_rank": meta["full_rank"],
                    "full_rank_cuts": meta["full_rank_cuts"],
                    "encode_s": round(encode_s, 5),
                }
            )
    best_f = min(
        rows,
        key=lambda row: (row["F_bytes"], row["E_bytes"], row["shape_index"], row["order_id"]),
    )
    best_e = min(
        rows,
        key=lambda row: (row["E_bytes"], row["F_bytes"], row["shape_index"], row["order_id"]),
    )
    shape = tuple(best_f["shape"])
    archive, _meta = build_representation(data, shape, best_f["order_id"])
    decoded, _decoded_meta = decode_representation(archive)
    if decoded != data:
        raise RuntimeError("selected development representation failed exact reconstruction")
    return {
        "size": size,
        "rows": rows,
        "best_f": best_f,
        "best_e": best_e,
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
    selected: dict[str, dict] = {}
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
        best = result["best_f"]
        selected[str(size)] = {
            "shape_name": best["shape_name"],
            "shape": best["shape"],
            "order_id": best["order_id"],
            "order": best["order"],
            "dev_E_bytes": best["E_bytes"],
            "dev_F_bytes": best["F_bytes"],
            "dev_coefficient_count": best["coefficient_count"],
            "dev_ranks": best["ranks"],
            "dev_full_rank": best["full_rank"],
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


def peak_build(data: bytes, shape: tuple[int, ...], order_id: int) -> tuple[int, int]:
    tracemalloc.start()
    try:
        archive, _meta = build_representation(data, shape, order_id)
        _current, peak_encode = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    tracemalloc.start()
    try:
        decoded, _decoded_meta = decode_representation(archive)
        _current, peak_decode = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    if decoded != data:
        raise RuntimeError("peak trace reconstruction failed")
    return peak_encode, peak_decode


def validate_region(data: bytes, size: int, offset: int, config: dict) -> dict:
    shape = tuple(config["shape"])
    order_id = config["order_id"]
    started = time.perf_counter()
    archive, meta = build_representation(data, shape, order_id)
    encode_s = time.perf_counter() - started
    started = time.perf_counter()
    compressed = Z9.compress(archive)
    compressed_s = time.perf_counter() - started
    started = time.perf_counter()
    decoded, _decoded_meta = decode_representation(archive)
    decode_s = time.perf_counter() - started
    if decoded != data:
        raise RuntimeError("E representation failed exact reconstruction")
    started = time.perf_counter()
    decoded_f, _decoded_f_meta = decode_representation(zstd.ZstdDecompressor().decompress(compressed))
    decode_f_s = time.perf_counter() - started
    if decoded_f != data:
        raise RuntimeError("F representation failed exact reconstruction")

    d_archive, d_meta = build_d(data, shape, order_id)
    started = time.perf_counter()
    d_decoded = decode_d(d_archive)
    d_decode_s = time.perf_counter() - started
    if d_decoded != data:
        raise RuntimeError("D control failed exact reconstruction")

    g_archive, g_meta = build_g(data)
    started = time.perf_counter()
    g_decoded = decode_g(g_archive)
    g_decode_s = time.perf_counter() - started
    if g_decoded != data:
        raise RuntimeError("G control failed exact reconstruction")

    controls = run_controls(data)
    peak_encode, peak_decode = peak_build(data, shape, order_id)

    cuts = meta["ranks"][1:-1]
    low_rank_cut = any(
        rank <= max_rank / 2 for rank, max_rank in zip(cuts, meta["max_ranks"]) if max_rank
    )
    baseline_name, baseline_size = min(
        (
            ("A_zstd9", controls["A_zstd9"]["size_bytes"]),
            ("B_zstd19", controls["B_zstd19"]["size_bytes"]),
            ("C_lzma2", controls["C_lzma2"]["size_bytes"]),
            ("D", len(d_archive)),
            ("G", len(g_archive)),
        ),
        key=lambda item: (item[1], item[0]),
    )
    return {
        "split": "val",
        "offset": offset,
        "length": size,
        "sha256": sha256(data),
        "shape_name": meta["shape_name"] if "shape_name" in meta else config["shape_name"],
        "shape": list(shape),
        "order_id": order_id,
        "order": config["order"],
        "kind": meta["kind"],
        "ranks": meta["ranks"],
        "max_ranks": meta["max_ranks"],
        "cuts": cuts,
        "full_rank": meta["full_rank"],
        "full_rank_cuts": meta["full_rank_cuts"],
        "low_rank_cut": low_rank_cut,
        "coefficient_count": meta["coefficient_count"],
        "header_bytes": meta["header_bytes"],
        "E_bytes": len(archive),
        "F_bytes": len(compressed),
        "D_bytes": len(d_archive),
        "G_bytes": len(g_archive),
        "controls": controls,
        "baseline_name": baseline_name,
        "baseline_bytes": baseline_size,
        "F_vs_baseline": round(len(compressed) / baseline_size, 6),
        "E_vs_original": round(len(archive) / size, 6),
        "F_vs_original": round(len(compressed) / size, 6),
        "coefficient_ratio": round(meta["coefficient_count"] / size, 6),
        "saving_vs_baseline": round(1.0 - len(compressed) / baseline_size, 6),
        "encode_s": round(encode_s, 5),
        "compress_s": round(compressed_s, 5),
        "decode_s": round(decode_s, 5),
        "decode_f_s": round(decode_f_s, 5),
        "d_encode_bytes": len(d_archive),
        "d_decode_s": round(d_decode_s, 5),
        "g_family": g_meta["family"],
        "g_param": g_meta["param"],
        "g_decode_s": round(g_decode_s, 5),
        "peak_encode_kib": round(peak_encode / 1024, 1),
        "peak_decode_kib": round(peak_decode / 1024, 1),
        "decoded_ok": True,
        "decoded_f_ok": True,
        "decoded_sha256": sha256(decoded),
        "decoded_f_sha256": sha256(decoded_f),
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
            files = list(pool.map(run_val_file, [task[0] for task in tasks], [task[1] for task in tasks]))
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
        sum_f = sum(region["F_bytes"] for region in regions)
        sum_e = sum(region["E_bytes"] for region in regions)
        sum_base = sum(region["baseline_bytes"] for region in regions)
        sum_n = sum(region["length"] for region in regions)
        sum_coeff = sum(region["coefficient_count"] for region in regions)
        low_rank = any(region["low_rank_cut"] for region in regions)
        rows.append(
            {
                "name": file_record["name"],
                "sizes": [region["length"] for region in regions],
                "N": sum_n,
                "E": sum_e,
                "F": sum_f,
                "baseline": sum_base,
                "saving_vs_baseline": round(1.0 - sum_f / sum_base, 6),
                "coefficient_ratio": round(sum_coeff / sum_n, 6),
                "low_rank_cut": low_rank,
                "primary_pass": (1.0 - sum_f / sum_base) >= 0.01,
                "low_rank_candidate": (sum_coeff / sum_n) <= 0.75 and low_rank,
                "serialization_bottleneck": min(sum_e, sum_f) > 0.99 * sum_base,
            }
        )
    return rows


def compute_gate(val_payload: dict) -> dict:
    files = file_aggregates(val_payload)
    primary_files = [row["name"] for row in files if row["primary_pass"]]
    low_rank_files = [row["name"] for row in files if row["low_rank_candidate"]]
    bottleneck_files = [
        row["name"]
        for row in files
        if row["low_rank_candidate"] and row["serialization_bottleneck"]
    ]
    primary_pass = len(primary_files) >= 2
    low_rank_pass = len(low_rank_files) >= 2 and len(bottleneck_files) >= 2
    return {
        "files": files,
        "primary": {
            "min_saving": 0.01,
            "min_files": 2,
            "qualifying_files": primary_files,
            "passed": primary_pass,
        },
        "low_rank": {
            "coefficient_ratio_max": 0.75,
            "cut_rank_fraction_max": 0.5,
            "min_files": 2,
            "qualifying_files": low_rank_files,
            "bottleneck_files": bottleneck_files,
            "passed": low_rank_pass,
        },
        "passed": primary_pass or low_rank_pass,
    }


# ---------------------------------------------------------------------------
# self-test


def selftest() -> None:
    if len(set(EXP[:255])) != 255:
        raise AssertionError("GF generator does not cover the field")
    if MUL[0x57][0x83] != 0xC1:
        raise AssertionError("GF(256) multiplication mismatch")
    for value in range(1, 256):
        if MUL[value][INV[value]] != 1:
            raise AssertionError("bad inverse")
    rows = [
        bytes((1, 2, 3, 4)),
        bytes((2, 4, 6, 8)),
        bytes((0, 1, 1, 0)),
    ]
    rank, _pivots, u_rows, v_rows = factor_matrix(rows, 3, 4)
    if rank != 2:
        raise AssertionError("bad rank")
    reconstructed = matmul_gf(u_rows, v_rows, 3, rank, 4)
    if reconstructed != rows:
        raise AssertionError("matrix factorization is not exact")
    small = bytes(range(8))
    tt = tt_decompose(small, (2, 2, 2))
    if tt_reconstruct(tt["cores"], (2, 2, 2), tt["ranks"]) != small:
        raise AssertionError("tiny TT reconstruction failed")
    for shape in ((2, 2, 2), (2, 2, 2, 2), (4, 4)):
        for order in range(3):
            permuted = apply_order(small, shape, order) if shape_product(shape) == 8 else b""
            if not permuted:
                continue
            restored = invert_order(permuted, shape, order)
            if restored != small:
                raise AssertionError("ordering is not reversible")
    print("selftest: GF(256), matrix factorization, TT, orderings: ok")


# ---------------------------------------------------------------------------
# probe


def probe(name: str, size: int) -> None:
    path = next(ROOT / relative for key, relative, _kind in FILES if key == name)
    data = path.read_bytes()[:size]
    if len(data) < size:
        print(name, size, "unavailable")
        return
    for shape_name, shape in SHAPES[size]:
        started = time.perf_counter()
        tt = tt_decompose(data, shape)
        elapsed = time.perf_counter() - started
        print(
            f"{name:8} {size:6d} {shape_name:7} ranks={tt['ranks']} "
            f"coeff={tt['coefficient_count']} ratio={tt['coefficient_count']/size:.3f} "
            f"full={tt['full_rank']} time={elapsed:.3f}"
        )


def protocol_dict() -> dict:
    return {
        "phase": 17,
        "episode": 1,
        "codec": "exact finite-field matrix/Tensor-Train representation v1.0",
        "field": {
            "name": "GF(2^8)",
            "polynomial": "0x11B",
            "addition": "XOR",
            "multiplication": "log/exp and 256x256 lookup tables",
        },
        "sizes": list(SIZES),
        "shapes": {
            str(size): [{"name": name, "dims": list(shape)} for name, shape in SHAPES[size]]
            for size in SIZES
        },
        "orders": list(ORDERS),
        "region_rule": (
            "first and last disjoint equal regions of each requested size; "
            "size is skipped when file_bytes < 2*size; no padding"
        ),
        "selection": "per file/size best compressed representation (F) on dev, frozen before validation",
        "controls": {
            "A": "zstd level 9 on raw region",
            "B": "zstd level 19 on raw region",
            "C": "raw LZMA2 preset 6 plus one selector byte",
            "D": "selected coordinate ordering + zstd level 9, no decomposition",
            "E": "exact serialized matrix/TT representation alone",
            "F": "same serialized representation + zstd level 9",
            "G": "best of delta, stride-3 shuffle, global add, global xor + zstd level 9",
        },
        "gate": {
            "primary": {
                "min_saving": 0.01,
                "min_files": 2,
                "baseline": "min(A,B,C,D,G) per region, summed over available sizes per file",
            },
            "low_rank": {
                "coefficient_ratio_max": 0.75,
                "cut_rank_fraction_max": 0.5,
                "min_files": 2,
                "bottleneck": "min(sum E, sum F) > 0.99 * sum baseline on a low-rank file",
            },
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf8")


def print_dev(payload: dict) -> None:
    print(f"{'file':8} {'size':>6} {'shape':8} {'order':12} {'E':>7} {'F':>7} {'coeff':>7} {'ratio':>6} {'full':>5} ranks")
    for file_record in payload["files"]:
        for size_key, region in file_record["regions"].items():
            best = region["best_f"]
            print(
                f"{file_record['name']:8} {int(size_key):6d} {best['shape_name']:8} {best['order']:12} "
                f"{best['E_bytes']:7d} {best['F_bytes']:7d} {best['coefficient_count']:7d} "
                f"{best['coefficient_count'] / int(size_key):6.3f} {str(best['full_rank']):>5} "
                f"{best['ranks']}"
            )
    print(f"dev elapsed {payload['elapsed_s']} s")


def print_val(payload: dict) -> None:
    print(
        f"{'file':8} {'size':>6} {'shape':8} {'order':12} {'E':>7} {'F':>7} "
        f"{'D':>7} {'G':>7} {'A':>7} {'base':>7} {'F/base':>7} {'coeff/N':>7} ranks"
    )
    for file_record in payload["validation"]["files"]:
        for size_key, region in file_record["regions"].items():
            print(
                f"{file_record['name']:8} {int(size_key):6d} {region['shape_name']:8} {region['order']:12} "
                f"{region['E_bytes']:7d} {region['F_bytes']:7d} {region['D_bytes']:7d} "
                f"{region['G_bytes']:7d} {region['controls']['A_zstd9']['size_bytes']:7d} "
                f"{region['baseline_bytes']:7d} {region['F_vs_baseline']:7.3f} "
                f"{region['coefficient_ratio']:7.3f} {region['ranks']}"
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
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        out = Path(args.out) if args.out else RESULTS / "phase17-dev.json"
        write_json(out, payload)
        print_dev(payload)
    elif args.split == "val":
        dev_path = RESULTS / "phase17-dev.json"
        dev = json.loads(dev_path.read_text(encoding="utf8"))
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 17,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase17.json"
        write_json(out, payload)
        print_val(payload)
    else:
        dev = run_dev(only=args.file)
        dev_payload = {
            "phase": 17,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        write_json(RESULTS / "phase17-dev.json", dev_payload)
        print_dev(dev_payload)
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 17,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase17.json"
        write_json(out, payload)
        print_val(payload)


if __name__ == "__main__":
    main()
