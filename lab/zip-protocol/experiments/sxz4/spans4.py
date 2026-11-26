"""SXZ4: span-level models, independent of storage blocks.

A *search window* decides where to look, a *span* decides where a model is
valid, and the *storage stream* is independent of both.  Spans may start and end
anywhere, cross any block boundary, and several models may cover one region.

The archive stores a position map, the compressed non-span stream with all
residuals, and a tiny header.  If nothing pays off, the engine falls back to a
single backend stream, so it is never worse than the backend alone.
"""

from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass, field

from sinuxz.bitio import BitReader, BitWriter

from experiments.sxz3 import bank as bank3
from experiments.sxz4 import program4, residual4, transforms4

MAGIC = b"SXZ4"
VERSION = 1
FLAG_SPANS = 1
HEADER = struct.Struct("<4sBBBBIIQIII")   # magic, ver, flags, backend, reserved, chainlen, crc, size, mapraw, mapc, streamraw
PLAIN_HEADER = struct.Struct("<4sBBBBIIQI")  # magic, ver, flags, backend, reserved, chainlen, crc, size, streamc

BACKEND_DEFLATE, BACKEND_ZSTD, BACKEND_LZMA = 0, 1, 2

MODELS = [bank3.PeriodBytes(), program4.LfsrBytes(), program4.XorShiftBytes(), bank3.AffineWord(),
          bank3.QuadraticWord(), bank3.LanesWord(), bank3.LcgWord(),
          bank3.XorRotWord(), bank3.XorShiftAny(), bank3.ReferenceSlice(),
          program4.Order2Word(), program4.CrossChannel(), program4.ProgramWord()]
BY_ID = {model.mid: model for model in MODELS}

FIT_SAMPLE = 2048
COARSE = 1024
FINE = 64
MIN_SPAN = 128
MAX_SPAN = 1 << 18
MIN_SAVINGS = 48
# 0.12 was too strict: a composite ramp whose residual costs 62 bytes per
# 2 KiB was cut to 68 fragments and then rejected, while 0.30 covers it with a
# single span (13,614 -> 276 bytes).  The savings test, not the tolerance,
# rejects a bad span.
TOLERANCE = 0.30
CHUNK = 4096


@dataclass
class Stats:
    spans: int = 0
    modelled_bytes: int = 0
    residual_bytes: int = 0
    model_cost: int = 0
    causal_spans: int = 0
    probes: int = 0
    tolerance: float = TOLERANCE
    models: dict = field(default_factory=dict)
    modes: dict = field(default_factory=dict)


def descriptor(model, params) -> bytes:
    writer = BitWriter()
    model.encode(writer, params)
    bits = writer.bit_length
    return bytes([model.mid, bits & 0xFF, (bits >> 8) & 0xFF]) + writer.to_bytes()


def read_descriptor(blob: bytes, pos: int):
    mid, low, high = blob[pos], blob[pos + 1], blob[pos + 2]
    bits = low | (high << 8)
    length = (bits + 7) // 8
    payload = blob[pos + 3 : pos + 3 + length]
    if len(payload) != length:
        raise ValueError("truncated descriptor")
    model = BY_ID.get(mid)
    if model is None:
        raise ValueError(f"unknown model {mid}")
    params = model.decode(BitReader(payload, bits))
    return model, params, pos + 3 + length


# ---------------------------------------------------------------------------
# Span discovery
# ---------------------------------------------------------------------------
def extend(tdata: bytes, pos: int, pred: bytes, tol: float = TOLERANCE,
           cost_check: bool = True, cost_ratio: float = 0.9) -> int:
    """Length of the prefix that the model still describes more cheaply.

    ``tol`` is a hard cap on the mismatch rate.  Inside that cap a chunk is
    kept only when its residual costs less than the backend would spend on the
    same bytes, so a model cannot swallow a region that belongs to another law
    just because the backend is weak there.
    """
    limit = min(len(pred), len(tdata) - pos, MAX_SPAN)
    end = 0
    offset = 0
    while offset < limit:
        take = min(CHUNK, limit - offset)
        actual = tdata[pos + offset : pos + offset + take]
        want = pred[offset : offset + take]
        if actual == want:
            end = offset + take
            offset += take
            continue
        errors = 0
        limit_local = int(take * tol) + 2
        for index in range(take):
            if actual[index] != want[index]:
                errors += 1
                if errors > limit_local:
                    return pos + offset + index
        if cost_check:
            _, _, residual_cost = residual4.best_byte(want, actual)
            if residual_cost > deflate_size(actual) * cost_ratio:
                return pos + offset
        end = offset + take
        offset += take
    return pos + end


def deflate_size(data: bytes, level: int = 6) -> int:
    return len(zlib.compress(data, level))


def has_law(sample: bytes) -> bool:
    """Cheap structure screen, about 1 ms per 4 KiB."""
    from collections import Counter

    if len(sample) < 64:
        return False
    if len(sample) <= 4096:
        from sinuxz.constants import find_reference

        if find_reference(sample, 0, len(sample), 18) is not None:
            return True
    for period in (1, 2, 4, 8, 16, 20, 32, 64):
        if len(sample) > period + 256 and all(
                sample[i] == sample[i - period] for i in range(period, period + 256)):
            return True
    for width, order in ((2, "little"), (2, "big"), (4, "little"), (4, "big"), (8, "little")):
        words = [int.from_bytes(sample[i : i + width], order)
                 for i in range(0, min(len(sample) - width, 2048), width)]
        if len(words) < 16:
            continue
        mask = (1 << (8 * width)) - 1
        diffs = Counter((words[i + 1] - words[i]) & mask for i in range(len(words) - 1))
        if diffs and diffs.most_common(1)[0][1] * 2 >= len(words) - 1:
            return True
        if len(words) > 3:
            second = Counter((words[i + 2] - 2 * words[i + 1] + words[i]) & mask
                             for i in range(len(words) - 2))
            if second and second.most_common(1)[0][1] * 2 >= len(words) - 2:
                return True
    # order-2 linear recurrence: solve a 3x3 system modulo 2**w
    from experiments.sxz4.program4 import solve3, WIDTHS

    for code in (1, 2, 3):
        width = WIDTHS[code]
        mod = 1 << (8 * width)
        mask = mod - 1
        for order in ("little", "big"):
            words = [int.from_bytes(sample[i : i + width], order)
                     for i in range(0, min(len(sample) - width, 1024), width)]
            if len(words) < 12:
                continue
            for start in range(min(6, len(words) - 5)):
                x0, x1, x2, x3, x4 = words[start : start + 5]
                solution = solve3([[x1, x0, 1], [x2, x1, 1], [x3, x2, 1]],
                                  [x2, x3, x4], mod)
                if solution is None:
                    continue
                a, b, c = solution
                hits = sum(1 for i in range(2, len(words))
                           if ((a * words[i - 1] + b * words[i - 2] + c) & mask) == words[i])
                if hits * 10 >= (len(words) - 2) * 9:
                    return True
    # xorshift32 and 32-bit LCG, 32 steps
    for order in ("big", "little"):
        words = [int.from_bytes(sample[i : i + 4], order) for i in range(0, min(len(sample), 256), 4)]
        if len(words) < 32:
            continue
        from experiments.sxz3.bank import XorShiftAny

        for triple in XorShiftAny.TRIPLES:
            state, matched = words[0], True
            for i in range(31):
                state = XorShiftAny.step(state, triple)
                if state != words[i + 1]:
                    matched = False
                    break
            if matched:
                return True
        x0, x1, x2 = words[0], words[1], words[2]
        den = (x1 - x0) & 0xFFFFFFFF
        if den % 2:
            a = ((x2 - x1) * pow(den, -1, 1 << 32)) & 0xFFFFFFFF
            c = (x1 - a * x0) & 0xFFFFFFFF
            if all(((a * words[i] + c) & 0xFFFFFFFF) == words[i + 1] for i in range(31)):
                return True
    return False


def _residual_choice(pred: bytes, actual: bytes):
    mode, payload, cost = residual4.best_byte(pred, actual)
    extra = b""
    if 1024 <= len(actual) <= 65536:
        probe = min(len(actual) // 4, 4096)
        candidate = None
        for width in (2, 4, 8):
            if probe < 4 * width or probe % width:
                continue
            for order in ("little", "big"):
                result = residual4.worddiff(pred[:probe], actual[:probe], width, order)
                if result is None:
                    continue
                _, k, word_payload = result
                store = 1 + 3 + len(residual4.varint(len(word_payload))) + len(word_payload)
                if candidate is None or store < candidate[0]:
                    candidate = (store, width, order)
        if candidate is not None and candidate[0] < cost:
            width, order = candidate[1], candidate[2]
            result = residual4.worddiff(pred, actual, width, order)
            if result is not None:
                _, k, word_payload = result
                store = 1 + 3 + len(residual4.varint(len(word_payload))) + len(word_payload)
                if store < cost:
                    return residual4.WORDDIFF, word_payload, store, bytes(
                        [width, 0 if order == "little" else 1, k])
    return mode, payload, cost, extra


def try_at(tdata: bytes, pos: int, allow_program: bool, floor: int = 0,
           deadline: float | None = None, gate: bool = True,
           tolerance: float = TOLERANCE, exact_only: bool = False,
           min_savings: int = MIN_SAVINGS, ratio: float | None = None) -> dict | None:
    """Best span that starts at or very near ``pos``."""
    if pos < floor:
        return None
    sample = tdata[pos : pos + FIT_SAMPLE]
    if len(sample) < MIN_SPAN:
        return None
    if ratio is None:
        ratio = deflate_size(sample) / max(1, len(sample))
    law = has_law(sample)
    # The gate used to skip both compressible and incompressible samples.  That
    # lost LFSR streams: Deflate already reached 0.3%, so the engine never tried
    # the 86-byte model.  Now only the middle band (where nothing is there) is
    # skipped, and the extremes still get probes.
    if gate and not law and 0.55 <= ratio <= 0.95:
        return None
    if not gate or law or ratio < 0.55:
        models = MODELS
    else:
        models = [bank3.AffineWord(), bank3.LcgWord(), program4.LfsrBytes(),
                  program4.Order2Word()]
        # A program is global; one synthesis at the start of the stream is
        # enough, and it keeps random regions cheap.
        if pos == 0:
            models.append(program4.ProgramWord())
    best = None
    for model in models:
        if deadline is not None and time.perf_counter() > deadline:
            break
        if model.mid == 18 and not allow_program:
            continue
        try:
            fits = model.fit_params(sample)
        except Exception:
            continue
        if getattr(model, "last_score", 1.0) < 0.45:
            continue
        for params in fits:
            try:
                desc = descriptor(model, params)
                pred = model.predict_bytes(params, min(MAX_SPAN, len(tdata) - pos))
            except Exception:
                continue
            end = extend(tdata, pos, pred, tolerance)
            length = end - pos
            if length < MIN_SPAN:
                continue
            actual = tdata[pos:end]
            mode, payload, rcost, extra = _residual_choice(pred[:length], actual)
            if exact_only and mode != residual4.EXACT:
                continue
            map_cost = 6 + len(residual4.varint(length)) + len(desc)
            savings = deflate_size(actual) - (len(desc) + rcost + map_cost + min_savings)
            if savings <= 0:
                continue
            span = {"start": pos, "length": length, "kind": 0, "model": model, "params": params,
                    "descriptor": desc, "mode": mode, "payload": payload, "extra": extra,
                    "cost": len(desc) + rcost, "savings": savings}
            if best is None or span["savings"] > best["savings"]:
                best = span
    return best


def causal_promising(sample: bytes) -> bool:
    """Cheap check: do consecutive words often repeat the same difference?"""
    from collections import Counter

    for width, order in ((2, "little"), (2, "big"), (4, "little"), (4, "big")):
        words = [int.from_bytes(sample[i : i + width], order)
                 for i in range(0, min(len(sample) - width, 2048), width)]
        if len(words) < 64:
            continue
        mask = (1 << (8 * width)) - 1
        diffs = Counter((words[i + 1] - words[i]) & mask for i in range(len(words) - 1))
        if diffs and diffs.most_common(1)[0][1] * 10 >= len(words) - 1:
            return True
    return False


def causal_span(tdata: bytes, pos: int) -> dict | None:
    """A predictor that only uses reconstructed history."""
    head = tdata[pos : pos + 4096]
    if len(head) < 1024:
        return None
    if deflate_size(head) < len(head) * 0.6:
        return None            # the backend already handles this region
    if not causal_promising(head):
        return None
    length = min(65536, len(tdata) - pos)
    if length < MIN_SPAN:
        return None
    result = residual4.best_causal(tdata, pos, length)
    if result is None:
        return None
    store, info = result
    actual = tdata[pos : pos + length]
    savings = deflate_size(actual) - (store + 6 + MIN_SAVINGS)
    if savings <= 0:
        return None
    longer = min(MAX_SPAN, len(tdata) - pos)
    if longer > length * 2:
        big = residual4.best_causal(tdata, pos, longer)
        if big is not None and big[0] < store * (longer / length):
            length, store, info = longer, big[0], big[1]
            actual = tdata[pos : pos + length]
            savings = deflate_size(actual) - (store + 6 + MIN_SAVINGS)
    return {"start": pos, "length": length, "kind": 1, "descriptor": info["description"],
            "mode": residual4.CAUSAL, "payload": info["payload"], "extra": b"",
            "cost": store, "savings": savings, "causal": info}


def find_spans(tdata: bytes, allow_program: bool, max_probes: int = 4000,
               time_budget: float = 30.0, gate: bool = True,
               tolerance: float = TOLERANCE, exact_only: bool = False,
               min_savings: int = MIN_SAVINGS, probe_step: int = COARSE,
               refine: tuple[int, ...] = (64, 192, 320, 448, 576, 704, 832, 960)) -> tuple[list[dict], Stats]:
    stats = Stats()
    spans = []
    n = len(tdata)
    pos = 0
    started = time.perf_counter()
    while pos + MIN_SPAN <= n:
        if stats.probes >= max_probes or time.perf_counter() - started > time_budget:
            break
        candidate = None
        floor = spans[-1]["start"] + spans[-1]["length"] if spans else 0
        ratio = deflate_size(tdata[pos : pos + FIT_SAMPLE]) / max(1, min(FIT_SAMPLE, len(tdata) - pos))
        best = try_at(tdata, pos, allow_program, floor, time.perf_counter() + 1.5,
                      gate, tolerance, exact_only, min_savings, ratio)
        stats.probes += 1
        if best is not None:
            candidate = best
            # Binary-search the earliest position that still fits the same law.
            # The probe grid can land up to one step inside a span; leaving the
            # head in the literal stream costs real bytes, so recover it.
            best_end = best["start"] + best["length"]
            lo = max(floor, best["start"] - 8192)
            hi = best["start"]
            while hi - lo > 128:
                mid = (lo + hi) // 2
                probe = try_at(tdata, mid, allow_program, floor,
                               time.perf_counter() + 1.5, gate, tolerance,
                               exact_only, min_savings)
                stats.probes += 1
                if probe is not None and probe["start"] + probe["length"] > hi + 1024:
                    hi = mid
                else:
                    lo = mid
            earlier = try_at(tdata, hi, allow_program, floor, time.perf_counter() + 1.5,
                             gate, tolerance, exact_only, min_savings)
            stats.probes += 1
            if (earlier is not None
                    and earlier["start"] + earlier["length"] >= best_end - 2048):
                candidate = earlier
            # Refine the start within the previous coarse window.
            anchor = candidate["start"]
            for shift in refine:
                if shift > anchor - floor:
                    break
                other = try_at(tdata, anchor - shift, allow_program, floor,
                               time.perf_counter() + 1.5, gate, tolerance,
                               exact_only, min_savings)
                stats.probes += 1
                if other is not None and other["start"] + other["length"] > candidate["start"] + candidate["length"]:
                    candidate = other
                if stats.probes >= max_probes:
                    break
        causal = causal_span(tdata, pos) if pos % 4096 == 0 else None
        if causal is not None and (candidate is None or causal["savings"] > candidate["savings"]):
            candidate = causal
        if candidate is None:
            # Compressible regions are where laws hide; scan them sparsely but
            # with the full bank.  Random-looking regions get cheap probes.
            if ratio < 0.55:
                pos += probe_step if probe_step < COARSE else max(probe_step, 16384)
            elif ratio > 0.95:
                pos += probe_step if probe_step < COARSE else max(probe_step, 4096)
            else:
                pos += probe_step
            continue
        spans.append(candidate)
        stats.spans += 1
        stats.modelled_bytes += candidate["length"]
        stats.residual_bytes += len(candidate["payload"])
        stats.model_cost += len(candidate["descriptor"])
        if candidate["kind"] == 1:
            stats.causal_spans += 1
            stats.modes["causal"] = stats.modes.get("causal", 0) + 1
        else:
            stats.models[candidate["model"].name] = stats.models.get(candidate["model"].name, 0) + 1
            name = residual4.NAMES.get(candidate["mode"], str(candidate["mode"]))
            stats.modes[name] = stats.modes.get(name, 0) + 1
        pos = candidate["start"] + candidate["length"]
    return spans, stats


# ---------------------------------------------------------------------------
# Container
# ---------------------------------------------------------------------------
def _compress(data: bytes, backend: int) -> bytes:
    if backend == BACKEND_ZSTD:
        import zstandard

        return zstandard.ZstdCompressor(level=19).compress(data)
    if backend == BACKEND_LZMA:
        import lzma

        return lzma.compress(data, preset=6)
    return zlib.compress(data, 6)


def _decompress(data: bytes, backend: int, size: int) -> bytes:
    if backend == BACKEND_ZSTD:
        import zstandard

        out = zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
    elif backend == BACKEND_LZMA:
        import lzma

        out = lzma.decompress(data)
    else:
        out = zlib.decompress(data)
    if len(out) != size:
        raise ValueError("backend size mismatch")
    return out


def build_map(spans: list[dict]) -> bytes:
    out = bytearray(residual4.varint(len(spans)))
    previous_end = 0
    for span in spans:
        out += residual4.varint(span["start"] - previous_end)
        out += residual4.varint(span["length"])
        out.append(span["kind"])
        if span["kind"] == 0:
            out += span["descriptor"]
            out.append(span["mode"])
            if span["mode"] == residual4.WORDDIFF:
                out += span["extra"]
        else:
            info = span["causal"]
            out += bytes([info["width"].bit_length() - 1,
                          0 if info["order"] == "little" else 1,
                          info["kind"], info["k"]])
        out += residual4.varint(len(span["payload"]))
        previous_end = span["start"] + span["length"]
    return bytes(out)


def parse_map(blob: bytes):
    count, pos = residual4.read_varint(blob, 0)
    spans = []
    previous_end = 0
    for _ in range(count):
        gap, pos = residual4.read_varint(blob, pos)
        length, pos = residual4.read_varint(blob, pos)
        kind = blob[pos]; pos += 1
        causal = None
        extra = b""
        model = params = None
        mode = 0
        if kind == 0:
            model, params, pos = read_descriptor(blob, pos)
            mode = blob[pos]; pos += 1
            if mode == residual4.WORDDIFF:
                extra = blob[pos : pos + 3]; pos += 3
        else:
            width_code, order_code, kind_code, k = blob[pos : pos + 4]
            pos += 4
            causal = {"width": 1 << width_code, "order": "little" if order_code == 0 else "big",
                      "kind": kind_code, "k": k}
        residual_len, pos = residual4.read_varint(blob, pos)
        spans.append({"start": previous_end + gap, "length": length, "kind": kind,
                      "model": model, "params": params, "mode": mode, "extra": extra,
                      "causal": causal, "residual_len": residual_len})
        previous_end += gap + length
    return spans, pos


def build_container(data: bytes, chain: tuple[int, ...], tdata: bytes, chain_blob: bytes,
                    spans: list[dict], backend: int) -> bytes:
    """Assemble the span archive from an explicit span list.

    The caller is responsible for non-overlap and range; this is the same
    code path as :func:`pack`, exposed so global span selection can be tested.
    """
    covered = bytearray(len(tdata))
    residuals = bytearray()
    for span in spans:
        if span["start"] < 0 or span["start"] + span["length"] > len(tdata):
            raise ValueError("span outside the stream")
        covered[span["start"] : span["start"] + span["length"]] = b"\x01" * span["length"]
        residuals += span["payload"]
    keep = bytes(tdata[index] for index, flag in enumerate(covered) if not flag)
    stream = keep + bytes(residuals)
    map_blob = build_map(spans)
    packed_stream = _compress(stream, backend)
    packed_map = _compress(map_blob, backend)
    crc = zlib.crc32(data) & 0xFFFFFFFF
    return (HEADER.pack(MAGIC, VERSION, FLAG_SPANS, backend, 0, len(chain_blob), crc, len(data),
                        len(map_blob), len(packed_map), len(stream))
            + chain_blob + packed_map + packed_stream)


def pack(data: bytes, chain: tuple[int, ...] = (0,), backend: int = BACKEND_DEFLATE,
         spans_on: bool = True, allow_program: bool = False,
         max_probes: int = 4000, time_budget: float = 30.0,
         gate: bool = True, tolerance: float = TOLERANCE,
         exact_only: bool = False, min_savings: int = MIN_SAVINGS,
         probe_step: int = COARSE, refine: tuple[int, ...] = (64, 192, 320, 448, 576, 704, 832, 960),
         tolerance_sweep: tuple[float, ...] | None = None) -> tuple[bytes, Stats]:
    tdata, metas = transforms4.apply_chain(data, chain)
    chain_blob = transforms4.encode_chain(chain, metas)
    plain = _compress(tdata, backend)
    plain_blob = PLAIN_HEADER.pack(MAGIC, VERSION, 0, backend, 0, len(chain_blob),
                                   zlib.crc32(data) & 0xFFFFFFFF, len(data), len(plain))
    plain_blob += chain_blob + plain

    if not spans_on:
        return plain_blob, Stats()

    best = None
    stats = Stats()
    for tol in (tolerance_sweep or (tolerance,)):
        spans, stats = find_spans(tdata, allow_program, max_probes, time_budget, gate,
                                  tol, exact_only, min_savings, probe_step, refine)
        if not spans:
            continue
        body = build_container(data, chain, tdata, chain_blob, spans, backend)
        if len(body) >= len(plain_blob):
            continue
        if best is None or len(body) < len(best[0]):
            stats.tolerance = tol
            best = (body, stats)
    if best is None:
        return plain_blob, stats
    return best


def _unpack(blob: bytes, verify: bool = True) -> bytes:
    magic, version, flags = blob[0:4], blob[4], blob[5]
    if magic != MAGIC or version != VERSION:
        raise ValueError("not an SXZ4 archive")
    # Re-read with the full structs to keep the offsets obvious.
    if flags == FLAG_SPANS:
        (_, _, _, backend, _, chain_len, crc, size, map_raw, map_comp, stream_raw) = HEADER.unpack_from(blob, 0)
        pos = HEADER.size
    else:
        (_, _, _, backend, _, chain_len, crc, size, stream_comp) = PLAIN_HEADER.unpack_from(blob, 0)
        pos = PLAIN_HEADER.size
    chain, metas, used = transforms4.decode_chain(blob[pos : pos + chain_len])
    if used != chain_len:
        raise ValueError("bad transform metadata")
    pos += chain_len
    if flags != FLAG_SPANS:
        tdata = _decompress(blob[pos : pos + stream_comp], backend, size)
        data = transforms4.invert_chain(tdata, chain, metas)
        if verify and (zlib.crc32(data) & 0xFFFFFFFF) != crc:
            raise ValueError("SXZ4 crc mismatch")
        return data

    packed_map = blob[pos : pos + map_comp]
    pos += map_comp
    packed_stream = blob[pos:]
    if not packed_stream:
        raise ValueError("missing stream")
    map_blob = _decompress(packed_map, backend, map_raw)
    stream = _decompress(packed_stream, backend, stream_raw)
    spans, used = parse_map(map_blob)
    if used != len(map_blob):
        raise ValueError("unconsumed map bytes")
    non_span = size - sum(span["length"] for span in spans)
    if non_span < 0:
        raise ValueError("spans exceed the input")
    tdata = bytearray(size)
    data_cursor = 0
    residual_cursor = non_span
    position = 0
    for span in spans:
        start, length = span["start"], span["length"]
        if start < position or start + length > size:
            raise ValueError("overlapping or out-of-range span")
        for index in range(position, start):
            tdata[index] = stream[data_cursor]
            data_cursor += 1
        payload = stream[residual_cursor : residual_cursor + span["residual_len"]]
        residual_cursor += span["residual_len"]
        if span["kind"] == 1:
            info = span["causal"]
            residual4.apply_causal(tdata, start, length, info["width"], info["order"],
                                   info["kind"], payload)
        else:
            pred = span["model"].predict_bytes(span["params"], length)
            if span["mode"] == residual4.WORDDIFF:
                width, order_code, k = span["extra"]
                order = "little" if order_code == 0 else "big"
                actual = residual4.apply_worddiff(pred, width, order, k, payload)
            else:
                actual = residual4.apply_byte(pred, span["mode"], payload)
            tdata[start : start + length] = actual
        position = start + length
    for index in range(position, size):
        tdata[index] = stream[data_cursor]
        data_cursor += 1
    if data_cursor != non_span or residual_cursor != len(stream):
        raise ValueError("stream accounting mismatch")
    data = transforms4.invert_chain(bytes(tdata), chain, metas)
    if verify and (zlib.crc32(data) & 0xFFFFFFFF) != crc:
        raise ValueError("SXZ4 crc mismatch")
    return data


def unpack(blob: bytes, verify: bool = True) -> bytes:
    """Public decoder: malformed input is always reported as ValueError."""
    try:
        return _unpack(blob, verify)
    except ValueError:
        raise
    except (IndexError, struct.error, zlib.error) as exc:
        raise ValueError("corrupt SXZ4 archive") from exc
