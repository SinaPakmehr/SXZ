"""Span economics and overlap accounting.

All comparisons are span-local.  No whole-file gain is claimed from adding
isolated model records.
"""

from __future__ import annotations

import lzma

import numpy as np
import zstandard as zstd

from .config import LZMA_PRESET, SIMPLE_MAX_PERIOD, ZSTD_LEVEL
from .representations import REP_BY_NAME, extract_symbols, pack_symbols

_ZSTD = zstd.ZstdCompressor(level=ZSTD_LEVEL)


def zstd19_size(data: bytes) -> int:
    return len(_ZSTD.compress(data))


def lzma2_size(data: bytes) -> int:
    return len(
        lzma.compress(
            data,
            format=lzma.FORMAT_XZ,
            preset=LZMA_PRESET | lzma.PRESET_EXTREME,
        )
    )


def simple_sizes(data: bytes) -> dict:
    """Sizes of trivial constant-run and byte-periodic representations."""
    output = {"const": None, "periodic": None, "period": None}
    if not data:
        return output
    if data.count(data[:1]) == len(data):
        output["const"] = 6  # mode + value + 4-byte length
    for period in range(1, min(SIMPLE_MAX_PERIOD, len(data) // 2) + 1):
        if all(data[index] == data[index - period] for index in range(period, len(data))):
            output["periodic"] = 6 + period
            output["period"] = period
            break
    return output


def model_span(model, data: bytes) -> tuple[bytes, int, int | None]:
    """Return (packed span bytes, raw byte equivalent, raw bit count)."""
    rep = REP_BY_NAME[model.rep]
    if rep.is_word:
        begin = model.align + model.start * rep.width
        end = begin + model.count * rep.width
        if end > len(data):
            raise ValueError("model span outside data")
        return data[begin:end], end - begin, None
    bits = extract_symbols(data, rep, 0)[model.start : model.start + model.count]
    packed = pack_symbols(bits, rep)
    return packed, len(packed), model.count


def evaluate_model(model, data: bytes) -> dict:
    span, raw_bytes, raw_bits = model_span(model, data)
    record = model.record_bytes
    zstd_bytes = zstd19_size(span)
    lzma_bytes = lzma2_size(span)
    simple = simple_sizes(span)
    backend_min = min(raw_bytes, zstd_bytes, lzma_bytes)
    result = {
        "family": model.family,
        "rep": model.rep,
        "align": model.align,
        "start": model.start,
        "count": model.count,
        "order": model.order,
        "window": model.window,
        "fit_len": model.fit_len,
        "val_len": model.val_len,
        "raw_bytes": raw_bytes,
        "raw_bits": raw_bits,
        "record_bytes": record,
        "information_bits": model.information_bits,
        "zstd19": zstd_bytes,
        "lzma2": lzma_bytes,
        "const_repr": simple["const"],
        "periodic_repr": simple["periodic"],
        "period": simple["period"],
        "savings_raw": raw_bytes - record,
        "savings_zstd": zstd_bytes - record,
        "savings_lzma": lzma_bytes - record,
        "savings_backend_min": backend_min - record,
        "raw_profitable": record < raw_bytes,
        "backend_profitable": record < backend_min,
        "with_4b_overhead": record + 4 < backend_min,
        "span_bytes": model.span_bytes,
        "start_byte": model.start_byte,
        "end_byte": model.end_byte,
        "start_bit": model.start_bit,
        "bit_count": model.bit_count,
        "exact": model.exact,
    }
    return result


def union_byte_coverage(models, data_bytes: int, families: set[str] | None = None) -> int:
    mask = np.zeros(data_bytes, dtype=bool)
    for model in models:
        if model.start_byte is None or model.end_byte is None:
            continue
        if families is not None and model.family not in families:
            continue
        mask[model.start_byte : model.end_byte] = True
    return int(mask.sum())


def union_bit_coverage(models, data_bytes: int, families: set[str] | None = None) -> int:
    total = 0
    for plane in range(8):
        mask = np.zeros(8 * data_bytes, dtype=bool)
        name = f"bit{plane}"
        for model in models:
            if model.rep != name or model.start_bit is None or model.bit_count is None:
                continue
            if families is not None and model.family not in families:
                continue
            mask[model.start_bit : model.start_bit + model.bit_count] = True
        total += int(mask.sum())
    return total


def select_nonoverlap(models, data_bytes: int, families: set[str] | None = None):
    """Greedy longest-first selection of byte spans; no two overlap."""
    candidates = [
        model
        for model in models
        if model.start_byte is not None
        and model.end_byte is not None
        and model.exact
        and (families is None or model.family in families)
    ]
    candidates.sort(key=lambda item: (-item.span_bytes, item.record_bytes))
    mask = np.zeros(data_bytes, dtype=bool)
    selected = []
    for model in candidates:
        if mask[model.start_byte : model.end_byte].any():
            continue
        selected.append(model)
        mask[model.start_byte : model.end_byte] = True
    return selected
