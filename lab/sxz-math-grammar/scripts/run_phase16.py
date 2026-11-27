#!/usr/bin/env python3
"""Phase 16 Episode 1: bounded deterministic grammar codec on real files.

Variants measured on two disjoint regions per input:
  D  ordinary bounded RePair grammar
  E  best ordinary byte transform (dev-selected family) + D
  F  D plus parameterized mathematical templates

Mathematical templates:
  add: S[i] = (T[i] + a) mod 256
  xor: S[i] =  T[i] XOR a
  sub: S[i] = (a - T[i]) mod 256

A template is a literal byte string in the dictionary.  Each invocation stores
its own one-byte parameter a.  Rules that reduce to an exact repeat (all params
zero) or a constant run (constant template) are rejected, so F cannot claim
ordinary repeats as mathematical gain.

All sizes are actual serialized archive bytes: header, dictionary records,
template blob, rule ids, invocation parameters, literal bytes and stream
framing.  Decoding starts from the serialized bytes alone.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import lzma
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import zstandard as zstd

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "lab/sxz-math-grammar/results"
MAGIC = b"SXZ16G1"
MAX_RULES = 128
MAX_MATH = 32
REGION_BYTES = 32768
WINDOW_LENGTHS = (8, 16, 32, 64, 128)
OPS = ("add", "xor", "sub")
KIND = {"add": 1, "xor": 2, "sub": 3}
KIND_OP = {value: key for key, value in KIND.items()}
FAMILIES = ("delta", "shuffle3", "global-add", "global-xor")
FAMILY_ID = {name: index for index, name in enumerate(FAMILIES)}
BUDGET_S = 180.0

# Frozen decision gate, evaluated only on the validation regions.
GATE = {
    "aggregate_vs_D_max_ratio": 0.98,
    "aggregate_vs_E_max_ratio": 0.99,
    "min_validation_regions_improved_vs_D": 4,
    "require_exact_reconstruction": True,
}

FILES = (
    ("book1", "datasets/corpus/book1"),
    ("bbc", "datasets/corpus/bbc.rss.xml"),
    ("7zr", "datasets/corpus/7zr.exe"),
    ("irs1040", "datasets/corpus/irs1040.pdf"),
    ("hopper", "datasets/corpus/hopper.bmp"),
    ("ecg", "datasets/corpus/ecg-holdout.bin"),
)

Z9 = zstd.ZstdCompressor(level=9)
Z19 = zstd.ZstdCompressor(level=19)
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6}]


# ---------------------------------------------------------------------------
# encoding primitives


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def uvarint(value: int) -> bytes:
    if value < 0:
        raise ValueError("uvarint requires a non-negative value")
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


def op_apply(template: bytes, param: int, op: str) -> bytes:
    if op == "add":
        return bytes((byte + param) & 255 for byte in template)
    if op == "xor":
        return bytes(byte ^ param for byte in template)
    if op == "sub":
        return bytes((param - byte) & 255 for byte in template)
    raise ValueError(f"unknown op {op}")


# ---------------------------------------------------------------------------
# mathematical template discovery


def discover_math(data: bytes, max_math: int) -> list[dict]:
    """Deterministic greedy selection with half-window strides.

    ADD and SUB share the additive signature; SUB is discovered with a negated
    template.  XOR uses its own signature.  Selection is by estimated serialized
    saving and intervals never overlap.
    """
    n = len(data)
    if n < WINDOW_LENGTHS[0] or max_math <= 0:
        return []

    candidates: list[tuple[int, int, str, list[int]]] = []
    for length in WINDOW_LENGTHS:
        if n < length:
            continue
        stride = max(1, length // 2)
        positions = range(0, n - length + 1, stride)
        add_buckets: dict[bytes, list[int]] = {}
        xor_buckets: dict[bytes, list[int]] = {}
        for pos in positions:
            first = data[pos]
            add_sig = bytes((data[pos + i] - first) & 255 for i in range(1, length))
            xor_sig = bytes(data[pos + i] ^ first for i in range(1, length))
            add_buckets.setdefault(add_sig, []).append(pos)
            xor_buckets.setdefault(xor_sig, []).append(pos)
        for op, buckets in (("add", add_buckets), ("sub", add_buckets), ("xor", xor_buckets)):
            for poss in buckets.values():
                if len(poss) < 2:
                    continue
                count = 0
                last = -1
                for pos in poss:
                    if pos >= last:
                        count += 1
                        last = pos + length
                if count < 2:
                    continue
                gain = count * (length - 2) - (length + 5)
                if gain > 0:
                    candidates.append((gain, length, op, poss))

    candidates.sort(key=lambda item: (-item[0], -item[1], OPS.index(item[2]), item[3][0]))
    claimed = bytearray(n)
    rules: list[dict] = []

    for _gain, length, op, poss in candidates:
        if len(rules) >= max_math:
            break
        free = [pos for pos in poss if claimed.find(b"\x01", pos, pos + length) < 0]
        if len(free) < 2:
            continue
        selected: list[int] = []
        last = -1
        for pos in free:
            if pos >= last:
                selected.append(pos)
                last = pos + length
        if len(selected) < 2:
            continue
        gain = len(selected) * (length - 2) - (length + 5)
        if gain <= 0:
            continue

        anchor = selected[0]
        if op == "sub":
            template = bytes((-data[anchor + i]) & 255 for i in range(length))
        else:
            template = data[anchor : anchor + length]
        if len(set(template)) < 2:
            continue  # constant run, not a parameterized template

        occurrences: list[tuple[int, int]] = []
        valid = True
        for pos in selected:
            if op == "add":
                param = (data[pos] - template[0]) & 255
            elif op == "xor":
                param = data[pos] ^ template[0]
            else:
                param = (data[pos] + template[0]) & 255
            if op_apply(template, param, op) != data[pos : pos + length]:
                valid = False
                break
            occurrences.append((pos, param))
        if not valid or len({param for _, param in occurrences}) < 2:
            continue  # exact repeat, not a parameterized occurrence set

        rule_index = len(rules)
        rules.append(
            {
                "op": op,
                "length": length,
                "template": template,
                "occurrences": occurrences,
                "gain_estimate": gain,
            }
        )
        for pos, _param in occurrences:
            claimed[pos : pos + length] = b"\x01" * length

    return rules


def build_symbols(data: bytes, math_rules: list[dict]) -> tuple[list[int], list[tuple[int, int]]]:
    n = len(data)
    claim = [-1] * n
    params = bytearray(n)
    for rule_index, rule in enumerate(math_rules):
        for pos, param in rule["occurrences"]:
            claim[pos] = rule_index
            params[pos] = param

    symbols: list[int] = []
    occurrences: list[tuple[int, int]] = []
    pos = 0
    while pos < n:
        rule_index = claim[pos]
        if rule_index >= 0:
            length = math_rules[rule_index]["length"]
            occurrences.append((rule_index, params[pos]))
            symbols.append(-len(occurrences))
            pos += length
        else:
            symbols.append(data[pos])
            pos += 1
    return symbols, occurrences


# ---------------------------------------------------------------------------
# ordinary bounded RePair grammar


def count_nonoverlap(symbols: list[int], left: int, right: int) -> int:
    count = 0
    pos = 0
    limit = len(symbols) - 1
    while pos < limit:
        if symbols[pos] == left and symbols[pos + 1] == right:
            count += 1
            pos += 2
        else:
            pos += 1
    return count


def build_pair_rules(symbols: list[int], max_new: int) -> tuple[list[tuple[int, int]], list[int]]:
    """Cost-aware RePair. Math symbols are negative barriers and are never paired.

    Pair keys are packed into one integer (symbols fit in 9 bits) and only the
    best eight candidates are kept, which keeps the 128-rule search bounded.
    """
    symbols = list(symbols)
    pair_rules: list[tuple[int, int]] = []
    pair_lengths: list[int] = []

    while len(pair_rules) < max_new:
        counts: dict[int, int] = {}
        previous = -1
        for symbol in symbols:
            if previous >= 0 and symbol >= 0:
                key = (previous << 9) | symbol
                counts[key] = counts.get(key, 0) + 1
            previous = symbol
        if not counts:
            break

        heap: list[tuple[int, int, int, int, int, int, int]] = []
        for key, frequency in counts.items():
            if frequency < 2:
                continue
            left = key >> 9
            right = key & 511
            left_length = 1 if left < 256 else pair_lengths[left - 256]
            right_length = 1 if right < 256 else pair_lengths[right - 256]
            expansion_length = left_length + right_length
            score = frequency * (expansion_length - 1)
            if score <= 5:
                continue
            item = (score, frequency, -left, -right, left, right, expansion_length)
            if len(heap) < 8:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
        if not heap:
            break

        chosen: tuple[int, int, int] | None = None
        for _score, _frequency, _nleft, _nright, left, right, expansion_length in sorted(
            heap, reverse=True
        ):
            occurrences = count_nonoverlap(symbols, left, right)
            if occurrences >= 2 and occurrences * (expansion_length - 1) - 5 > 0:
                chosen = (left, right, expansion_length)
                break
        if chosen is None:
            break

        left, right, expansion_length = chosen
        new_symbol = 256 + len(pair_rules)
        pair_rules.append((left, right))
        pair_lengths.append(expansion_length)

        output: list[int] = []
        pos = 0
        limit = len(symbols)
        while pos < limit:
            if pos + 1 < limit and symbols[pos] == left and symbols[pos + 1] == right:
                output.append(new_symbol)
                pos += 2
            else:
                output.append(symbols[pos])
                pos += 1
        symbols = output

    return pair_rules, symbols


# ---------------------------------------------------------------------------
# serialization


def encode_run_stream(tokens: list[tuple[int, int, int | None]], math_count: int) -> bytes:
    out = bytearray()
    pos = 0
    while pos < len(tokens):
        kind, value, param = tokens[pos]
        if kind == 0:
            end = pos + 1
            while end < len(tokens) and tokens[end][0] == 0:
                end += 1
            out.append(0)
            out += uvarint(end - pos)
            out += bytes(token[1] for token in tokens[pos:end])
            pos = end
        else:
            out.append(1 + value)
            if value < math_count:
                if param is None:
                    raise ValueError("missing math parameter")
                out.append(param)
            pos += 1
    return bytes(out)


def encode_bitmap_stream(tokens: list[tuple[int, int, int | None]], math_count: int) -> bytes:
    total = len(tokens)
    bitmap = bytearray((total + 7) // 8)
    payload = bytearray()
    for index, (kind, value, param) in enumerate(tokens):
        if kind == 1:
            bitmap[index >> 3] |= 1 << (index & 7)
            payload.append(value)
            if value < math_count:
                if param is None:
                    raise ValueError("missing math parameter")
                payload.append(param)
        else:
            payload.append(value)
    return uvarint(total) + bytes(bitmap) + bytes(payload)


def pair_expansions(pair_rules: list[tuple[int, int]]) -> list[bytes]:
    expansions: list[bytes] = []

    def child(code: int) -> bytes:
        if code < 256:
            return bytes((code,))
        index = code - 256
        if index >= len(expansions):
            raise ValueError("forward pair reference")
        return expansions[index]

    for left, right in pair_rules:
        expansions.append(child(left) + child(right))
    return expansions


def summarize_math(math_rules: list[dict], limit: int = 3) -> list[dict]:
    rows = []
    for rule in math_rules:
        occurrences = rule["occurrences"]
        params = sorted({param for _, param in occurrences})
        rows.append(
            {
                "op": rule["op"],
                "length": rule["length"],
                "occurrences": len(occurrences),
                "params_distinct": len(params),
                "params": params[:8],
                "covered_bytes": len(occurrences) * rule["length"],
                "template_hex": rule["template"][:8].hex(),
            }
        )
    rows.sort(key=lambda row: (-row["covered_bytes"], row["op"], row["length"]))
    return rows[:limit]


def summarize_pairs(
    pair_rules: list[tuple[int, int]], usage: Counter[int], math_count: int, limit: int = 3
) -> list[dict]:
    expansions = pair_expansions(pair_rules)
    rows = []
    for index, expansion in enumerate(expansions):
        refs = usage.get(math_count + index, 0)
        rows.append(
            {
                "length": len(expansion),
                "refs": refs,
                "preview_hex": expansion[:12].hex(),
            }
        )
    rows.sort(key=lambda row: (-(row["refs"] * row["length"]), -row["length"]))
    return rows[:limit]


def serialize_archive(
    orig_len: int,
    math_rules: list[dict],
    pair_rules: list[tuple[int, int]],
    symbols: list[int],
    occurrences: list[tuple[int, int]],
) -> tuple[bytes, dict]:
    math_count = len(math_rules)
    pair_count = len(pair_rules)

    template_pool = bytearray()
    template_offsets: dict[bytes, int] = {}
    for rule in math_rules:
        template = rule["template"]
        if template not in template_offsets:
            template_offsets[template] = len(template_pool)
            template_pool += template

    records = bytearray()
    for rule in math_rules:
        records.append(KIND[rule["op"]])
        records += uvarint(template_offsets[rule["template"]])
        records += uvarint(rule["length"])
    for left, right in pair_rules:
        records.append(0)
        records += uvarint(left)
        records += uvarint(right)

    archive = bytearray(MAGIC)
    archive += uvarint(orig_len)
    archive += uvarint(math_count + pair_count)
    archive += uvarint(math_count)
    archive += uvarint(len(template_pool))
    header_bytes = len(archive)
    archive += records
    archive += template_pool

    tokens: list[tuple[int, int, int | None]] = []
    for symbol in symbols:
        if symbol < 0:
            math_index, param = occurrences[-symbol - 1]
            tokens.append((1, math_index, param))
        elif symbol < 256:
            tokens.append((0, symbol, None))
        else:
            tokens.append((1, math_count + (symbol - 256), None))

    run_stream = b"\x00" + encode_run_stream(tokens, math_count)
    bitmap_stream = b"\x01" + encode_bitmap_stream(tokens, math_count)
    if len(run_stream) <= len(bitmap_stream):
        stream = run_stream
        mode = 0
    else:
        stream = bitmap_stream
        mode = 1
    stream_length_bytes = uvarint(len(stream))
    archive += stream_length_bytes
    archive += stream

    usage: Counter[int] = Counter()
    literal_tokens = 0
    math_refs = 0
    pair_refs = 0
    for kind, value, _param in tokens:
        if kind == 0:
            literal_tokens += 1
        else:
            usage[value] += 1
            if value < math_count:
                math_refs += 1
            else:
                pair_refs += 1

    pair_lengths: list[int] = []
    for left, right in pair_rules:
        left_length = 1 if left < 256 else pair_lengths[left - 256]
        right_length = 1 if right < 256 else pair_lengths[right - 256]
        pair_lengths.append(left_length + right_length)

    math_covered = sum(usage.get(index, 0) * math_rules[index]["length"] for index in range(math_count))
    pair_covered = sum(usage.get(math_count + index, 0) * length for index, length in enumerate(pair_lengths))
    params_distinct = len({param for rule in math_rules for _, param in rule["occurrences"]})
    math_ops: Counter[str] = Counter(rule["op"] for rule in math_rules)

    total_bytes = len(archive)
    meta = {
        "math_count": math_count,
        "pair_count": pair_count,
        "math_ops": dict(math_ops),
        "math_refs": math_refs,
        "pair_refs": pair_refs,
        "literal_tokens": literal_tokens,
        "math_covered_bytes": math_covered,
        "pair_covered_bytes": pair_covered,
        "params_distinct": params_distinct,
        "breakdown": {
            "total_bytes": total_bytes,
            "header_bytes": header_bytes + len(stream_length_bytes),
            "records_bytes": len(records),
            "template_bytes": len(template_pool),
            "stream_bytes": len(stream),
            "stream_mode": mode,
        },
        "_usage": usage,
    }
    return bytes(archive), meta


# ---------------------------------------------------------------------------
# archive decoder


def decode_archive(archive: bytes) -> bytes:
    if archive[: len(MAGIC)] != MAGIC:
        raise ValueError("bad magic")
    pos = len(MAGIC)
    orig_len, pos = read_uvarint(archive, pos)
    rule_count, pos = read_uvarint(archive, pos)
    math_count, pos = read_uvarint(archive, pos)
    blob_len, pos = read_uvarint(archive, pos)
    if rule_count > MAX_RULES or math_count > rule_count:
        raise ValueError("invalid rule counts")

    records = []
    for _ in range(rule_count):
        if pos >= len(archive):
            raise ValueError("truncated rule record")
        kind = archive[pos]
        pos += 1
        if kind == 0:
            left, pos = read_uvarint(archive, pos)
            right, pos = read_uvarint(archive, pos)
            records.append(("pair", left, right))
        elif kind in KIND_OP:
            offset, pos = read_uvarint(archive, pos)
            length, pos = read_uvarint(archive, pos)
            records.append(("math", kind, offset, length))
        else:
            raise ValueError("unknown rule kind")
    if any(record[0] != "math" for record in records[:math_count]):
        raise ValueError("math records must come first")
    if any(record[0] != "pair" for record in records[math_count:]):
        raise ValueError("pair records must come last")

    if pos + blob_len > len(archive):
        raise ValueError("truncated template blob")
    blob = archive[pos : pos + blob_len]
    pos += blob_len
    stream_len, pos = read_uvarint(archive, pos)
    if pos + stream_len != len(archive):
        raise ValueError("stream length mismatch")
    stream = archive[pos : pos + stream_len]

    expansions: list[bytes] = []

    def child(code: int) -> bytes:
        if code < 256:
            return bytes((code,))
        index = code - 256
        if index >= len(expansions):
            raise ValueError("forward pair reference")
        return expansions[index]

    for record in records[math_count:]:
        expansions.append(child(record[1]) + child(record[2]))

    math_cache: dict[tuple[int, int], bytes] = {}

    def math_bytes(index: int, param: int) -> bytes:
        key = (index, param)
        if key not in math_cache:
            kind, offset, length = records[index][1], records[index][2], records[index][3]
            if offset + length > len(blob):
                raise ValueError("template outside blob")
            math_cache[key] = op_apply(blob[offset : offset + length], param, KIND_OP[kind])
        return math_cache[key]

    if not stream:
        raise ValueError("empty stream")
    mode = stream[0]
    output = bytearray()
    if mode == 0:
        cursor = 1
        while cursor < len(stream):
            tag = stream[cursor]
            cursor += 1
            if tag == 0:
                run_length, cursor = read_uvarint(stream, cursor)
                if cursor + run_length > len(stream):
                    raise ValueError("truncated literal run")
                output += stream[cursor : cursor + run_length]
                cursor += run_length
            else:
                rule_index = tag - 1
                if rule_index >= rule_count:
                    raise ValueError("rule index out of range")
                if rule_index < math_count:
                    if cursor >= len(stream):
                        raise ValueError("missing math parameter")
                    param = stream[cursor]
                    cursor += 1
                    output += math_bytes(rule_index, param)
                else:
                    output += expansions[rule_index - math_count]
    elif mode == 1:
        total, cursor = read_uvarint(stream, 1)
        bitmap_len = (total + 7) // 8
        if cursor + bitmap_len > len(stream):
            raise ValueError("truncated bitmap")
        bitmap = stream[cursor : cursor + bitmap_len]
        cursor += bitmap_len
        for index in range(total):
            if bitmap[index >> 3] >> (index & 7) & 1:
                if cursor >= len(stream):
                    raise ValueError("truncated bitmap payload")
                rule_index = stream[cursor]
                cursor += 1
                if rule_index >= rule_count:
                    raise ValueError("rule index out of range")
                if rule_index < math_count:
                    if cursor >= len(stream):
                        raise ValueError("missing math parameter")
                    param = stream[cursor]
                    cursor += 1
                    output += math_bytes(rule_index, param)
                else:
                    output += expansions[rule_index - math_count]
            else:
                if cursor >= len(stream):
                    raise ValueError("truncated literal payload")
                output.append(stream[cursor])
                cursor += 1
        if cursor != len(stream):
            raise ValueError("bitmap stream trailing bytes")
    else:
        raise ValueError("unknown stream mode")

    if len(output) != orig_len:
        raise ValueError("decoded length mismatch")
    return bytes(output)


# ---------------------------------------------------------------------------
# ordinary grammar entry point


def grammar_encode(data: bytes, use_math: bool) -> tuple[bytes, dict]:
    math_rules = discover_math(data, MAX_MATH) if use_math else []
    symbols, occurrences = build_symbols(data, math_rules)
    pair_rules, symbols = build_pair_rules(symbols, MAX_RULES - len(math_rules))
    archive, meta = serialize_archive(len(data), math_rules, pair_rules, symbols, occurrences)

    usage = meta.pop("_usage")
    meta["top_math"] = summarize_math(math_rules) if use_math else []
    meta["top_pair"] = summarize_pairs(pair_rules, usage, len(math_rules))
    return archive, meta


# ---------------------------------------------------------------------------
# E controls: reversible transform + ordinary grammar


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
    if width <= 0:
        raise ValueError("bad width")
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


def e_transform(data: bytes, family: str) -> tuple[bytes, bytes, int]:
    if family == "delta":
        return delta_encode(data), b"", 0
    if family == "shuffle3":
        body, trailing = shuffle_encode(data, 3)
        return body, trailing, 0
    if family == "global-add":
        param = choose_global(data, "add")
        return global_apply(data, param, "add"), b"", param
    if family == "global-xor":
        param = choose_global(data, "xor")
        return global_apply(data, param, "xor"), b"", param
    raise ValueError(f"unknown family {family}")


def e_encode_body(body: bytes, trailing: bytes, param: int, family: str) -> tuple[bytes, dict]:
    base_archive, base_meta = grammar_encode(body, use_math=False)
    archive = (
        b"E1"
        + bytes((FAMILY_ID[family], param))
        + uvarint(len(trailing))
        + trailing
        + base_archive
    )
    return archive, {
        "family": family,
        "param": param,
        "trailing_bytes": len(trailing),
        "base": base_meta,
    }


def e_prepare(data: bytes) -> tuple[str, dict[str, tuple[int, bytes, bytes, int]]]:
    """Choose the E transform family with a cheap compressed-size proxy.

    The grammar is run only for the winning family. The family is frozen from
    the development region; its parameter is re-selected on each region.
    """
    candidates: dict[str, tuple[int, bytes, bytes, int]] = {}
    for family in FAMILIES:
        body, trailing, param = e_transform(data, family)
        proxy = len(Z9.compress(body))
        candidates[family] = (proxy, body, trailing, param)
    family = min(FAMILIES, key=lambda name: (candidates[name][0], FAMILY_ID[name]))
    return family, candidates


def e_encode(data: bytes, family: str) -> tuple[bytes, dict]:
    body, trailing, param = e_transform(data, family)
    return e_encode_body(body, trailing, param, family)


def e_decode(archive: bytes) -> bytes:
    if archive[:2] != b"E1":
        raise ValueError("bad E magic")
    family_id = archive[2]
    param = archive[3]
    pos = 4
    trailing_len, pos = read_uvarint(archive, pos)
    trailing = archive[pos : pos + trailing_len]
    pos += trailing_len
    body = decode_archive(archive[pos:])
    if family_id == FAMILY_ID["delta"]:
        output = delta_decode(body)
    elif family_id == FAMILY_ID["shuffle3"]:
        output = shuffle_decode(body, trailing, 3)
    elif family_id == FAMILY_ID["global-add"]:
        output = global_apply(body, (-param) & 255, "add")
    elif family_id == FAMILY_ID["global-xor"]:
        output = global_apply(body, param, "xor")
    else:
        raise ValueError("unknown E family id")
    if not family_id == FAMILY_ID["shuffle3"]:
        output += trailing
    return output


# ---------------------------------------------------------------------------
# controls


def lzma2_compress(data: bytes) -> bytes:
    return lzma.compress(data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)


def lzma2_decompress(data: bytes) -> bytes:
    return lzma.decompress(data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)


def run_controls(data: bytes) -> dict:
    out = {}
    cases = (
        ("A_zstd9", lambda value: Z9.compress(value), lambda value: zstd.ZstdDecompressor().decompress(value), 0),
        ("B_zstd19", lambda value: Z19.compress(value), lambda value: zstd.ZstdDecompressor().decompress(value), 0),
        ("C_lzma2", lzma2_compress, lzma2_decompress, 1),
    )
    for name, compressor, decompressor, extra in cases:
        start = time.perf_counter()
        blob = compressor(data)
        encoded = time.perf_counter() - start
        start = time.perf_counter()
        decoded = decompressor(blob)
        decoded_time = time.perf_counter() - start
        if decoded != data:
            raise RuntimeError(f"{name} control reconstruction failed")
        out[name] = {
            "size_bytes": len(blob) + extra,
            "encode_s": round(encoded, 4),
            "decode_s": round(decoded_time, 4),
            "decoded_ok": True,
        }
    return out


# ---------------------------------------------------------------------------
# region driver


def region_pair(data: bytes) -> tuple[bytes, bytes, int] | None:
    n = len(data)
    size = min(REGION_BYTES, n // 2)
    if size < 64:
        return None
    return data[:size], data[n - size :], size


def variant_record(archive: bytes, meta: dict, encoded_s: float, decoded: bytes) -> dict:
    return {
        "size_bytes": len(archive),
        "encode_s": round(encoded_s, 4),
        "decode_s": round(meta.pop("_decode_s", 0.0), 4),
        "decoded_ok": True,
        "decoded_sha256": sha256(decoded),
        "breakdown": meta["breakdown"],
        "rules": {"math": meta["math_count"], "pair": meta["pair_count"]},
        "math_ops": meta["math_ops"],
        "math_invocations": meta["math_refs"],
        "pair_invocations": meta["pair_refs"],
        "math_covered_bytes": meta["math_covered_bytes"],
        "pair_covered_bytes": meta["pair_covered_bytes"],
        "params_distinct": meta["params_distinct"],
        "top_math": meta["top_math"],
        "top_pair": meta["top_pair"],
    }


def run_region(data: bytes, offset: int, split: str, e_family: str | None) -> dict:
    record = {
        "split": split,
        "offset": offset,
        "length": len(data),
        "sha256": sha256(data),
        "controls": run_controls(data),
        "variants": {},
    }

    for name, use_math in (("D", False), ("F", True)):
        start = time.perf_counter()
        archive, meta = grammar_encode(data, use_math)
        encoded_s = time.perf_counter() - start
        start = time.perf_counter()
        decoded = decode_archive(archive)
        decoded_s = time.perf_counter() - start
        if decoded != data:
            raise RuntimeError(f"{name} reconstruction failed")
        meta["_decode_s"] = decoded_s
        record["variants"][name] = variant_record(archive, meta, encoded_s, decoded)

    if split == "dev":
        family, candidates = e_prepare(data)
        proxy, body, trailing, param = candidates[family]
        start = time.perf_counter()
        archive, meta = e_encode_body(body, trailing, param, family)
        encoded_s = time.perf_counter() - start
        record["e_candidates"] = {name: candidates[name][0] for name in FAMILIES}
        record["e_family_proxy"] = proxy
    else:
        if e_family not in FAMILIES:
            raise ValueError("missing frozen E family")
        family = e_family
        body, trailing, param = e_transform(data, family)
        start = time.perf_counter()
        archive, meta = e_encode_body(body, trailing, param, family)
        encoded_s = time.perf_counter() - start
        record["e_family_proxy"] = len(Z9.compress(body))

    start = time.perf_counter()
    decoded = e_decode(archive)
    decoded_s = time.perf_counter() - start
    if decoded != data:
        raise RuntimeError("E reconstruction failed")

    base = meta["base"]
    base.pop("_usage", None)
    record["e_family"] = family
    record["e_param"] = meta["param"]
    record["variants"]["E"] = {
        "size_bytes": len(archive),
        "encode_s": round(encoded_s, 4),
        "decode_s": round(decoded_s, 4),
        "decoded_ok": True,
        "decoded_sha256": sha256(decoded),
        "transform": family,
        "param": meta["param"],
        "trailing_bytes": meta["trailing_bytes"],
        "base_size_bytes": base["breakdown"]["total_bytes"],
        "breakdown": {
            **base["breakdown"],
            "wrapper_bytes": len(archive) - base["breakdown"]["total_bytes"],
        },
        "rules": {"math": base["math_count"], "pair": base["pair_count"]},
        "math_ops": base["math_ops"],
        "math_invocations": base["math_refs"],
        "pair_invocations": base["pair_refs"],
        "math_covered_bytes": base["math_covered_bytes"],
        "pair_covered_bytes": base["pair_covered_bytes"],
        "params_distinct": base["params_distinct"],
        "top_math": base["top_math"],
        "top_pair": base["top_pair"],
    }
    return record


# ---------------------------------------------------------------------------
# dataset and aggregation


def protocol_dict() -> dict:
    return {
        "phase": 16,
        "episode": 1,
        "codec": "bounded deterministic grammar v1.0",
        "region_bytes_cap": REGION_BYTES,
        "region_rule": "two disjoint equal regions; cap 32 KiB; smaller files use half-file regions",
        "max_rules": MAX_RULES,
        "max_math_rules": MAX_MATH,
        "window_lengths": list(WINDOW_LENGTHS),
        "window_stride": "length/2",
        "min_occurrences": 2,
        "math_param_filter": "template non-constant and at least two distinct parameters",
        "pair_policy": "cost-aware RePair, top-8 candidates, exact non-overlap check",
        "e_families": list(FAMILIES),
        "gate": GATE,
        "hard_budget_s": BUDGET_S,
    }


def read_file(name: str) -> tuple[Path, bytes]:
    for key, relative in FILES:
        if key == name:
            path = ROOT / relative
            return path, path.read_bytes()
    raise KeyError(name)


def run_task(task: tuple[str, str, str | None]) -> dict | None:
    name, split, family = task
    path, data = read_file(name)
    relative = next(relative for key, relative in FILES if key == name)
    pair = region_pair(data)
    if pair is None:
        return None
    dev_data, val_data, size = pair
    if split == "dev":
        region = dev_data
        offset = 0
    else:
        region = val_data
        offset = len(data) - size
        if family is None:
            raise ValueError(f"no frozen E family for {name}")
    record = run_region(region, offset, split, family)
    return {
        "name": name,
        "path": relative,
        "file_bytes": len(data),
        "file_sha256": sha256(data),
        "region_bytes": size,
        split: record,
    }


def run_split(split: str, families: dict[str, str] | None = None, only: str | None = None) -> list[dict]:
    tasks: list[tuple[str, str, str | None]] = []
    for name, _relative in FILES:
        if only and name != only:
            continue
        family = families.get(name) if split == "val" and families else None
        tasks.append((name, split, family))
    if not tasks:
        return []
    workers = min(len(tasks), max(1, (os.cpu_count() or 2) - 1), 6)
    if len(tasks) == 1 or workers == 1:
        rows = [run_task(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(run_task, tasks))
    return [row for row in rows if row is not None]


def aggregate(rows: list[dict], split: str) -> dict:
    selected = [row[split] for row in rows if split in row]
    sums = {key: 0 for key in ("A_zstd9", "B_zstd19", "C_lzma2", "D", "E", "F")}
    improved = 0
    math_rules = 0
    math_invocations = 0
    all_ok = True
    for record in selected:
        for control in ("A_zstd9", "B_zstd19", "C_lzma2"):
            sums[control] += record["controls"][control]["size_bytes"]
        for variant in ("D", "E", "F"):
            sums[variant] += record["variants"][variant]["size_bytes"]
            all_ok = all_ok and record["variants"][variant]["decoded_ok"]
        math_rules += record["variants"]["F"]["rules"]["math"]
        math_invocations += record["variants"]["F"]["math_invocations"]
        if record["variants"]["F"]["size_bytes"] < record["variants"]["D"]["size_bytes"]:
            improved += 1
    return {
        "regions": len(selected),
        "bytes": sums,
        "F_vs_D_ratio": round(sums["F"] / sums["D"], 6) if sums["D"] else None,
        "F_vs_E_ratio": round(sums["F"] / sums["E"], 6) if sums["E"] else None,
        "regions_improved_vs_D": improved,
        "math_rules": math_rules,
        "math_invocations": math_invocations,
        "all_reconstructions_exact": all_ok,
    }


def gate_result(validation: dict) -> dict:
    checks = {
        "exact_reconstruction": validation["all_reconstructions_exact"],
        "math_rules_present": validation["math_rules"] > 0,
        "math_invocations_present": validation["math_invocations"] > 0,
        "aggregate_vs_D": validation["F_vs_D_ratio"] is not None
        and validation["F_vs_D_ratio"] <= GATE["aggregate_vs_D_max_ratio"],
        "aggregate_vs_E": validation["F_vs_E_ratio"] is not None
        and validation["F_vs_E_ratio"] <= GATE["aggregate_vs_E_max_ratio"],
        "per_file_wins": validation["regions_improved_vs_D"]
        >= GATE["min_validation_regions_improved_vs_D"],
    }
    return {"checks": checks, "passed": all(checks.values())}


def print_summary(rows: list[dict], split: str) -> None:
    head = f"{'file':8} {'bytes':>7} {'z9':>7} {'z19':>7} {'lzma2':>7} {'D':>7} {'E':>7} {'F':>7} {'F/D':>6}"
    print(head)
    for row in rows:
        record = row[split]
        values = record["variants"]
        print(
            f"{row['name']:8} {record['length']:7d} "
            f"{record['controls']['A_zstd9']['size_bytes']:7d} "
            f"{record['controls']['B_zstd19']['size_bytes']:7d} "
            f"{record['controls']['C_lzma2']['size_bytes']:7d} "
            f"{values['D']['size_bytes']:7d} {values['E']['size_bytes']:7d} {values['F']['size_bytes']:7d} "
            f"{values['F']['size_bytes'] / values['D']['size_bytes']:6.3f}"
        )


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "val", "both"), default="both")
    parser.add_argument("--file", default=None, help="limit to one named input")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    started = time.perf_counter()
    if args.split == "dev":
        rows = run_split("dev", only=args.file)
        payload = {
            "phase": 16,
            "episode": 1,
            "split": "dev",
            "protocol": protocol_dict(),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "files": rows,
            "aggregate": aggregate(rows, "dev"),
        }
        out = Path(args.out) if args.out else RESULTS / "phase16-dev.json"
        write_json(out, payload)
        print_summary(rows, "dev")
        print(json.dumps(payload["aggregate"], indent=1))
    elif args.split == "val":
        dev_path = RESULTS / "phase16-dev.json"
        dev_payload = json.loads(dev_path.read_text(encoding="utf8"))
        families = {row["name"]: row["dev"]["e_family"] for row in dev_payload["files"]}
        val_rows = run_split("val", families=families, only=args.file)
        dev_rows = {row["name"]: row["dev"] for row in dev_payload["files"]}
        combined = []
        for row in val_rows:
            combined.append(
                {
                    "name": row["name"],
                    "path": row["path"],
                    "file_bytes": row["file_bytes"],
                    "file_sha256": row["file_sha256"],
                    "region_bytes": row["region_bytes"],
                    "dev": dev_rows[row["name"]],
                    "val": row["val"],
                }
            )
        validation = aggregate(combined, "val")
        payload = {
            "phase": 16,
            "episode": 1,
            "protocol": protocol_dict(),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "files": combined,
            "aggregate": {"dev": dev_payload["aggregate"], "val": validation},
            "gate": gate_result(validation),
        }
        out = Path(args.out) if args.out else RESULTS / "phase16.json"
        write_json(out, payload)
        print_summary(combined, "val")
        print(json.dumps(validation, indent=1))
        print(json.dumps(payload["gate"], indent=1))
    else:
        dev_rows = run_split("dev", only=args.file)
        families = {row["name"]: row["dev"]["e_family"] for row in dev_rows}
        val_rows = run_split("val", families=families, only=args.file)
        dev_by_name = {row["name"]: row["dev"] for row in dev_rows}
        combined = []
        for row in val_rows:
            combined.append(
                {
                    "name": row["name"],
                    "path": row["path"],
                    "file_bytes": row["file_bytes"],
                    "file_sha256": row["file_sha256"],
                    "region_bytes": row["region_bytes"],
                    "dev": dev_by_name[row["name"]],
                    "val": row["val"],
                }
            )
        dev_aggregate = aggregate(combined, "dev")
        validation = aggregate(combined, "val")
        payload = {
            "phase": 16,
            "episode": 1,
            "protocol": protocol_dict(),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "files": combined,
            "aggregate": {"dev": dev_aggregate, "val": validation},
            "gate": gate_result(validation),
        }
        out = Path(args.out) if args.out else RESULTS / "phase16.json"
        write_json(out, payload)
        print_summary(combined, "dev")
        print_summary(combined, "val")
        print(json.dumps(dev_aggregate, indent=1))
        print(json.dumps(validation, indent=1))
        print(json.dumps(payload["gate"], indent=1))


if __name__ == "__main__":
    main()
