#!/usr/bin/env python3
"""Phase 18 Episode 1: exact spectral representations.

Transforms: integer FWHT (C = H x, inverse x = H C / N with exact
divisibility), reversible integer Haar lifting, and identity.  No
floating-point arithmetic, thresholding or coefficient deletion is used.
Serialization options: signed zigzag varints, biased fixed-width packing, and
sparse nonzero indices with delta positions.  Every archive is decoded from
its serialized bytes alone.
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
import run_phase17 as ep1  # noqa: E402  (GF utilities, zstd/lzma controls, files)

RESULTS = ROOT / "lab/sxz-spectral/results"
MAGIC = b"SXZ18S1"
MAGIC_E = b"SXZ18C1"
Z9 = ep1.Z9
Z19 = ep1.Z19
LZMA_FILTERS = ep1.LZMA_FILTERS
FILES = ep1.FILES

BLOCKS = (64, 256, 1024, 4096)
TRANSFORMS = ("identity", "fwht", "haar")
REPRS = ("bytes", "bitplanes")
ENCODINGS = ("varint", "fixed", "sparse")
SIZES = (4096,)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def uvarint(value: int) -> bytes:
    return ep1.uvarint(value)


def read_uvarint(buf: bytes, pos: int) -> tuple[int, int]:
    return ep1.read_uvarint(buf, pos)


def zigzag(value: int) -> int:
    return value * 2 if value >= 0 else -value * 2 - 1


def unzigzag(value: int) -> int:
    return value // 2 if value % 2 == 0 else -(value // 2) - 1


# ---------------------------------------------------------------------------
# exact transforms


def fwht(values: list[int]) -> list[int]:
    arr = list(values)
    n = len(arr)
    step = 1
    while step < n:
        jump = step * 2
        for start in range(0, n, jump):
            for index in range(start, start + step):
                a = arr[index]
                b = arr[index + step]
                arr[index] = a + b
                arr[index + step] = a - b
        step = jump
    return arr


def ifwht(coeffs: list[int]) -> list[int]:
    arr = fwht(coeffs)
    n = len(arr)
    out = []
    for value in arr:
        quotient, remainder = divmod(value, n)
        if remainder:
            raise ValueError("FWHT coefficients are not exactly divisible")
        out.append(quotient)
    return out


def haar_forward(values: list[int]) -> list[int]:
    """Standard recursive Haar lifting: decompose approximation only."""
    arr = list(values)
    current = len(arr)
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


def haar_inverse(coeffs: list[int]) -> list[int]:
    """Inverse of the approximation-only recursive Haar lifting."""
    arr = list(coeffs)
    current = 2
    while current <= len(arr):
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


def transform(values: list[int], transform_id: int) -> list[int]:
    if transform_id == 0:
        return list(values)
    if transform_id == 1:
        return fwht(values)
    if transform_id == 2:
        return haar_forward(values)
    raise ValueError("bad transform id")


def inverse_transform(coeffs: list[int], transform_id: int) -> list[int]:
    if transform_id == 0:
        return list(coeffs)
    if transform_id == 1:
        return ifwht(coeffs)
    if transform_id == 2:
        return haar_inverse(coeffs)
    raise ValueError("bad transform id")


# ---------------------------------------------------------------------------
# stream encodings


def pack_unsigned(values: list[int], width: int) -> bytes:
    if width == 0:
        return b""
    out = bytearray()
    buffer = 0
    bits = 0
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


def unpack_unsigned(data: bytes, count: int, width: int) -> list[int]:
    if width == 0:
        return [0] * count
    total_bits = count * width
    if len(data) * 8 < total_bits:
        raise ValueError("truncated fixed-width stream")
    buffer = int.from_bytes(data, "big")
    values = []
    for index in range(count):
        shift = total_bits - (index + 1) * width
        values.append((buffer >> shift) & ((1 << width) - 1))
    return values


def encode_stream(values: list[int], encoding: int) -> tuple[bytes, dict]:
    nonzero = sum(1 for value in values if value)
    max_abs = max((abs(value) for value in values), default=0)
    distinct = len(set(values))
    counter = Counter(values)
    top = counter.most_common(3)
    if encoding == 0:
        payload = b"".join(uvarint(zigzag(value)) for value in values)
        return payload, {
            "coefficient_bytes": len(payload),
            "index_bytes": 0,
            "nonzero": nonzero,
            "max_abs": max_abs,
            "distinct": distinct,
            "top": top,
        }
    if encoding == 1:
        minimum = min(values) if values else 0
        maximum = max(values) if values else 0
        width = (maximum - minimum).bit_length()
        packed = pack_unsigned([value - minimum for value in values], width)
        header = uvarint(zigzag(minimum)) + uvarint(width)
        payload = header + packed
        return payload, {
            "coefficient_bytes": len(payload),
            "index_bytes": 0,
            "nonzero": nonzero,
            "max_abs": max_abs,
            "distinct": distinct,
            "top": top,
        }
    if encoding == 2:
        output = bytearray()
        sparse = [(index, value) for index, value in enumerate(values) if value]
        count_bytes = uvarint(len(sparse))
        output += count_bytes
        index_bytes = len(count_bytes)
        coefficient_bytes = 0
        previous = 0
        for index, value in sparse:
            delta = uvarint(index - previous)
            coefficient = uvarint(zigzag(value))
            output += delta
            output += coefficient
            index_bytes += len(delta)
            coefficient_bytes += len(coefficient)
            previous = index
        return bytes(output), {
            "coefficient_bytes": coefficient_bytes,
            "index_bytes": index_bytes,
            "nonzero": nonzero,
            "max_abs": max_abs,
            "distinct": distinct,
            "top": top,
        }
    raise ValueError("bad encoding")


def decode_stream(data: bytes, pos: int, count: int, encoding: int) -> tuple[list[int], int, dict]:
    if encoding == 0:
        values = []
        for _ in range(count):
            value, pos = read_uvarint(data, pos)
            values.append(unzigzag(value))
        return values, pos, {"payload_bytes": pos}
    if encoding == 1:
        minimum_code, pos = read_uvarint(data, pos)
        minimum = unzigzag(minimum_code)
        width, pos = read_uvarint(data, pos)
        byte_count = (count * width + 7) // 8
        packed = data[pos : pos + byte_count]
        pos += byte_count
        values = [value + minimum for value in unpack_unsigned(packed, count, width)]
        return values, pos, {"payload_bytes": byte_count + len(uvarint(minimum_code)) + len(uvarint(width))}
    if encoding == 2:
        nonzero, pos = read_uvarint(data, pos)
        values = [0] * count
        previous = 0
        for _ in range(nonzero):
            delta, pos = read_uvarint(data, pos)
            index = previous + delta
            coefficient, pos = read_uvarint(data, pos)
            values[index] = unzigzag(coefficient)
            previous = index
        return values, pos, {"payload_bytes": 0}
    raise ValueError("bad encoding")


# ---------------------------------------------------------------------------
# archive


def build_archive(
    data: bytes,
    transform_id: int,
    representation_id: int,
    block_length: int,
    encoding: int,
) -> tuple[bytes, dict]:
    total = len(data)
    if total % block_length:
        raise ValueError("block length does not divide region")
    block_count = total // block_length
    header = bytearray(MAGIC)
    header.append(transform_id)
    header.append(representation_id)
    header += uvarint(block_length)
    header += uvarint(total)
    header.append(encoding)
    header += uvarint(block_count)
    payload = bytearray()
    stats = {
        "total_coefficients": 0,
        "nonzero": 0,
        "max_abs": 0,
        "coefficient_bytes": 0,
        "index_bytes": 0,
        "top": Counter(),
        "distinct_values": set(),
    }
    streams_per_block = 1 if representation_id == 0 else 8
    for block_index in range(block_count):
        block = data[block_index * block_length : (block_index + 1) * block_length]
        for stream_index in range(streams_per_block):
            if representation_id == 0:
                values = list(block)
            else:
                values = [(value >> stream_index) & 1 for value in block]
            coeffs = transform(values, transform_id)
            encoded, meta = encode_stream(coeffs, encoding)
            payload += encoded
            stats["total_coefficients"] += len(coeffs)
            stats["nonzero"] += meta["nonzero"]
            stats["max_abs"] = max(stats["max_abs"], meta["max_abs"])
            stats["coefficient_bytes"] += meta["coefficient_bytes"]
            stats["index_bytes"] += meta["index_bytes"]
            stats["distinct_values"].update(coeffs)
            stats["top"].update(coeffs)
    archive = bytes(header) + bytes(payload)
    meta = {
        "transform": TRANSFORMS[transform_id],
        "transform_id": transform_id,
        "representation": REPRS[representation_id],
        "representation_id": representation_id,
        "block_length": block_length,
        "block_count": block_count,
        "encoding": ENCODINGS[encoding],
        "encoding_id": encoding,
        "header_bytes": len(header),
        "coefficient_bytes": stats["coefficient_bytes"],
        "index_bytes": stats["index_bytes"],
        "payload_bytes": len(payload),
        "exact_bytes": len(archive),
        "compressed_bytes": len(Z9.compress(archive)),
        "total_coefficients": stats["total_coefficients"],
        "nonzero": stats["nonzero"],
        "nonzero_fraction": stats["nonzero"] / stats["total_coefficients"],
        "max_abs": stats["max_abs"],
        "distinct_values": len(stats["distinct_values"]),
        "top_coefficients": stats["top"].most_common(5),
    }
    return archive, meta


def decode_archive(archive: bytes) -> tuple[bytes, dict]:
    if archive[: len(MAGIC)] != MAGIC:
        raise ValueError("bad spectral magic")
    pos = len(MAGIC)
    transform_id = archive[pos]
    pos += 1
    representation_id = archive[pos]
    pos += 1
    block_length, pos = read_uvarint(archive, pos)
    total, pos = read_uvarint(archive, pos)
    encoding = archive[pos]
    pos += 1
    block_count, pos = read_uvarint(archive, pos)
    if block_count * block_length != total:
        raise ValueError("bad block geometry")
    out = bytearray(total)
    streams_per_block = 1 if representation_id == 0 else 8
    for block_index in range(block_count):
        block = bytearray(block_length)
        for stream_index in range(streams_per_block):
            coeffs, pos, _meta = decode_stream(archive, pos, block_length, encoding)
            values = inverse_transform(coeffs, transform_id)
            if representation_id == 0:
                if any(value < 0 or value > 255 for value in values):
                    raise ValueError("byte range violation")
                block[:] = bytes(values)
            else:
                for index, value in enumerate(values):
                    if value not in (0, 1):
                        raise ValueError("bit-plane range violation")
                    block[index] |= value << stream_index
        offset = block_index * block_length
        out[offset : offset + block_length] = block
    if pos != len(archive):
        raise ValueError("trailing spectral bytes")
    return bytes(out), {
        "transform_id": transform_id,
        "representation_id": representation_id,
        "block_length": block_length,
        "encoding": encoding,
    }


# ---------------------------------------------------------------------------
# conventional controls


def xor_prev_encode(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    out[0] = data[0]
    for index in range(1, len(data)):
        out[index] = data[index] ^ data[index - 1]
    return bytes(out)


def xor_prev_decode(data: bytes) -> bytes:
    if not data:
        return b""
    out = bytearray(len(data))
    out[0] = data[0]
    for index in range(1, len(data)):
        out[index] = data[index] ^ out[index - 1]
    return bytes(out)


def build_e(data: bytes) -> tuple[bytes, dict]:
    candidates = []
    for family_id, family in enumerate(("delta", "xor-prev", "shuffle3", "global-add", "global-xor")):
        trailing = b""
        param = 0
        if family == "delta":
            body = ep1.delta_encode(data)
        elif family == "xor-prev":
            body = xor_prev_encode(data)
        elif family == "shuffle3":
            body, trailing = ep1.shuffle_encode(data, 3)
        elif family == "global-add":
            param = ep1.choose_global(data, "add")
            body = ep1.global_apply(data, param, "add")
        else:
            param = ep1.choose_global(data, "xor")
            body = ep1.global_apply(data, param, "xor")
        payload = Z9.compress(body)
        header = bytearray(MAGIC_E)
        header.append(family_id)
        header.append(param)
        header += uvarint(len(data))
        header += uvarint(len(trailing))
        header += trailing
        archive = bytes(header) + payload
        candidates.append((len(archive), family_id, archive, family, param, len(trailing)))
    candidates.sort(key=lambda item: (item[0], item[1]))
    size, family_id, archive, family, param, trailing = candidates[0]
    return archive, {
        "predictor": family,
        "family_id": family_id,
        "param": param,
        "trailing_bytes": trailing,
        "exact_bytes": size,
    }


def decode_e(archive: bytes) -> bytes:
    if archive[: len(MAGIC_E)] != MAGIC_E:
        raise ValueError("bad E magic")
    pos = len(MAGIC_E)
    family_id = archive[pos]
    param = archive[pos + 1]
    pos += 2
    total, pos = read_uvarint(archive, pos)
    trailing_len, pos = read_uvarint(archive, pos)
    trailing = archive[pos : pos + trailing_len]
    pos += trailing_len
    body = zstd.ZstdDecompressor().decompress(archive[pos:])
    if family_id == 0:
        output = ep1.delta_decode(body)
    elif family_id == 1:
        output = xor_prev_decode(body)
    elif family_id == 2:
        output = ep1.shuffle_decode(body, trailing, 3)
    elif family_id == 3:
        output = ep1.global_apply(body, (-param) & 255, "add")
    elif family_id == 4:
        output = ep1.global_apply(body, param, "xor")
    else:
        raise ValueError("bad E family")
    if family_id != 2:
        output += trailing
    if len(output) != total:
        raise ValueError("bad E output length")
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
    # FWHT exact inverse, including values that produce negative coefficients
    for values in ([0, 1, 2, 3, 4, 5, 6, 7], [255, 0, 17, 200, 3, 9, 44, 1]):
        coeffs = fwht(values)
        if ifwht(coeffs) != values:
            raise AssertionError("FWHT inverse")
    # Haar lifting exact inverse and standard coefficient range invariants
    for values in ([0, 1, 2, 3, 4, 5, 6, 7], [255, 0, 17, 200, 3, 9, 44, 1]):
        coeffs = haar_forward(values)
        if haar_inverse(coeffs) != values:
            raise AssertionError("Haar inverse")
        if max(abs(value) for value in coeffs) > 255 or len(set(coeffs)) > 511:
            raise AssertionError("Haar coefficient range")
    probe_values = [(index * 37 + 11) & 255 for index in range(4096)]
    probe_coeffs = haar_forward(probe_values)
    if haar_inverse(probe_coeffs) != probe_values:
        raise AssertionError("large Haar inverse")
    if max(abs(value) for value in probe_coeffs) > 255 or len(set(probe_coeffs)) > 511:
        raise AssertionError("large Haar coefficient range")
    data = bytes((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15)) * 4
    for transform_id in range(3):
        for representation_id in range(2):
            for block_length in (16, 64):
                if len(data) % block_length:
                    continue
                for encoding in range(3):
                    archive, meta = build_archive(
                        data, transform_id, representation_id, block_length, encoding
                    )
                    decoded, _decoded_meta = decode_archive(archive)
                    if decoded != data:
                        raise AssertionError(
                            (transform_id, representation_id, block_length, encoding)
                        )
    print("selftest: FWHT, Haar, encodings, archive decode: ok")


def is_periodic(values: list[int], maximum: int) -> tuple[bool, int]:
    total = len(values)
    for period in (1, 2, 4, 8, 16, 32):
        if period > maximum or total % period:
            continue
        if all(values[index] == values[index % period] for index in range(total)):
            return True, period
    return False, 0


def representative_segment(
    data: bytes,
    transform_id: int,
    representation_id: int,
    block_length: int,
) -> dict | None:
    best_nontrivial = None
    best_trivial = None
    streams = 1 if representation_id == 0 else 8
    for block_index in range(len(data) // block_length):
        block = data[block_index * block_length : (block_index + 1) * block_length]
        for stream in range(streams):
            if representation_id == 0:
                values = list(block)
            else:
                values = [(value >> stream) & 1 for value in block]
            coeffs = transform(values, transform_id)
            if inverse_transform(coeffs, transform_id) != values:
                raise RuntimeError("representative transform not reversible")
            nonzero = sum(1 for value in coeffs if value)
            periodic, period = is_periodic(values, block_length // 4)
            constant = len(set(values)) == 1
            nonzero_values = Counter(value for value in coeffs if value)
            record = {
                "block_index": block_index,
                "offset": block_index * block_length,
                "plane": None if representation_id == 0 else stream,
                "block_length": block_length,
                "nonzero": nonzero,
                "total": block_length,
                "nonzero_fraction": nonzero / block_length,
                "max_abs": max((abs(value) for value in coeffs), default=0),
                "distinct_nonzero": len(nonzero_values),
                "top_nonzero": nonzero_values.most_common(3),
                "constant": constant,
                "periodic": periodic,
                "period": period,
            }
            target = best_trivial if (constant or periodic) else best_nontrivial
            if target is None or record["nonzero_fraction"] < target["nonzero_fraction"]:
                if constant or periodic:
                    best_trivial = record
                else:
                    best_nontrivial = record
    return best_nontrivial or best_trivial


def build_identity_best(data: bytes, representation_id: int, block_length: int) -> tuple[bytes, bytes, dict, int]:
    candidates = []
    for encoding in range(3):
        archive, meta = build_archive(data, 0, representation_id, block_length, encoding)
        candidates.append((meta["compressed_bytes"], archive, meta, encoding))
    candidates.sort(key=lambda item: (item[0], item[3]))
    _size, archive, meta, encoding = candidates[0]
    return archive, Z9.compress(archive), meta, encoding


def dev_search_region(data: bytes, size: int) -> dict:
    rows = []
    for transform_id in (1, 2):
        for representation_id in range(2):
            for block_length in BLOCKS:
                if size % block_length:
                    continue
                for encoding in range(3):
                    archive, meta = build_archive(
                        data, transform_id, representation_id, block_length, encoding
                    )
                    rows.append(
                        {
                            "transform": TRANSFORMS[transform_id],
                            "transform_id": transform_id,
                            "representation": REPRS[representation_id],
                            "representation_id": representation_id,
                            "block_length": block_length,
                            "encoding": ENCODINGS[encoding],
                            "encoding_id": encoding,
                            "F_bytes": len(archive),
                            "G_bytes": meta["compressed_bytes"],
                            "nonzero": meta["nonzero"],
                            "nonzero_fraction": round(meta["nonzero_fraction"], 6),
                            "max_abs": meta["max_abs"],
                            "distinct_values": meta["distinct_values"],
                            "coefficient_bytes": meta["coefficient_bytes"],
                            "index_bytes": meta["index_bytes"],
                            "header_bytes": meta["header_bytes"],
                        }
                    )
    best_g = min(
        rows,
        key=lambda row: (row["G_bytes"], row["F_bytes"], row["transform_id"], row["representation_id"], row["block_length"], row["encoding_id"]),
    )
    best_f = min(
        rows,
        key=lambda row: (row["F_bytes"], row["G_bytes"], row["transform_id"], row["representation_id"], row["block_length"], row["encoding_id"]),
    )
    archive, meta = build_archive(
        data,
        best_g["transform_id"],
        best_g["representation_id"],
        best_g["block_length"],
        best_g["encoding_id"],
    )
    if decode_archive(archive)[0] != data:
        raise RuntimeError("selected spectral configuration failed reconstruction")
    return {"size": size, "rows": rows, "best_g": best_g, "best_f": best_f, "selected_exact": True}


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
        best = result["best_g"]
        selected[str(size)] = {
            "transform": best["transform"],
            "transform_id": best["transform_id"],
            "representation": best["representation"],
            "representation_id": best["representation_id"],
            "block_length": best["block_length"],
            "encoding": best["encoding"],
            "encoding_id": best["encoding_id"],
            "dev_F_bytes": best["F_bytes"],
            "dev_G_bytes": best["G_bytes"],
            "dev_nonzero_fraction": best["nonzero_fraction"],
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


def validate_region(data: bytes, size: int, offset: int, config: dict) -> dict:
    transform_id = config["transform_id"]
    representation_id = config["representation_id"]
    block_length = config["block_length"]
    encoding_id = config["encoding_id"]
    started = time.perf_counter()
    archive, meta = build_archive(
        data, transform_id, representation_id, block_length, encoding_id
    )
    encode_s = time.perf_counter() - started
    started = time.perf_counter()
    compressed = Z9.compress(archive)
    compress_s = time.perf_counter() - started
    started = time.perf_counter()
    decoded, _decoded_meta = decode_archive(archive)
    decode_s = time.perf_counter() - started
    if decoded != data:
        raise RuntimeError("spectral representation failed exact reconstruction")
    started = time.perf_counter()
    decoded_g, _decoded_g_meta = decode_archive(
        zstd.ZstdDecompressor().decompress(compressed)
    )
    decode_g_s = time.perf_counter() - started
    if decoded_g != data:
        raise RuntimeError("compressed spectral representation failed reconstruction")

    d_f_archive, d_archive, d_meta, d_encoding = build_identity_best(
        data, representation_id, block_length
    )
    d_decoded = decode_archive(zstd.ZstdDecompressor().decompress(d_archive))[0]
    if d_decoded != data:
        raise RuntimeError("identity block control failed reconstruction")
    e_archive, e_meta = build_e(data)
    e_decoded = decode_e(e_archive)
    if e_decoded != data:
        raise RuntimeError("conventional control failed reconstruction")
    controls = run_controls(data)
    baseline_name, baseline_bytes = min(
        (
            ("A_zstd9", controls["A_zstd9"]["size_bytes"]),
            ("B_zstd19", controls["B_zstd19"]["size_bytes"]),
            ("C_lzma2", controls["C_lzma2"]["size_bytes"]),
            ("D", len(d_archive)),
            ("E", len(e_archive)),
        ),
        key=lambda item: (item[1], item[0]),
    )
    representative = representative_segment(
        data, transform_id, representation_id, block_length
    )
    return {
        "split": "val",
        "offset": offset,
        "length": size,
        "sha256": sha256(data),
        "transform": meta["transform"],
        "transform_id": transform_id,
        "representation": meta["representation"],
        "representation_id": representation_id,
        "block_length": block_length,
        "encoding": meta["encoding"],
        "encoding_id": encoding_id,
        "block_count": meta["block_count"],
        "F_bytes": len(archive),
        "G_bytes": len(compressed),
        "D_bytes": len(d_archive),
        "D_F_bytes": len(d_f_archive),
        "D_encoding": ENCODINGS[d_encoding],
        "E_bytes": len(e_archive),
        "E_predictor": e_meta["predictor"],
        "controls": controls,
        "baseline_name": baseline_name,
        "baseline_bytes": baseline_bytes,
        "G_vs_baseline": round(len(compressed) / baseline_bytes, 6),
        "saving_vs_baseline": round(1.0 - len(compressed) / baseline_bytes, 6),
        "F_vs_original": round(len(archive) / size, 6),
        "G_vs_original": round(len(compressed) / size, 6),
        "nonzero": meta["nonzero"],
        "total_coefficients": meta["total_coefficients"],
        "nonzero_fraction": round(meta["nonzero_fraction"], 6),
        "max_abs": meta["max_abs"],
        "distinct_values": meta["distinct_values"],
        "coefficient_bytes": meta["coefficient_bytes"],
        "index_bytes": meta["index_bytes"],
        "header_bytes": meta["header_bytes"],
        "top_coefficients": meta["top_coefficients"],
        "representative": representative,
        "encode_s": round(encode_s, 5),
        "compress_s": round(compress_s, 5),
        "decode_s": round(decode_s, 5),
        "decode_g_s": round(decode_g_s, 5),
        "decoded_ok": True,
        "decoded_g_ok": True,
        "D_decoded_ok": True,
        "E_decoded_ok": True,
        "decoded_sha256": sha256(decoded),
        "decoded_g_sha256": sha256(decoded_g),
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
            config = selected.get(name, {}).get(key)
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
        total_g = sum(region["G_bytes"] for region in regions)
        total_f = sum(region["F_bytes"] for region in regions)
        total_base = sum(region["baseline_bytes"] for region in regions)
        total_n = sum(region["length"] for region in regions)
        total_coeff = sum(region["total_coefficients"] for region in regions)
        total_nonzero = sum(region["nonzero"] for region in regions)
        rows.append(
            {
                "name": file_record["name"],
                "sizes": [region["length"] for region in regions],
                "N": total_n,
                "F": total_f,
                "G": total_g,
                "baseline": total_base,
                "saving_vs_baseline": round(1.0 - total_g / total_base, 6),
                "primary_pass": (1.0 - total_g / total_base) >= 0.01,
                "nonzero_fraction": round(total_nonzero / total_coeff, 6),
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


def protocol_dict() -> dict:
    return {
        "phase": 18,
        "episode": 1,
        "codec": "exact integer spectral representation v1.0",
        "transforms": ["identity", "fwht", "haar"],
        "representations": ["bytes", "bitplanes"],
        "block_lengths": list(BLOCKS),
        "encodings": list(ENCODINGS),
        "sizes": list(SIZES),
        "region_rule": "first and last disjoint 4 KiB regions; no padding",
        "selection": "per file, smallest spectral G (archive + zstd-9) on dev; frozen before validation",
        "controls": {
            "A": "zstd-9 raw",
            "B": "zstd-19 raw",
            "C": "raw LZMA2 preset 6 +1",
            "D": "matched identity block/bit-plane representation + zstd-9",
            "E": "best delta/XOR/shuffle/global transform + zstd-9",
            "F": "exact spectral archive alone",
            "G": "spectral archive + zstd-9",
        },
        "gate": {
            "min_saving": 0.01,
            "min_files": 2,
            "baseline": "min(A,B,C,D,E) per region",
        },
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf8")


def print_dev(payload: dict) -> None:
    print(f"{'file':8} {'transform':6} {'repr':9} {'L':>5} {'enc':6} {'F':>7} {'G':>7} {'nz':>6}")
    for file_record in payload["files"]:
        for size_key, region in file_record["regions"].items():
            best = region["best_g"]
            print(
                f"{file_record['name']:8} {best['transform']:6} {best['representation']:9} "
                f"{best['block_length']:5d} {best['encoding']:6} {best['F_bytes']:7d} "
                f"{best['G_bytes']:7d} {best['nonzero_fraction']:6.3f}"
            )
    print(f"dev elapsed {payload['elapsed_s']} s")


def print_val(payload: dict) -> None:
    print(
        f"{'file':8} {'transform':6} {'repr':9} {'L':>5} {'enc':6} {'F':>7} {'G':>7} "
        f"{'D':>7} {'E':>7} {'A':>7} {'base':>7} {'G/base':>7} {'nz':>6}"
    )
    for file_record in payload["validation"]["files"]:
        for size_key, region in file_record["regions"].items():
            print(
                f"{file_record['name']:8} {region['transform']:6} {region['representation']:9} "
                f"{region['block_length']:5d} {region['encoding']:6} {region['F_bytes']:7d} "
                f"{region['G_bytes']:7d} {region['D_bytes']:7d} {region['E_bytes']:7d} "
                f"{region['controls']['A_zstd9']['size_bytes']:7d} {region['baseline_bytes']:7d} "
                f"{region['G_vs_baseline']:7.3f} {region['nonzero_fraction']:6.3f}"
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
            "phase": 18,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        out = Path(args.out) if args.out else RESULTS / "phase18-dev.json"
        write_json(out, payload)
        print_dev(payload)
    elif args.split == "val":
        dev = json.loads((RESULTS / "phase18-dev.json").read_text(encoding="utf8"))
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 18,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase18.json"
        write_json(out, payload)
        print_val(payload)
    else:
        dev = run_dev(only=args.file)
        dev_payload = {
            "phase": 18,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            **dev,
        }
        write_json(RESULTS / "phase18-dev.json", dev_payload)
        print_dev(dev_payload)
        val = run_val(dev, only=args.file)
        gate = compute_gate(val)
        payload = {
            "phase": 18,
            "episode": 1,
            "protocol": protocol_dict(),
            "unit_tests": "passed",
            "selected": dev["selected"],
            "dev_elapsed_s": dev["elapsed_s"],
            "validation": val,
            "gate": gate,
            "elapsed_s": round(time.perf_counter() - started, 3),
        }
        out = Path(args.out) if args.out else RESULTS / "phase18.json"
        write_json(out, payload)
        print_val(payload)


def probe(name: str, size: int) -> None:
    path = next(ROOT / relative for key, relative, _kind in FILES if key == name)
    data = path.read_bytes()[:size]
    if len(data) < size:
        print(name, size, "unavailable")
        return
    for transform_id in (1, 2):
        for representation_id in (0, 1):
            for block_length in BLOCKS:
                if size % block_length:
                    continue
                best = None
                for encoding in range(3):
                    archive, meta = build_archive(
                        data, transform_id, representation_id, block_length, encoding
                    )
                    if best is None or len(archive) < best[0]:
                        best = (len(archive), encoding, meta)
                print(
                    f"{name} {size} {TRANSFORMS[transform_id]:5} {REPRS[representation_id]:9} "
                    f"L={block_length:4} F={best[0]:7} G={best[2]['compressed_bytes']:7} "
                    f"enc={ENCODINGS[best[1]]:6} nz={best[2]['nonzero_fraction']:.3f}"
                )


if __name__ == "__main__":
    main()
