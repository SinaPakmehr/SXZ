"""Window scanner, span extension, consolidation and record verification."""

from __future__ import annotations

import bisect
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .config import (
    BM_MAX_ORDER,
    HALF_STRIDE,
    MAX_SPAN_BITS,
    MAX_SPAN_SYMBOLS,
    WINDOWS,
)
from .inference import Candidate, detect_bit_window, detect_word_window, poly_initials, poly_predict
from .records import ModelRecord, record_information_bits, seed_to_int
from .representations import ALL_REPRESENTATIONS, Representation, extract_symbols


@dataclass
class ScannedModel:
    family: str
    rep: str
    align: int
    start: int
    count: int
    order: int
    params: tuple
    record_bytes: int
    information_bits: int
    window: int
    fit_len: int
    val_len: int
    exact: bool
    high_order: bool
    alignment_pass: bool
    span_bytes: int
    start_byte: int | None
    end_byte: int | None
    start_bit: int | None
    bit_count: int | None
    simple_fraction: float
    degenerate_tail: bool

    def to_dict(self) -> dict:
        return {
            "family": self.family,
            "rep": self.rep,
            "align": self.align,
            "start": self.start,
            "count": self.count,
            "order": self.order,
            "params": list(self.params),
            "record_bytes": self.record_bytes,
            "information_bits": self.information_bits,
            "window": self.window,
            "fit_len": self.fit_len,
            "val_len": self.val_len,
            "exact": self.exact,
            "high_order": self.high_order,
            "alignment_pass": self.alignment_pass,
            "span_bytes": self.span_bytes,
            "start_byte": self.start_byte,
            "end_byte": self.end_byte,
            "start_bit": self.start_bit,
            "bit_count": self.bit_count,
            "simple_fraction": self.simple_fraction,
            "degenerate_tail": self.degenerate_tail,
        }


@dataclass
class ScanResult:
    name: str
    data_bytes: int
    full: bool
    sha256: str
    windows: int
    symbols_examined: int
    representation_bytes_examined: int
    elapsed_s: float
    stats: dict
    models: list[ScannedModel] = field(default_factory=list)
    windows_by_rep: dict = field(default_factory=dict)
    success_by_rep: dict = field(default_factory=dict)
    models_by_family: dict = field(default_factory=dict)

    @property
    def throughput_mb_s(self) -> float:
        return self.data_bytes / (1 << 20) / self.elapsed_s if self.elapsed_s else 0.0


def _starts(length: int, window: int) -> list[int]:
    if length < window:
        return []
    half = window // 2
    stride = half if HALF_STRIDE else window
    starts = list(range(0, length - window + 1, stride))
    last = length - window
    if not starts or starts[-1] != last:
        starts.append(last)
    return starts


def _shape_key(candidate: Candidate) -> tuple:
    if candidate.family == "periodic":
        return ("periodic", int(candidate.shape[0]))
    if candidate.family.startswith("poly"):
        # The highest difference is invariant along one polynomial run.
        # Lower initial differences change with the window start.
        return (candidate.family, int(candidate.shape[-1]))
    return (candidate.family,) + tuple(candidate.shape)


def scan_file(
    data: bytes,
    name: str,
    reps: Iterable[Representation] = ALL_REPRESENTATIONS,
    windows: tuple[int, ...] = WINDOWS,
    align: int = 0,
    symbol_range: tuple[int, int] | None = None,
    alignment_pass: bool = False,
) -> ScanResult:
    begin = time.perf_counter()
    stats: dict = {}
    models: list[ScannedModel] = []
    windows_by_rep: dict = {}
    success_by_rep: dict = {}
    models_by_family: dict = {}
    total_windows = 0
    symbols_examined = 0
    representation_bytes = 0

    for rep in reps:
        symbols = extract_symbols(data, rep, align)
        successes: list[Candidate] = []
        rep_windows = 0
        rep_success = 0
        for window in windows:
            if symbol_range is None:
                starts = _starts(len(symbols), window)
            else:
                low, high = symbol_range
                all_starts = _starts(len(symbols), window)
                starts = [s for s in all_starts if s >= low and s + window <= high]
            for start in starts:
                total_windows += 1
                rep_windows += 1
                symbols_examined += window
                representation_bytes += (
                    window * rep.width if rep.is_word else max(1, (window + 7) // 8)
                )
                if rep.is_word:
                    candidate = detect_word_window(
                        symbols, start, window, rep.sym_bits, stats
                    )
                else:
                    candidate = detect_bit_window(
                        symbols, start, window, stats, max_order=BM_MAX_ORDER
                    )
                if candidate is not None:
                    successes.append(candidate)
                    rep_success += 1
        consolidated = _consolidate(
            data, rep, successes, align, alignment_pass, stats
        )
        models.extend(consolidated)
        for model in consolidated:
            models_by_family[model.family] = models_by_family.get(model.family, 0) + 1
        windows_by_rep[rep.name] = rep_windows
        success_by_rep[rep.name] = rep_success

    elapsed = time.perf_counter() - begin
    return ScanResult(
        name=name,
        data_bytes=len(data),
        full=True,
        sha256=hashlib.sha256(data).hexdigest(),
        windows=total_windows,
        symbols_examined=symbols_examined,
        representation_bytes_examined=representation_bytes,
        elapsed_s=elapsed,
        stats=stats,
        models=models,
        windows_by_rep=windows_by_rep,
        success_by_rep=success_by_rep,
        models_by_family=models_by_family,
    )


def _consolidate(
    data: bytes,
    rep: Representation,
    successes: list[Candidate],
    align: int,
    alignment_pass: bool,
    stats: dict,
) -> list[ScannedModel]:
    if not successes:
        return []
    symbols = extract_symbols(data, rep, align)
    groups: dict[tuple, list[Candidate]] = defaultdict(list)
    for candidate in successes:
        groups[_shape_key(candidate)].append(candidate)

    output: list[ScannedModel] = []
    for key, items in groups.items():
        starts = sorted({candidate.start for candidate in items})
        window_by_start = {candidate.start: candidate.window for candidate in items}
        index = 0
        while index < len(starts):
            start = starts[index]
            window = window_by_start[start]
            built = _build_params(rep, key, symbols, start)
            if built is None:
                index += 1
                continue
            family, order, params = built
            maximum = MAX_SPAN_BITS if rep.is_bit else MAX_SPAN_SYMBOLS
            maximum = min(maximum, len(symbols) - start)
            count = _extend(rep, family, params, symbols, start, maximum, order)
            if count <= 0:
                index += 1
                continue
            record = ModelRecord(family, rep, align, start, count, order, params, flags=2)
            blob = record.to_bytes()
            decoded = ModelRecord.from_bytes(blob)
            reconstructed = decoded.reconstruct_symbols()
            expected = symbols[start : start + count]
            exact = np.array_equal(
                np.asarray(reconstructed, dtype=np.uint64), expected.astype(np.uint64)
            )
            if rep.is_word:
                packed = b"".join(
                    int(value).to_bytes(rep.width, rep.order) for value in reconstructed
                )
                begin = align + start * rep.width
                exact = exact and packed == data[begin : begin + count * rep.width]
            if not exact:
                stats["record_verification_failures"] = (
                    stats.get("record_verification_failures", 0) + 1
                )
            high_order = family == "bm" and order > window // 2
            if high_order:
                stats["consolidated_high_order"] = stats.get("consolidated_high_order", 0) + 1
            unique, counts = np.unique(expected, return_counts=True)
            simple_fraction = float(counts.max() / count) if counts.size else 0.0
            degenerate_tail = (
                family in {"poly1", "poly2", "poly3", "affine1", "affine2", "bm"}
                and simple_fraction > 0.90
            )
            if degenerate_tail:
                stats["degenerate_tail_models"] = stats.get("degenerate_tail_models", 0) + 1
            if rep.is_word:
                start_byte = align + start * rep.width
                end_byte = start_byte + count * rep.width
                start_bit = None
                bit_count = None
                span = count * rep.width
            else:
                start_byte = None
                end_byte = None
                start_bit = start
                bit_count = count
                span = (count + 7) // 8
            output.append(
                ScannedModel(
                    family=family,
                    rep=rep.name,
                    align=align,
                    start=start,
                    count=count,
                    order=order,
                    params=tuple(params),
                    record_bytes=len(blob),
                    information_bits=record_information_bits(record),
                    window=window,
                    fit_len=window // 2,
                    val_len=window - window // 2,
                    exact=exact,
                    high_order=high_order,
                    alignment_pass=alignment_pass,
                    span_bytes=span,
                    start_byte=start_byte,
                    end_byte=end_byte,
                    start_bit=start_bit,
                    bit_count=bit_count,
                    simple_fraction=simple_fraction,
                    degenerate_tail=degenerate_tail,
                )
            )
            index = bisect.bisect_left(starts, start + count, lo=index + 1)
    return output


def _build_params(
    rep: Representation, key: tuple, symbols: np.ndarray, start: int
) -> tuple[str, int, tuple] | None:
    family = key[0]
    if family == "const":
        return "const", 0, (int(key[1]),)
    if family == "periodic":
        period = int(key[1])
        if start + period > len(symbols):
            return None
        pattern = tuple(int(value) for value in symbols[start : start + period])
        return "periodic", period, (pattern,)
    if family.startswith("poly"):
        order = int(family[-1])
        if start + order + 1 > len(symbols):
            return None
        initials = tuple(poly_initials(symbols[start : start + order + 1], order, rep.sym_bits))
        return family, order, initials
    if family == "affine1":
        if start >= len(symbols):
            return None
        a, c = int(key[1]), int(key[2])
        return "affine1", 1, (a, c, int(symbols[start]))
    if family == "affine2":
        if start + 1 >= len(symbols):
            return None
        a, b, c = int(key[1]), int(key[2]), int(key[3])
        return "affine2", 2, (a, b, c, int(symbols[start]), int(symbols[start + 1]))
    if family == "bm":
        order, taps = int(key[1]), int(key[2])
        if start + order > len(symbols):
            return None
        seed = seed_to_int(int(value) for value in symbols[start : start + order])
        return "bm", order, (taps, seed)
    return None


def _extend(
    rep: Representation,
    family: str,
    params: tuple,
    symbols: np.ndarray,
    start: int,
    maximum: int,
    order: int,
) -> int:
    if maximum <= 0:
        return 0
    if family == "const":
        value = int(params[0])
        mismatch = np.flatnonzero(symbols[start : start + maximum] != value)
        return int(mismatch[0]) if mismatch.size else maximum
    if family == "periodic":
        pattern = np.asarray(params[0], dtype=np.uint64)
        period = len(pattern)
        tile = np.tile(pattern, maximum // period + 1)[:maximum]
        mismatch = np.flatnonzero(symbols[start : start + maximum] != tile)
        return int(mismatch[0]) if mismatch.size else maximum
    if family.startswith("poly"):
        predicted = np.asarray(poly_predict(params, maximum, rep.sym_bits), dtype=np.uint64)
        mismatch = np.flatnonzero(predicted != symbols[start : start + maximum])
        return int(mismatch[0]) if mismatch.size else maximum
    if family == "affine1":
        a, c, x0 = int(params[0]), int(params[1]), int(params[2])
        mask = rep.mask
        current = x0
        for offset in range(maximum):
            if current != int(symbols[start + offset]):
                return offset
            current = (a * current + c) & mask
        return maximum
    if family == "affine2":
        a, b, c, x0, x1 = (int(value) for value in params)
        mask = rep.mask
        previous2, previous1 = x0, x1
        for offset in range(maximum):
            current = previous2 if offset == 0 else (previous1 if offset == 1 else (a * previous1 + b * previous2 + c) & mask)
            if offset >= 2:
                previous2, previous1 = previous1, current
            if current != int(symbols[start + offset]):
                return offset
        return maximum
    if family == "bm":
        taps_value = int(params[0])
        seed_bits = [int(value) & 1 for value in symbols[start : start + order]]
        state = 0
        for index in range(order):
            state |= (seed_bits[order - 1 - index] & 1) << index
        state_mask = (1 << order) - 1
        for offset in range(maximum):
            if offset < order:
                bit = seed_bits[offset]
            else:
                bit = (state & taps_value).bit_count() & 1
                state = ((state << 1) | bit) & state_mask
            if bit != int(symbols[start + offset]):
                return offset
        return maximum
    return 0
