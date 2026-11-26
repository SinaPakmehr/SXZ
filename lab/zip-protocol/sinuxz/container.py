"""SINUXZ container: pack bits as formulas + compressed raw pools.

Format (all integers little endian)
-----------------------------------
Header 16 bytes::

    magic  4s  b"SXZ1"
    version u8 (=1)
    flags   u8  1=stored, 2=whole-file deflate, 4=structured segments
    size    u32 original byte length
    nseg    u16 number of segments
    crc     u32 crc32 of the original data

Structured body, repeated ``nseg`` times::

    codec u8
      0 raw      : u32 usize, bytes
      1 deflate  : u32 usize, u32 csize, zlib bytes
      2 formula  : u32 usize, u8 transform, u8 model, u16 param_bits, params
      3 pnm      : u32 usize, u32 csize, u8 predictor, zlib residual bytes
      4 pcm      : u32 usize, u32 csize, u8 predictor, zlib residual bytes

The decoder regenerates ``usize`` bytes from the formula, inverts the
transform and appends them.  Nothing is approximated: a segment is only
stored as a formula when the generated bits match the input exactly.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from .bitio import BitReader, BitWriter, bits_to_bytes, bytes_to_bits
from .constants import REFERENCE_SIZE, find_reference, reference_hits
from .models import BY_ID as MODEL_BY_ID
from .models import MODELS, QUADRATIC, REFERENCE, Model, Params, formula_cost_bits
from .pcm import mode_name as pcm_mode_name
from .pcm import pack_pcm, restore_pcm, wav_layout
from .predictors import PREDICTORS, pnm_layout, predict_pnm
from .transforms import BY_ID as TRANSFORM_BY_ID
from .transforms import TRANSFORMS

MAGIC = b"SXZ1"
VERSION = 1

FLAG_STORED = 1
FLAG_DEFLATE = 2
FLAG_STRUCTURED = 4

HEADER = struct.Struct("<4sBBIHI")
SEG_FORMULA = struct.Struct("<BIBBH")
SEG_DEFLATE = struct.Struct("<BII")
SEG_RAW = struct.Struct("<BI")
SEG_PNM = struct.Struct("<BIIB")
SEG_PCM = SEG_PNM

FORMULA_HEADER_BYTES = SEG_FORMULA.size  # 9
DEFLATE_HEADER_BYTES = SEG_DEFLATE.size  # 9

CODEC_RAW = 0
CODEC_DEFLATE = 1
CODEC_FORMULA = 2
CODEC_PNM = 3
CODEC_PCM = 4


@dataclass
class Candidate:
    transform_id: int
    model: Model
    params: Params
    cover_bytes: int
    cost_bits: int

    @property
    def score(self) -> float:
        return self.cost_bits / max(self.cover_bytes, 1)

    @property
    def payload_bytes(self) -> int:
        # cost_bits already includes FORMULA_HEADER_BYTES * 8.
        return (self.cost_bits + 7) // 8


@dataclass
class SegmentInfo:
    codec: int
    size: int
    detail: str
    cost_bytes: int


class Packer:
    def __init__(
        self,
        max_window: int = 512,
        min_formula_bytes: int = 16,
        step: Optional[int] = None,
        extend_bytes: int = 16384,
        level: int = 9,
        experimental_models: bool = False,
        scan_budget: int | None = None,
    ) -> None:
        if max_window < 1 or not 1 <= min_formula_bytes <= max_window:
            raise ValueError("expected 1 <= min_formula_bytes <= max_window")
        if step is not None and step < 1:
            raise ValueError("step must be positive")
        if extend_bytes < 0 or not 0 <= level <= 9:
            raise ValueError("expected nonnegative extend_bytes and zlib level 0..9")
        if scan_budget is not None and scan_budget < 0:
            raise ValueError("scan_budget must be nonnegative")
        self.max_window = max_window
        self.min_formula_bytes = min_formula_bytes
        self.extend_bytes = extend_bytes
        self.level = level
        self.experimental_models = experimental_models
        self.scan_budget = scan_budget
        self._models = [*MODELS, QUADRATIC] if experimental_models else MODELS
        self._step = step
        self.segments: list[SegmentInfo] = []
        self.probe_count = 0
        self.scan_seconds = 0.0
        self.predict_seconds = 0.0
        # Optional diagnostic log. None by default so packing is unchanged.
        self.trace: list[dict] | None = None
        self._fits: list[dict] | None = None
        self.choices: list[tuple[int, str]] | None = None

    # -- formula search ----------------------------------------------------
    def _step_for(self, n: int) -> int:
        if self._step is not None:
            return self._step
        if n <= 4096:
            return 8
        if n <= 262144:
            return 32
        return 64

    def find_formula(self, window: bytes, probe_extend: bytes = b"") -> Optional[Candidate]:
        """Best formula that reproduces a prefix of ``window`` exactly."""
        best: Optional[Candidate] = None
        log: list[dict] | None = [] if self.trace is not None else None
        for transform in TRANSFORMS:
            tb = transform.forward(window)
            bits = bytes_to_bits(tb)
            for model in self._models:
                for params in model.fit(bits):
                    lcp = model.match(params, bits)
                    cover = lcp // 8
                    if log is not None:
                        log.append({"transform": transform.name, "model": model.name,
                                    "params": params, "cover": cover,
                                    "cost_bits": formula_cost_bits(model, params)})
                    if cover < self.min_formula_bytes:
                        continue
                    cand = Candidate(
                        transform_id=transform.tid,
                        model=model,
                        params=params,
                        cover_bytes=cover,
                        cost_bits=formula_cost_bits(model, params),
                    )
                    if (
                        best is None
                        or cand.score < best.score - 1e-9
                        or (abs(cand.score - best.score) <= 1e-9 and cand.cover_bytes > best.cover_bytes)
                    ):
                        best = cand
        # A formula found in a small window usually keeps going.  Verify the
        # longer prefix before committing to it.
        if best is not None and best.cover_bytes == len(window) and len(probe_extend) > len(window):
            transform = TRANSFORM_BY_ID[best.transform_id]
            tb = transform.forward(probe_extend)
            ext_bits = bytes_to_bits(tb)
            lcp = best.model.match(best.params, ext_bits)
            cover = lcp // 8
            if cover > best.cover_bytes:
                best.cover_bytes = cover
        if self.experimental_models:
            probe = probe_extend if len(probe_extend) > len(window) else window
            match = find_reference(probe, 0, len(probe), self.min_formula_bytes)
            if match is not None:
                cover, params = match
                if log is not None:
                    log.append({"transform": "identity", "model": REFERENCE.name,
                                "params": params, "cover": cover,
                                "cost_bits": formula_cost_bits(REFERENCE, params)})
                cand = Candidate(0, REFERENCE, params, cover, formula_cost_bits(REFERENCE, params))
                if best is None or (cand.score, -cover) < (best.score, -best.cover_bytes):
                    best = cand
        self._fits = log
        return best

    # -- segmentation ------------------------------------------------------
    def _segment(self, data: bytes) -> list[tuple]:
        n = len(data)
        step = self._step_for(n)
        bounded = self.scan_budget is not None
        if self.scan_budget is not None:
            if self.scan_budget == 0:
                return []
            # Fixed absolute grid: accepting a segment or finding a reference
            # between grid points cannot create additional expensive probes.
            step = max(step, (n + self.scan_budget - 1) // self.scan_budget)
        max_span = max(self.max_window, self.extend_bytes)
        pos = 0
        pool_start = 0
        out: list[tuple] = []

        def worth_storing(cand: Candidate, span: bytes) -> bool:
            fallback = min(
                SEG_RAW.size + len(span),
                DEFLATE_HEADER_BYTES + len(zlib.compress(span, self.level)),
            )
            return cand.payload_bytes < fallback

        def flush_pool(end: int) -> None:
            if end > pool_start:
                out.append(("deflate", data[pool_start:end]))

        while pos < n:
            cand = None
            segment_start = pos
            probed = (not bounded or pos % step == 0) and n - pos >= self.min_formula_bytes
            if probed:
                self.probe_count += 1
                window = data[pos : pos + self.max_window]
                extend = data[pos : pos + self.extend_bytes]
                cand = self.find_formula(window, probe_extend=extend)
                fits = self._fits
                if self.experimental_models:
                    earliest = max(pool_start, pos - min(step, max_span // 2))
                    phase = QUADRATIC.fit_lanes(data, pos, self.max_window, earliest, max_span, self.min_formula_bytes)
                    if phase is not None:
                        start, cover, params = phase
                        quad = Candidate(0, QUADRATIC, params, cover, formula_cost_bits(QUADRATIC, params))
                        if cand is None or (quad.score, -cover) < (cand.score, -cand.cover_bytes):
                            cand, segment_start = quad, start
            elif self.experimental_models:
                match = find_reference(data, pos, min(n, pos + max_span), self.min_formula_bytes)
                if match is not None:
                    cover, params = match
                    cand = Candidate(0, REFERENCE, params, cover, formula_cost_bits(REFERENCE, params))
                fits = None
            else:
                fits = None

            if cand is not None:
                span = data[segment_start : segment_start + cand.cover_bytes]
                accepted = worth_storing(cand, span)
                if self.trace is not None:
                    self.trace.append({
                        "pos": pos, "probed": probed, "accepted": accepted,
                        "reason": "accepted" if accepted else "cost_exceeds_fallback",
                        "span": len(span), "cover": cand.cover_bytes,
                        "model": cand.model.name, "transform": TRANSFORM_BY_ID[cand.transform_id].name,
                        "params": cand.params, "cost_bits": cand.cost_bits,
                        "fallback_bytes": min(SEG_RAW.size + len(span),
                                              DEFLATE_HEADER_BYTES + len(zlib.compress(span, self.level))),
                        "fits": fits or [],
                    })
                if accepted:
                    flush_pool(segment_start)
                    out.append(
                        (
                            "formula",
                            len(span),
                            cand.transform_id,
                            cand.model.mid,
                            cand.params,
                        )
                    )
                    pos = segment_start + len(span)
                    pool_start = pos
                    continue
            elif self.trace is not None and probed:
                self.trace.append({"pos": pos, "probed": True, "accepted": False,
                                   "reason": "no_candidate", "fits": fits or []})

            take = min(step - (pos % step if bounded else 0), n - pos)
            if self.experimental_models:
                # Check cheap byte anchors at otherwise skipped offsets; never
                # flush/split a pool merely because an anchor matched.
                for start, cover, params in reference_hits(
                    data, pos + 1, pos + take, max_span, self.min_formula_bytes
                ):
                    ref = Candidate(0, REFERENCE, params, cover, formula_cost_bits(REFERENCE, params))
                    if worth_storing(ref, data[start : start + cover]):
                        take = start - pos
                        break
            pos += take

        flush_pool(n)
        return out

    # -- emission ----------------------------------------------------------
    def pack(self, data: bytes) -> bytes:
        self.segments = []
        self.probe_count = 0
        self.scan_seconds = self.predict_seconds = 0.0
        size = len(data)
        if size > 0xFFFFFFFF:
            raise ValueError("input exceeds the SXZ1 size field")
        crc = zlib.crc32(data) & 0xFFFFFFFF

        if size == 0:
            return HEADER.pack(MAGIC, VERSION, FLAG_STORED, 0, 0, 0)

        if self.scan_budget == 0:
            segs = []
        else:
            start = perf_counter()
            segs = self._segment(data)
            self.scan_seconds = perf_counter() - start
        if len(segs) > 0xFFFF:
            segs = []  # not representable in SXZ1; only whole-file modes
        if len(segs) == 1 and segs[0][0] == "deflate":
            segs = []  # the corresponding whole-file modes have less overhead
        body = bytearray()
        for seg in segs:
            if seg[0] == "deflate":
                chunk: bytes = seg[1]
                comp = zlib.compress(chunk, self.level)
                if SEG_DEFLATE.size + len(comp) < SEG_RAW.size + len(chunk):
                    body += SEG_DEFLATE.pack(CODEC_DEFLATE, len(chunk), len(comp))
                    body += comp
                    self.segments.append(SegmentInfo(CODEC_DEFLATE, len(chunk), "deflate", SEG_DEFLATE.size + len(comp)))
                else:
                    body += SEG_RAW.pack(CODEC_RAW, len(chunk))
                    body += chunk
                    self.segments.append(SegmentInfo(CODEC_RAW, len(chunk), "raw", SEG_RAW.size + len(chunk)))
            else:
                _, usize, tid, mid, params = seg
                model = MODEL_BY_ID[mid]
                w = BitWriter()
                model.encode(w, params)
                param_bytes = w.to_bytes()
                body += SEG_FORMULA.pack(CODEC_FORMULA, usize, tid, mid, w.bit_length)
                body += param_bytes
                detail = f"{model.describe(params)} t={TRANSFORM_BY_ID[tid].name} p={w.bit_length}b"
                self.segments.append(SegmentInfo(CODEC_FORMULA, usize, detail, FORMULA_HEADER_BYTES + len(param_bytes)))

        whole_deflate = HEADER.pack(MAGIC, VERSION, FLAG_DEFLATE, size, 0, crc) + zlib.compress(data, self.level)
        raw = HEADER.pack(MAGIC, VERSION, FLAG_STORED, size, 0, crc) + data

        # Never be worse than zlib by more than the 16 byte header.
        choices = []
        if segs:
            header = HEADER.pack(MAGIC, VERSION, FLAG_STRUCTURED, size, len(segs), crc)
            choices.append((header + body, self.segments))
        choices += [
            (whole_deflate, [SegmentInfo(CODEC_DEFLATE, size, "deflate-whole", len(whole_deflate) - HEADER.size)]),
            (raw, [SegmentInfo(CODEC_RAW, size, "stored", size)]),
        ]
        if self.experimental_models:
            start = perf_counter()
            header = HEADER.pack(MAGIC, VERSION, FLAG_STRUCTURED, size, 1, crc)
            layout = wav_layout(data)
            if layout is not None:
                limit = min(len(blob) for blob, _ in choices) - HEADER.size - SEG_PCM.size
                chosen = pack_pcm(data, layout, self.level, limit)
                if chosen is not None:
                    mode, comp = chosen
                    segment = SEG_PCM.pack(CODEC_PCM, size, len(comp), mode) + comp
                    choices.append((header + segment, [SegmentInfo(CODEC_PCM, size, pcm_mode_name(mode), len(segment))]))
            elif pnm_layout(data) is not None:
                for mode, name in enumerate(PREDICTORS):
                    comp = zlib.compress(predict_pnm(data, mode), self.level)
                    segment = SEG_PNM.pack(CODEC_PNM, size, len(comp), mode) + comp
                    choices.append((header + segment, [SegmentInfo(CODEC_PNM, size, name, len(segment))]))
            self.predict_seconds = perf_counter() - start

        blob, self.segments = min(choices, key=lambda item: len(item[0]))
        if self.trace is not None:
            self.choices = [(len(candidate[0]), candidate[1][0].detail if candidate[1] else "")
                            for candidate in choices]
        return bytes(blob)


def _parse_header(blob: bytes) -> tuple[int, int, int, int, int]:
    if len(blob) < HEADER.size:
        raise ValueError("not a SINUXZ file (too short)")
    magic, version, flags, size, nseg, crc = HEADER.unpack_from(blob, 0)
    if magic != MAGIC:
        raise ValueError("not a SINUXZ file (bad magic)")
    if version != VERSION:
        raise ValueError(f"unsupported version {version}")

    if flags not in (FLAG_STORED, FLAG_DEFLATE, FLAG_STRUCTURED):
        raise ValueError("invalid header flags")
    if flags == FLAG_STRUCTURED and not 1 <= nseg <= size:
        raise ValueError("invalid structured segment count")
    if flags != FLAG_STRUCTURED and nseg:
        raise ValueError("unexpected segment count")
    if flags == FLAG_STORED and len(blob) != HEADER.size + size:
        raise ValueError("stored size mismatch")
    return version, flags, size, nseg, crc


def _records(blob: bytes, size: int, nseg: int):
    layouts = {
        CODEC_RAW: SEG_RAW, CODEC_DEFLATE: SEG_DEFLATE, CODEC_FORMULA: SEG_FORMULA,
        CODEC_PNM: SEG_PNM, CODEC_PCM: SEG_PCM,
    }
    pos = HEADER.size
    for _ in range(nseg):
        if pos >= len(blob):
            raise ValueError("truncated segment list")
        codec = blob[pos]
        layout = layouts.get(codec)
        if layout is None:
            raise ValueError(f"unknown codec {codec}")
        if pos + layout.size > len(blob):
            raise ValueError("truncated segment header")
        _, usize, *params = layout.unpack_from(blob, pos)
        if not 1 <= usize <= size:
            raise ValueError("invalid segment size")
        size -= usize
        start = pos + layout.size
        if codec == CODEC_RAW:
            length = usize
        elif codec == CODEC_FORMULA:
            length = (params[2] + 7) // 8
        else:
            length = params[0]
        if start + length > len(blob):
            raise ValueError("truncated segment payload")
        yield codec, usize, params, blob[start : start + length], layout.size + length
        pos = start + length
    if size or pos != len(blob):
        raise ValueError("structured size mismatch")


def _inflate(payload: bytes, size: int, *, dictionary: bytes | None = None) -> bytes:
    inflater = zlib.decompressobj() if dictionary is None else zlib.decompressobj(zdict=dictionary)
    try:
        data = inflater.decompress(payload, size + 1)
    except zlib.error as exc:
        raise ValueError("invalid deflate payload") from exc
    if len(data) != size or not inflater.eof or inflater.unused_data:
        raise ValueError("deflate size or stream boundary mismatch")
    return data


def _formula(params: list[int], payload: bytes, size: int):
    tid, mid, param_bits = params
    model = MODEL_BY_ID.get(mid)
    transform = TRANSFORM_BY_ID.get(tid)
    if model is None or transform is None:
        raise ValueError(f"unknown model/transform {mid}/{tid}")
    reader = BitReader(payload, param_bits)
    try:
        values = model.decode(reader)
    except EOFError as exc:
        raise ValueError("truncated formula parameters") from exc
    if reader.remaining():
        raise ValueError("unexpected formula parameters")
    if model is REFERENCE and (tid != 0 or values[1] + size > REFERENCE_SIZE):
        raise ValueError("invalid constant slice")
    return model, transform, values


def unpack(blob: bytes, verify: bool = True) -> bytes:
    _, flags, size, nseg, crc = _parse_header(blob)
    if flags == FLAG_STORED:
        data = blob[HEADER.size :]
    elif flags == FLAG_DEFLATE:
        data = _inflate(blob[HEADER.size :], size)
    else:
        out = bytearray()
        for codec, usize, params, payload, _ in _records(blob, size, nseg):
            if codec == CODEC_RAW:
                out += payload
            elif codec == CODEC_DEFLATE:
                out += _inflate(payload, usize)
            elif codec == CODEC_PNM:
                out += predict_pnm(_inflate(payload, usize), params[1], inverse=True)
            elif codec == CODEC_PCM:
                out += restore_pcm(_inflate(payload, usize), params[1])
            else:
                model, transform, values = _formula(params, payload, usize)
                tb = bits_to_bytes(model.gen(values, usize * 8))
                out += transform.inverse(tb)
        data = bytes(out)

    if verify and (zlib.crc32(data) & 0xFFFFFFFF) != crc:
        raise ValueError("crc mismatch")
    return data


def inspect(blob: bytes) -> dict:
    version, flags, size, nseg, _ = _parse_header(blob)

    info: dict = {
        "version": version,
        "flags": flags,
        "original_size": size,
        "stored_size": len(blob),
        "segments": [],
        "formula_bytes": 0,
        "formula_ratio_percent": 0.0,
        "residual_bytes": 0,
        "codec_counts": {},
        "overhead_bytes": len(blob) - size,
    }
    if size:
        info["ratio"] = len(blob) / size
        info["saving_percent"] = 100 * (1 - len(blob) / size)

    if flags & (FLAG_STORED | FLAG_DEFLATE):
        kind = "stored" if flags & FLAG_STORED else "deflate-whole"
        info["codec_counts"][kind] = 1
        info["segments"].append({"codec": kind, "offset": 0, "size": size, "cost_bytes": len(blob) - HEADER.size})
        return info

    counts = info["codec_counts"]
    offset = 0
    for codec, usize, params, payload, cost in _records(blob, size, nseg):
        detail = ""
        if codec == CODEC_RAW:
            kind = "raw"
        elif codec == CODEC_DEFLATE:
            kind = "deflate"
        elif codec == CODEC_PNM:
            if params[1] >= len(PREDICTORS):
                raise ValueError("unknown PNM predictor")
            kind = "pnm-residual"
            detail = PREDICTORS[params[1]]
            info["residual_bytes"] += usize
        elif codec == CODEC_PCM:
            kind = "pcm-residual"
            detail = pcm_mode_name(params[1])
            info["residual_bytes"] += usize
        else:
            model, transform, values = _formula(params, payload, usize)
            kind = "formula"
            detail = f"{model.describe(values)}/{transform.name} {params[2]}b"
            info["formula_bytes"] += usize
        counts[kind] = counts.get(kind, 0) + 1
        info["segments"].append({"codec": kind, "offset": offset, "size": usize, "detail": detail, "cost_bytes": cost})
        offset += usize
    info["formula_ratio_percent"] = 100 * info["formula_bytes"] / size if size else 0.0
    return info
