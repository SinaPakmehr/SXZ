#!/usr/bin/env python3
"""Phase 17 Episode 3: bounded exact multidimensional recurrence discovery.

Reuses the GF(2^8) arithmetic and RREF solver from Episode 1.  For a reshaped
byte array, a causal linear recurrence is fitted on an initial prefix of
eligible coordinates and verified on the remaining eligible coordinates.
Candidates contain at most 16 coefficients, including the optional affine
constant.  Two residual codings are measured: raw XOR residuals and zstd-9
residuals.  Decoding uses only serialized boundary values, coefficients and
residuals; original data is never consulted.
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
sys.path.insert(0, str(SCRIPT_DIR))
import run_phase17 as ep1  # noqa: E402  (reuse GF(256), solver and utilities)

ROOT = ep1.ROOT
RESULTS = ROOT / "lab/sxz-emar/results"
MAGIC = b"SXZ17R1"
MAGIC_D = b"SXZ17D3"
Z9 = ep1.Z9
Z19 = ep1.Z19
LZMA_FILTERS = ep1.LZMA_FILTERS
FILES = ep1.FILES

SHAPES = (
    ("2d", (64, 64)),
    ("3d", (16, 16, 16)),
    ("4d", (8, 8, 8, 8)),
)
SIZES = (4096,)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def uvarint(value: int) -> bytes:
    return ep1.uvarint(value)


def read_uvarint(buf: bytes, pos: int) -> tuple[int, int]:
    return ep1.read_uvarint(buf, pos)


def strides(shape: tuple[int, ...]) -> list[int]:
    out = [1] * len(shape)
    for index in range(len(shape) - 2, -1, -1):
        out[index] = out[index + 1] * shape[index + 1]
    return out


def coords_of(index: int, shape: tuple[int, ...]) -> tuple[int, ...]:
    coords = [0] * len(shape)
    for position in range(len(shape) - 1, -1, -1):
        index, coords[position] = divmod(index, shape[position])
    return tuple(coords)


def flat_delta(shift: tuple[int, ...], stride: list[int]) -> int:
    return sum(component * step for component, step in zip(shift, stride))


def neighborhoods(dimensions: int) -> list[tuple[str, tuple[tuple[int, ...], ...]]]:
    axes = []
    for axis in range(dimensions):
        shift = [0] * dimensions
        shift[axis] = -1
        axes.append(tuple(shift))
    axes = tuple(axes)
    diagonal = []
    for mask in range(1, 1 << dimensions):
        shift = tuple(-1 if mask >> axis & 1 else 0 for axis in range(dimensions))
        diagonal.append(shift)
    diagonal = tuple(diagonal)
    diag2 = diagonal
    shift2 = [-2] + [0] * (dimensions - 1)
    if len(diag2) < 16:
        diag2 = diag2 + (tuple(shift2),)
    axes2 = axes
    for axis in range(dimensions):
        shift = [0] * dimensions
        shift[axis] = -2
        axes2 = axes2 + (tuple(shift),)
    return [
        ("axes", axes),
        ("diagonal", diagonal),
        ("diag2", diag2),
        ("axes2", axes2),
    ]


def mask_for(shape: tuple[int, ...], shifts: tuple[tuple[int, ...], ...]) -> tuple[list[int], list[int], list[int]]:
    offsets = [0] * len(shape)
    for shift in shifts:
        for axis, component in enumerate(shift):
            offsets[axis] = max(offsets[axis], -component)
    eligible = []
    boundary = []
    total = 1
    for dim in shape:
        total *= dim
    for index in range(total):
        coords = coords_of(index, shape)
        if all(coords[axis] >= offsets[axis] for axis in range(len(shape))):
            eligible.append(index)
        else:
            boundary.append(index)
    return offsets, eligible, boundary


def boundary_count(shape: tuple[int, ...], offsets: list[int]) -> int:
    interior = 1
    for dim, offset in zip(shape, offsets):
        interior *= max(0, dim - offset)
    total = 1
    for dim in shape:
        total *= dim
    return total - interior


def solve_system(rows: list[bytes], targets: list[int], nvars: int) -> dict | None:
    if nvars == 0:
        if all(target == 0 for target in targets):
            return {"rank": 0, "nullity": 0, "coeffs": b"", "consistent": True}
        return None
    augmented = [row + bytes((target,)) for row, target in zip(rows, targets)]
    rank, pivots, _u_rows, v_rows = ep1.factor_matrix(
        augmented, len(augmented), nvars + 1
    )
    if any(pivot == nvars for pivot in pivots):
        return None
    coeffs = bytearray(nvars)
    for row_index, pivot in enumerate(pivots):
        if pivot < nvars:
            coeffs[pivot] = v_rows[row_index][-1]
    rank_a = len(pivots)
    return {
        "rank": rank_a,
        "nullity": nvars - rank_a,
        "coeffs": bytes(coeffs),
        "consistent": True,
    }


def feature_target(
    data: bytes,
    index: int,
    shape: tuple[int, ...],
    kind: int,
    shifts: tuple[tuple[int, ...], ...],
    lags: tuple[int, ...],
    stride: list[int],
    affine: bool,
) -> tuple[bytes, int]:
    if kind == 0:
        values = bytes(data[index + flat_delta(shift, stride)] for shift in shifts)
    else:
        values = bytes(data[index - lag] for lag in lags)
    if affine:
        values += b"\x01"
    return values, data[index]


def predict(
    data: bytes,
    index: int,
    kind: int,
    shifts: tuple[tuple[int, ...], ...],
    lags: tuple[int, ...],
    stride: list[int],
    coeffs: bytes,
    affine: bool,
) -> int:
    value = 0
    if kind == 0:
        for position, shift in enumerate(shifts):
            coefficient = coeffs[position]
            if coefficient:
                value ^= ep1.MUL[coefficient][data[index + flat_delta(shift, stride)]]
    else:
        for position, lag in enumerate(lags):
            coefficient = coeffs[position]
            if coefficient:
                value ^= ep1.MUL[coefficient][data[index - lag]]
    if affine:
        value ^= coeffs[len(shifts) if kind == 0 else len(lags)]
    return value


def fit_model(
    data: bytes,
    shape: tuple[int, ...],
    kind: int,
    shifts: tuple[tuple[int, ...], ...],
    lags: tuple[int, ...],
    affine: bool,
    mask_shifts: tuple[tuple[int, ...], ...] | None = None,
) -> dict:
    offsets, eligible, boundary = mask_for(shape, mask_shifts if mask_shifts is not None else shifts)
    nvars = (len(shifts) if kind == 0 else len(lags)) + (1 if affine else 0)
    stride = strides(shape)
    train_target = min(len(eligible), max(nvars + 2, len(eligible) // 2))
    sizes = []
    for size in (train_target, nvars + 4, nvars + 2, nvars + 1, nvars, max(1, nvars // 2), 1):
        if 1 <= size <= len(eligible) and size not in sizes:
            sizes.append(size)
    solution = None
    train_size = 0
    for size in sizes:
        rows = []
        targets = []
        valid = True
        for index in eligible[:size]:
            values, target = feature_target(
                data, index, shape, kind, shifts, lags, stride, affine
            )
            rows.append(values)
            targets.append(target)
        if not valid:
            continue
        candidate = solve_system(rows, targets, nvars)
        if candidate is not None:
            solution = candidate
            train_size = size
            break
    if solution is None:
        solution = {
            "rank": 0,
            "nullity": nvars,
            "coeffs": bytes(nvars),
            "consistent": False,
        }
        train_size = 0
    coeffs = solution["coeffs"]

    mismatches = []
    train_correct = 0
    test_correct = 0
    for order, index in enumerate(eligible):
        actual = data[index]
        predicted = predict(data, index, kind, shifts, lags, stride, coeffs, affine)
        if predicted == actual:
            if order < train_size:
                train_correct += 1
            else:
                test_correct += 1
        else:
            mismatches.append((index, predicted ^ actual))
    train_rate = train_correct / train_size if train_size else 0.0
    test_count = len(eligible) - train_size
    test_rate = test_correct / test_count if test_count else 0.0
    coverage = 1.0 - len(mismatches) / len(eligible) if eligible else 0.0

    shift_coeffs = coeffs[: (len(shifts) if kind == 0 else len(lags))]
    nonzero = [position for position, value in enumerate(shift_coeffs) if value]
    used_axes = set()
    if kind == 0:
        for position in nonzero:
            for axis, component in enumerate(shifts[position]):
                if component:
                    used_axes.add(axis)
    constant = len(nonzero) == 0
    periodic = (
        len(nonzero) == 1 and shift_coeffs[nonzero[0]] == 1 and not affine
    )
    return {
        "kind": kind,
        "shape": list(shape),
        "shape_name": None,
        "shifts": [list(shift) for shift in shifts],
        "lags": list(lags),
        "offset": offsets,
        "affine": affine,
        "nvars": nvars,
        "coeffs": coeffs,
        "rank": solution["rank"],
        "nullity": solution["nullity"],
        "consistent": solution["consistent"],
        "train_size": train_size,
        "eligible_count": len(eligible),
        "boundary_count": len(boundary),
        "boundary_indices": boundary,
        "train_rate": round(train_rate, 6),
        "test_rate": round(test_rate, 6),
        "coverage": round(coverage, 6),
        "mismatches": mismatches,
        "constant": constant,
        "periodic": periodic,
        "used_axes": sorted(used_axes),
        "nontrivial_multidim": kind == 0
        and not constant
        and not periodic
        and len(used_axes) >= 2,
    }


def encode_residuals(mismatches: list[tuple[int, int]]) -> bytes:
    out = bytearray()
    out += uvarint(len(mismatches))
    previous = 0
    for index, value in mismatches:
        out += uvarint(index - previous)
        out.append(value)
        previous = index
    return bytes(out)


def _header(model: dict, residual_mode: int, residual_count: int, payload_len: int) -> bytes:
    header = bytearray(MAGIC)
    header.append(model["kind"])
    header.append(len(model["shape"]))
    for dim in model["shape"]:
        header += uvarint(dim)
    header += uvarint(0x11B)
    header.append(0)  # raster ordering
    for offset in model["offset"]:
        header += uvarint(offset)
    header.append(1 if model["affine"] else 0)
    if model["kind"] == 0:
        header += uvarint(len(model["shifts"]))
        for shift in model["shifts"]:
            for component in shift:
                header += uvarint(-component)
    else:
        header += uvarint(len(model["lags"]))
        for lag in model["lags"]:
            header += uvarint(lag)
    header += uvarint(len(model["coeffs"]))
    header += model["coeffs"]
    header += uvarint(model["rank"])
    header += uvarint(model["nullity"])
    header.append(1 if model["consistent"] else 0)
    header += uvarint(model["train_size"])
    header += uvarint(model["eligible_count"])
    header += uvarint(model["boundary_count"])
    header.append(residual_mode)
    header += uvarint(residual_count)
    header += uvarint(payload_len)
    return bytes(header)


def serialize_model(data: bytes, model: dict, residual_mode: int) -> tuple[bytes, dict] | None:
    if residual_mode == 0 and model["mismatches"]:
        return None
    if residual_mode == 1:
        payload = encode_residuals(model["mismatches"])
    elif residual_mode == 2:
        raw = encode_residuals(model["mismatches"])
        payload = Z9.compress(raw)
    elif residual_mode == 0:
        payload = b""
    else:
        raise ValueError("bad residual mode")
    header = _header(model, residual_mode, len(model["mismatches"]), len(payload))
    boundary = bytes(data[index] for index in model["boundary_indices"])
    archive = header + boundary + payload
    meta = {
        "kind": "md" if model["kind"] == 0 else "1d",
        "shape": model["shape"],
        "shape_name": model["shape_name"],
        "affine": model["affine"],
        "rank": model["rank"],
        "nullity": model["nullity"],
        "consistent": model["consistent"],
        "train_size": model["train_size"],
        "eligible_count": model["eligible_count"],
        "train_rate": model["train_rate"],
        "test_rate": model["test_rate"],
        "coverage": model["coverage"],
        "boundary_count": model["boundary_count"],
        "nonzero_coefficients": sum(1 for value in model["coeffs"] if value),
        "coeffs": list(model["coeffs"]),
        "shifts": model["shifts"],
        "lags": model["lags"],
        "constant": model["constant"],
        "periodic": model["periodic"],
        "used_axes": model["used_axes"],
        "nontrivial_multidim": model["nontrivial_multidim"],
        "residual_mode": residual_mode,
        "residual_count": len(model["mismatches"]),
        "model_bytes": len(header),
        "boundary_bytes": len(boundary),
        "residual_bytes": len(payload),
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
    }
    return archive, meta


def decode_model(archive: bytes) -> bytes:
    if archive[: len(MAGIC)] != MAGIC:
        raise ValueError("bad recurrence magic")
    pos = len(MAGIC)
    kind = archive[pos]
    pos += 1
    shape_count = archive[pos]
    pos += 1
    shape = []
    for _ in range(shape_count):
        dim, pos = read_uvarint(archive, pos)
        shape.append(dim)
    poly, pos = read_uvarint(archive, pos)
    if poly != 0x11B:
        raise ValueError("bad field")
    order = archive[pos]
    pos += 1
    if order != 0:
        raise ValueError("bad ordering")
    offsets = []
    for _ in range(shape_count):
        offset, pos = read_uvarint(archive, pos)
        offsets.append(offset)
    affine = bool(archive[pos])
    pos += 1
    if kind == 0:
        shift_count, pos = read_uvarint(archive, pos)
        shifts = []
        for _ in range(shift_count):
            shift = []
            for _axis in range(shape_count):
                magnitude, pos = read_uvarint(archive, pos)
                shift.append(-magnitude)
            shifts.append(tuple(shift))
        lags = ()
    elif kind == 1:
        shift_count, pos = read_uvarint(archive, pos)
        lags = []
        for _ in range(shift_count):
            lag, pos = read_uvarint(archive, pos)
            lags.append(lag)
        shifts = ()
    else:
        raise ValueError("bad recurrence kind")
    coeff_count, pos = read_uvarint(archive, pos)
    coeffs = archive[pos : pos + coeff_count]
    pos += coeff_count
    rank, pos = read_uvarint(archive, pos)
    nullity, pos = read_uvarint(archive, pos)
    consistent = bool(archive[pos])
    pos += 1
    train_size, pos = read_uvarint(archive, pos)
    eligible_count, pos = read_uvarint(archive, pos)
    boundary_count, pos = read_uvarint(archive, pos)
    residual_mode = archive[pos]
    pos += 1
    residual_count, pos = read_uvarint(archive, pos)
    payload_len, pos = read_uvarint(archive, pos)
    boundary = archive[pos : pos + boundary_count]
    pos += boundary_count
    payload = archive[pos : pos + payload_len]
    pos += payload_len
    if pos != len(archive):
        raise ValueError("trailing recurrence bytes")

    total = 1
    for dim in shape:
        total *= dim
    offsets_tuple = tuple(shape)
    boundary_indices = []
    eligible = []
    for index in range(total):
        coords = coords_of(index, tuple(shape))
        if all(coords[axis] >= offsets[axis] for axis in range(shape_count)):
            eligible.append(index)
        else:
            boundary_indices.append(index)
    if len(boundary_indices) != boundary_count:
        raise ValueError("boundary mask mismatch")
    if residual_mode == 0:
        residual_stream = b""
    elif residual_mode == 1:
        residual_stream = payload
    elif residual_mode == 2:
        residual_stream = zstd.ZstdDecompressor().decompress(payload)
    else:
        raise ValueError("bad residual mode")
    residual_map = {}
    if residual_count:
        cursor = 0
        count, cursor = read_uvarint(residual_stream, cursor)
        if count != residual_count:
            raise ValueError("residual count mismatch")
        previous = 0
        for _ in range(count):
            delta, cursor = read_uvarint(residual_stream, cursor)
            index = previous + delta
            value = residual_stream[cursor]
            cursor += 1
            residual_map[index] = value
            previous = index
        if cursor != len(residual_stream):
            raise ValueError("residual trailing bytes")
    data = bytearray(total)
    for index, value in zip(boundary_indices, boundary):
        data[index] = value
    stride = strides(tuple(shape))
    for index in eligible:
        value = predict(
            data, index, kind, tuple(shifts), tuple(lags), stride, coeffs, affine
        )
        if index in residual_map:
            value ^= residual_map.pop(index)
        data[index] = value
    if residual_map:
        raise ValueError("residual outside eligible coordinates")
    return bytes(data)


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


def predictor_encode(data: bytes, shape: tuple[int, ...], predictor: int) -> bytes:
    total = len(data)
    stride = strides(shape)
    out = bytearray(total)
    if predictor == 0:
        return delta_encode(data)
    if predictor == 1:
        out[0] = data[0]
        for index in range(1, total):
            out[index] = data[index] ^ data[index - 1]
        return bytes(out)
    for index in range(total):
        coords = coords_of(index, shape)
        predicted = 0
        if coords[-1] > 0:
            predicted = data[index - 1]
        elif len(shape) > 1 and coords[0] > 0:
            predicted = data[index - stride[0]]
        if predictor == 2:
            out[index] = (data[index] - predicted) & 255
        else:
            out[index] = data[index] ^ predicted
    return bytes(out)


def predictor_decode(data: bytes, shape: tuple[int, ...], predictor: int) -> bytes:
    total = len(data)
    stride = strides(shape)
    if predictor == 0:
        return delta_decode(data)
    if predictor == 1:
        out = bytearray(total)
        out[0] = data[0]
        for index in range(1, total):
            out[index] = data[index] ^ out[index - 1]
        return bytes(out)
    out = bytearray(total)
    for index in range(total):
        coords = coords_of(index, shape)
        predicted = 0
        if coords[-1] > 0:
            predicted = out[index - 1]
        elif len(shape) > 1 and coords[0] > 0:
            predicted = out[index - stride[0]]
        if predictor == 2:
            out[index] = (data[index] + predicted) & 255
        else:
            out[index] = data[index] ^ predicted
    return bytes(out)


def build_d(data: bytes, shape: tuple[int, ...]) -> tuple[bytes, dict]:
    candidates = []
    for predictor in range(4):
        residual = predictor_encode(data, shape, predictor)
        payload = Z9.compress(residual)
        header = bytearray(MAGIC_D)
        header.append(predictor)
        header.append(len(shape))
        for dim in shape:
            header += uvarint(dim)
        header += uvarint(len(data))
        archive = bytes(header) + payload
        candidates.append((len(archive), predictor, archive))
    candidates.sort(key=lambda item: (item[0], item[1]))
    size, predictor, archive = candidates[0]
    return archive, {"predictor": predictor, "exact_bytes": size}


def decode_d(archive: bytes) -> bytes:
    if archive[: len(MAGIC_D)] != MAGIC_D:
        raise ValueError("bad D magic")
    predictor = archive[len(MAGIC_D)]
    pos = len(MAGIC_D) + 1
    shape_count = archive[pos]
    pos += 1
    shape = []
    for _ in range(shape_count):
        dim, pos = read_uvarint(archive, pos)
        shape.append(dim)
    total, pos = read_uvarint(archive, pos)
    residual = zstd.ZstdDecompressor().decompress(archive[pos:])
    if len(residual) != total:
        raise ValueError("bad D length")
    return predictor_decode(residual, tuple(shape), predictor)


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
# self-test and probe


def selftest() -> None:
    # A 4x4 2D field generated by a[1,1] = a[0,0] + 3*a[0,1]
    data = bytearray(16)
    for i in range(4):
        data[i] = i + 1
    for y in range(4):
        for x in range(4):
            if y == 0:
                data[y * 4 + x] = (x + 1) & 255
            elif x == 0:
                data[y * 4 + x] = (y + 3) & 255
            else:
                data[y * 4 + x] = (
                    data[(y - 1) * 4 + x - 1] ^ ep1.MUL[3][data[(y - 1) * 4 + x]]
                )
    shifts = ((0, -1), (-1, 0), (-1, -1))
    model = fit_model(bytes(data), (4, 4), 0, shifts, (), False)
    for mode in (0, 1, 2):
        result = serialize_model(bytes(data), model, mode)
        if result is None:
            continue
        archive, _meta = result
        if decode_model(archive) != bytes(data):
            raise AssertionError("recurrence decode")
    # bit-plane/order control
    for predictor in range(4):
        residual = predictor_encode(bytes(data), (4, 4), predictor)
        if predictor_decode(residual, (4, 4), predictor) != bytes(data):
            raise AssertionError("predictor")
    print("selftest: GF recurrence fit, residuals, decode, predictors: ok")


def lags_from_shifts(
    shape: tuple[int, ...], shifts: tuple[tuple[int, ...], ...]
) -> tuple[int, ...]:
    stride = strides(shape)
    return tuple(sorted({-flat_delta(shift, stride) for shift in shifts}))


def variants_for_model(
    data: bytes, model: dict
) -> dict[str, tuple[bytes, dict] | None]:
    exact = serialize_model(data, model, 0)
    raw = serialize_model(data, model, 1)
    zstd = serialize_model(data, model, 2)
    return {"exact": exact, "raw": raw, "zstd": zstd}


def best_variant(variants: dict[str, tuple[bytes, dict] | None]) -> tuple[str, int] | None:
    sizes = [
        (meta["exact_bytes"], mode)
        for mode, value in variants.items()
        if value is not None
        for meta in (value[1],)
    ]
    if not sizes:
        return None
    size, mode = min(sizes, key=lambda item: (item[0], item[1]))
    return mode, size


def dev_search_region(data: bytes, size: int) -> dict:
    rows = []
    for shape_name, shape in SHAPES:
        for neighborhood, shifts in neighborhoods(len(shape)):
            for affine in (False, True):
                if len(shifts) + (1 if affine else 0) > 16:
                    continue
                model = fit_model(data, shape, 0, shifts, (), affine)
                model["shape_name"] = shape_name
                variants = variants_for_model(data, model)
                lags = lags_from_shifts(shape, shifts)
                e_model = fit_model(
                    data, shape, 1, (), lags, affine, mask_shifts=shifts
                )
                e_model["shape_name"] = shape_name
                e_variants = variants_for_model(data, e_model)
                md_best = best_variant(variants)
                e_best = best_variant(e_variants)
                rows.append(
                    {
                        "shape_name": shape_name,
                        "shape": list(shape),
                        "neighborhood": neighborhood,
                        "affine": affine,
                        "rank": model["rank"],
                        "nullity": model["nullity"],
                        "consistent": model["consistent"],
                        "train_size": model["train_size"],
                        "eligible_count": model["eligible_count"],
                        "boundary_count": model["boundary_count"],
                        "train_rate": model["train_rate"],
                        "test_rate": model["test_rate"],
                        "coverage": model["coverage"],
                        "nonzero_coefficients": sum(1 for c in model["coeffs"] if c),
                        "coeffs": list(model["coeffs"]),
                        "constant": model["constant"],
                        "periodic": model["periodic"],
                        "used_axes": model["used_axes"],
                        "nontrivial_multidim": model["nontrivial_multidim"],
                        "md_variants": {
                            mode: (value[1]["exact_bytes"] if value else None)
                            for mode, value in variants.items()
                        },
                        "md_best": {"mode": md_best[0], "bytes": md_best[1]} if md_best else None,
                        "e_rank": e_model["rank"],
                        "e_nullity": e_model["nullity"],
                        "e_coverage": e_model["coverage"],
                        "e_best": {"mode": e_best[0], "bytes": e_best[1]} if e_best else None,
                        "e_variants": {
                            mode: (value[1]["exact_bytes"] if value else None)
                            for mode, value in e_variants.items()
                        },
                        "shifts": [list(shift) for shift in shifts],
                        "lags": list(lags),
                    }
                )
    any_rows = [row for row in rows if row["md_best"]]
    best_any = min(any_rows, key=lambda row: (row["md_best"]["bytes"], row["shape_name"], row["neighborhood"], row["affine"]))
    nontrivial = [row for row in any_rows if row["nontrivial_multidim"]]
    best_nontrivial = (
        min(nontrivial, key=lambda row: (row["md_best"]["bytes"], row["shape_name"], row["neighborhood"], row["affine"]))
        if nontrivial
        else None
    )
    selected = best_nontrivial or best_any
    selected_model = None
    if selected:
        shape = tuple(selected["shape"])
        affine = selected["affine"]
        if selected["neighborhood"]:
            shape_name = selected["shape_name"]
            shifts = tuple(tuple(shift) for shift in selected["shifts"])
            selected_model = fit_model(data, shape, 0, shifts, (), affine)
            selected_model["shape_name"] = shape_name
    archive = None
    if selected and selected_model:
        mode = selected["md_best"]["mode"]
        result = serialize_model(data, selected_model, {"exact": 0, "raw": 1, "zstd": 2}[mode])
        if result is None:
            raise RuntimeError("selected development recurrence unavailable")
        archive, _meta = result
        decoded = decode_model(archive)
        if decoded != data:
            raise RuntimeError("selected development recurrence failed exact reconstruction")
    return {
        "size": size,
        "rows": rows,
        "best_any": best_any,
        "best_nontrivial": best_nontrivial,
        "selected": selected,
        "selected_exact": archive is not None,
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
            **result,
        }
        selected[str(size)] = result["selected"]
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


def validate_region(data: bytes, size: int, offset: int, config: dict) -> dict:
    shape = tuple(config["shape"])
    shape_name = config["shape_name"]
    shifts = tuple(tuple(shift) for shift in config["shifts"])
    affine = config["affine"]
    started = time.perf_counter()
    model = fit_model(data, shape, 0, shifts, (), affine)
    model["shape_name"] = shape_name
    variants = variants_for_model(data, model)
    encode_s = time.perf_counter() - started
    mode = config["md_best"]["mode"]
    selected_archive, selected_meta = variants[mode]
    if selected_archive is None:
        raise RuntimeError("selected validation recurrence unavailable")
    started = time.perf_counter()
    decoded = decode_model(selected_archive)
    decode_s = time.perf_counter() - started
    if decoded != data:
        raise RuntimeError("selected recurrence failed exact reconstruction")
    exact_archive = variants["exact"][0] if variants["exact"] else None
    exact_decoded_ok = None
    if exact_archive is not None:
        exact_decoded_ok = decode_model(exact_archive) == data
        if not exact_decoded_ok:
            raise RuntimeError("exact recurrence failed exact reconstruction")
    raw_archive, _raw_meta = variants["raw"]
    started = time.perf_counter()
    raw_decoded = decode_model(raw_archive)
    raw_decode_s = time.perf_counter() - started
    if raw_decoded != data:
        raise RuntimeError("raw-residual recurrence failed exact reconstruction")

    lags = lags_from_shifts(shape, shifts)
    e_model = fit_model(data, shape, 1, (), lags, affine, mask_shifts=shifts)
    e_model["shape_name"] = shape_name
    e_variants = variants_for_model(data, e_model)
    e_mode, e_best = best_variant(e_variants)
    e_archive, _e_meta = e_variants[e_mode]
    e_decoded = decode_model(e_archive)
    if e_decoded != data:
        raise RuntimeError("1D control failed exact reconstruction")

    d_archive, d_meta = build_d(data, shape)
    d_decoded = decode_d(d_archive)
    if d_decoded != data:
        raise RuntimeError("D control failed exact reconstruction")
    controls = run_controls(data)
    baseline_name, baseline_bytes = min(
        (
            ("A_zstd9", controls["A_zstd9"]["size_bytes"]),
            ("B_zstd19", controls["B_zstd19"]["size_bytes"]),
            ("C_lzma2", controls["C_lzma2"]["size_bytes"]),
            ("D", len(d_archive)),
            ("E", e_best),
        ),
        key=lambda item: (item[1], item[0]),
    )
    md_best_mode, md_best_bytes = best_variant(variants)
    return {
        "split": "val",
        "offset": offset,
        "length": size,
        "sha256": sha256(data),
        "shape_name": shape_name,
        "shape": list(shape),
        "neighborhood": config["neighborhood"],
        "affine": affine,
        "shifts": [list(shift) for shift in shifts],
        "rank": model["rank"],
        "nullity": model["nullity"],
        "consistent": model["consistent"],
        "train_size": model["train_size"],
        "eligible_count": model["eligible_count"],
        "boundary_count": model["boundary_count"],
        "train_rate": model["train_rate"],
        "test_rate": model["test_rate"],
        "coverage": model["coverage"],
        "nonzero_coefficients": sum(1 for c in model["coeffs"] if c),
        "coeffs": list(model["coeffs"]),
        "constant": model["constant"],
        "periodic": model["periodic"],
        "used_axes": model["used_axes"],
        "nontrivial_multidim": model["nontrivial_multidim"],
        "md_variants": {
            name: (value[1]["exact_bytes"] if value else None)
            for name, value in variants.items()
        },
        "md_best_mode": md_best_mode,
        "md_best_bytes": md_best_bytes,
        "exact_bytes": len(exact_archive) if exact_archive else None,
        "raw_bytes": variants["raw"][1]["exact_bytes"],
        "zstd_bytes": variants["zstd"][1]["exact_bytes"],
        "model_bytes": selected_meta["model_bytes"],
        "boundary_bytes": selected_meta["boundary_bytes"],
        "residual_bytes": selected_meta["residual_bytes"],
        "residual_count": selected_meta["residual_count"],
        "E_rank": e_model["rank"],
        "E_nullity": e_model["nullity"],
        "E_coverage": e_model["coverage"],
        "E_best_mode": e_mode,
        "E_best_bytes": e_best,
        "E_variants": {
            name: (value[1]["exact_bytes"] if value else None)
            for name, value in e_variants.items()
        },
        "D_bytes": len(d_archive),
        "D_predictor": d_meta["predictor"],
        "controls": controls,
        "baseline_name": baseline_name,
        "baseline_bytes": baseline_bytes,
        "md_vs_baseline": round(md_best_bytes / baseline_bytes, 6),
        "saving_vs_baseline": round(1.0 - md_best_bytes / baseline_bytes, 6),
        "encode_s": round(encode_s, 5),
        "decode_s": round(decode_s, 5),
        "raw_decode_s": round(raw_decode_s, 5),
        "decoded_ok": True,
        "decoded_sha256": sha256(decoded),
        "raw_decoded_ok": True,
        "raw_decoded_sha256": sha256(raw_decoded),
        "exact_decoded_ok": exact_decoded_ok,
        "E_decoded_ok": True,
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
        for size in available:
            key = str(size)
            if key not in selected.get(name, {}):
                raise ValueError(f"missing frozen selection for {name} {size}")
            config = selected[name][key]
            if config is None:
                continue
            region = data[-size:]
            file_record["regions"][key] = validate_region(
                region, size, len(data) - size, config
            )
        files.append(file_record)
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
        md = sum(region["md_best_bytes"] for region in regions)
        base = sum(region["baseline_bytes"] for region in regions)
        nontrivial = any(region["nontrivial_multidim"] for region in regions)
        rows.append(
            {
                "name": file_record["name"],
                "sizes": [region["length"] for region in regions],
                "md_bytes": md,
                "baseline": base,
                "saving_vs_baseline": round(1.0 - md / base, 6),
                "primary_pass": nontrivial and (1.0 - md / base) >= 0.01,
                "nontrivial": nontrivial,
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


def probe(name: str, size: int) -> None:
    path = next(ROOT / relative for key, relative, _kind in FILES if key == name)
    data = path.read_bytes()[:size]
    if len(data) < size:
        print(name, size, "unavailable")
        return
    for shape_name, shape in SHAPES:
        for neighborhood, shifts in neighborhoods(len(shape)):
            for affine in (False, True):
                if len(shifts) + (1 if affine else 0) > 16:
                    continue
                started = time.perf_counter()
                model = fit_model(data, shape, 0, shifts, (), affine)
                model["shape_name"] = shape_name
                exact = serialize_model(data, model, 0)
                raw = serialize_model(data, model, 1)
                zres = serialize_model(data, model, 2)
                elapsed = time.perf_counter() - started
                print(
                    f"{name} {size} {shape_name} {neighborhood:9} affine={affine} "
                    f"rank={model['rank']} null={model['nullity']} cov={model['coverage']:.3f} "
                    f"bd={model['boundary_count']} exact={len(exact[0]) if exact else '-'} "
                    f"raw={len(raw[0])} z={len(zres[0])} nontriv={model['nontrivial_multidim']} t={elapsed:.3f}"
                )


def protocol_dict() -> dict:
    return {
        "phase": 17,
        "episode": 3,
        "codec": "bounded multidimensional recurrence v1.0",
        "field": "GF(2^8), polynomial 0x11B",
        "shapes": [{"name": name, "dims": list(shape)} for name, shape in SHAPES],
        "sizes": list(SIZES),
        "neighborhoods": ["axes", "diagonal", "diag2", "axes2"],
        "orders": ["raster"],
        "coeff_limit": 16,
        "affine": "fitted with and without an affine constant",
        "region_rule": "first and last disjoint 4 KiB regions; no padding",
        "selection": (
            "best nondegenerate multidimensional candidate by total serialized size "
            "on dev; fall back to best any candidate only for reporting"
        ),
        "representations": [
            "exact recurrence only (valid only at 100% coverage)",
            "recurrence + raw XOR residuals",
            "recurrence + zstd-9 residuals",
        ],
        "controls": {
            "A": "zstd-9 raw",
            "B": "zstd-19 raw",
            "C": "raw LZMA2 preset 6 +1",
            "D": "best delta/XOR/spatial predictor + zstd-9",
            "E": "1D recurrence with the same boundary mask and flattened lags",
            "F": "multidimensional recurrence representation",
            "G": "multidimensional recurrence + compressed residuals",
        },
        "gate": {
            "min_saving": 0.01,
            "min_files": 2,
            "baseline": "min(A,B,C,D,E_best) per region",
            "nontrivial_required": True,
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf8")


def print_dev(payload: dict) -> None:
    print(f"{'file':8} {'size':>6} {'shape':5} {'neighbor':9} {'aff':>4} {'rank':>4} {'null':>4} {'cover':>7} {'bd':>5} {'MD':>7} {'E':>7} {'nontriv':>7}")
    for file_record in payload["files"]:
        for size_key, region in file_record["regions"].items():
            selected = region["selected"]
            if selected is None:
                print(file_record["name"], size_key, "no candidate")
                continue
            print(
                f"{file_record['name']:8} {int(size_key):6d} {selected['shape_name']:5} {selected['neighborhood']:9} "
                f"{str(selected['affine']):>4} {selected['rank']:4d} {selected['nullity']:4d} "
                f"{selected['coverage']:7.3f} {selected['boundary_count']:5d} "
                f"{selected['md_best']['bytes']:7d} {selected['e_best']['bytes']:7d} "
                f"{str(selected['nontrivial_multidim']):>7}"
            )
    nontrivial = sum(
        1 for f in payload["files"] for r in f["regions"].values()
        if r["selected"] and r["selected"]["nontrivial_multidim"]
    )
    exact = sum(
        1 for f in payload["files"] for r in f["regions"].values()
        if r["selected"] and r["selected"]["md_variants"]["exact"] is not None
    )
    print(f"dev elapsed {payload['elapsed_s']} s; nontrivial selections {nontrivial}; exact {exact}")


def print_val(payload: dict) -> None:
    print(
        f"{'file':8} {'size':>6} {'shape':5} {'neighbor':9} {'aff':>4} {'rank':>4} {'cover':>7} "
        f"{'exact':>7} {'raw':>7} {'zstd':>7} {'E':>7} {'base':>7} {'md/base':>7} {'nontriv':>7}"
    )
    for file_record in payload["validation"]["files"]:
        for size_key, region in file_record["regions"].items():
            print(
                f"{file_record['name']:8} {int(size_key):6d} {region['shape_name']:5} {region['neighborhood']:9} "
                f"{str(region['affine']):>4} {region['rank']:4d} {region['coverage']:7.3f} "
                f"{str(region['exact_bytes']):>7} {region['raw_bytes']:7d} {region['zstd_bytes']:7d} "
                f"{region['E_best_bytes']:7d} {region['baseline_bytes']:7d} {region['md_vs_baseline']:7.3f} "
                f"{str(region['nontrivial_multidim']):>7}"
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
            "episode": 3,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        out = Path(args.out) if args.out else RESULTS / "phase17c-dev.json"
        write_json(out, payload)
        print_dev(payload)
    elif args.split == "val":
        dev = json.loads((RESULTS / "phase17c-dev.json").read_text(encoding="utf8"))
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 17,
            "episode": 3,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase17c.json"
        write_json(out, payload)
        print_val(payload)
    else:
        dev = run_dev(only=args.file)
        dev_payload = {
            "phase": 17,
            "episode": 3,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        write_json(RESULTS / "phase17c-dev.json", dev_payload)
        print_dev(dev_payload)
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 17,
            "episode": 3,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase17c.json"
        write_json(out, payload)
        print_val(payload)


if __name__ == "__main__":
    main()
