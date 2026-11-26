"""SXZ2: independently bounded frames and an optional verified size-gated layer."""

from __future__ import annotations

import shutil
import struct
import tempfile
import zlib
from collections import Counter, deque
from dataclasses import dataclass, field
from time import perf_counter
from typing import BinaryIO, Iterator

from .container import CODEC_FORMULA, FLAG_DEFLATE, FLAG_STORED, HEADER as SXZ1_HEADER
from .container import Packer, _inflate, _parse_header, unpack
from .pcm import PCMLayout, pack_pcm, read_wav_layout, restore_pcm_payload
from .predictors import PREDICTORS, pnm_layout, predict_pixels

MAGIC = b"SXZ2"
VERSION = 1
NESTED = 1
BRIDGE = 2
HEADER = struct.Struct("<4sBBIB")
FRAME = struct.Struct("<BIII")
FOOTER = struct.Struct("<QII")
PNM_PARAMS = struct.Struct("<IBB")
MAX_CHUNK = 16 << 20
MAX_CACHE = 64 << 20
RAW, DEFLATE, SXZ1, COPY, PCM, PNM, DEFLATE_DICT = range(7)
END = 255
CODECS = ("raw", "deflate", "sxz1", "copy", "pcm", "pnm", "deflate-dict")
DICT_SIZE = 32768


def _bounds(chunk_size: int, lookback: int) -> None:
    if not 16 <= chunk_size <= MAX_CHUNK:
        raise ValueError("chunk size must be 16 bytes to 16 MiB")
    if not 0 <= lookback <= 32 or lookback * chunk_size > MAX_CACHE:
        raise ValueError("lookback must be 0..32 frames with a cache of at most 64 MiB")


@dataclass(frozen=True)
class StreamOptions:
    chunk_size: int = 1 << 20
    lookback: int = 4
    scan_budget: int = 32
    level: int = 6
    experimental_models: bool = False
    bridge: bool = False
    fast_sample: bool = False

    def __post_init__(self) -> None:
        _bounds(self.chunk_size, self.lookback)
        if not 0 <= self.level <= 9 or self.scan_budget < 0:
            raise ValueError("expected Deflate level 0..9 and a nonnegative per-frame scan budget")


@dataclass
class StreamStats:
    original_size: int = 0
    stored_size: int = HEADER.size + 1 + FOOTER.size
    frames: int = 0
    codecs: Counter = field(default_factory=Counter)
    probes: int = 0
    scan_seconds: float = 0.0
    formula_bytes: int = 0

    def add(self, codec: int, size: int, length: int) -> None:
        self.original_size += size
        self.stored_size += FRAME.size + length
        self.frames += 1
        self.codecs[CODECS[codec]] += 1


@dataclass
class PackResult:
    first: StreamStats
    second: StreamStats | None = None
    first_seconds: float = 0.0
    second_seconds: float = 0.0

    @property
    def nested(self) -> bool:
        return self.second is not None and self.second.stored_size < self.first.stored_size

    @property
    def stored_size(self) -> int:
        return self.second.stored_size if self.nested else self.first.stored_size


def _read(src: BinaryIO, count: int) -> bytes:
    data = src.read(count)
    if not data or len(data) == count:
        return data
    # Buffered files normally return the whole request. Also support short reads.
    parts = bytearray(data)
    while len(parts) < count:
        part = src.read(count - len(parts))
        if not part:
            break
        parts += part
    return bytes(parts)


def _exact(src: BinaryIO, count: int) -> bytes:
    data = _read(src, count)
    if len(data) != count:
        raise ValueError("truncated SXZ2 stream or input range")
    return data


def _ranges(src: BinaryIO, length: int, stride: int, hint: tuple) -> Iterator[tuple[bytes, tuple]]:
    while length:
        take = min(length, stride)
        yield _exact(src, take), hint
        length -= take


def _chunks(src: BinaryIO, options: StreamOptions) -> Iterator[tuple[bytes, tuple]]:
    cap = options.chunk_size
    if options.experimental_models and src.seekable():
        origin = src.tell()
        size = src.seek(0, 2) - origin

        def read_at(offset: int, count: int) -> bytes:
            src.seek(origin + offset)
            return _exact(src, count)

        pcm = read_wav_layout(size, read_at)
        pnm = None if pcm else pnm_layout(read_at(0, min(size, 257)), size)
        src.seek(origin)
        if pcm is not None:
            align = 2 * pcm.channels
            yield from _ranges(src, pcm.start, cap, ())
            yield from _ranges(src, pcm.end - pcm.start, cap // align * align, (PCM, pcm.channels))
            yield from _ranges(src, size - pcm.end, cap, ())
        elif pnm is not None and pnm[1] <= cap:
            start, row, channels = pnm
            yield from _ranges(src, start, cap, ())
            yield from _ranges(src, size - start, cap // row * row, (PNM, row, channels))
        else:
            while data := _read(src, cap):
                yield data, ()
            return
        if src.read(1):
            raise ValueError("typed input size changed during packing")
    else:
        while data := _read(src, cap):
            yield data, ()


def _baseline(data: bytes, level: int) -> tuple[int, bytes]:
    comp = zlib.compress(data, level)
    return (DEFLATE, comp) if len(comp) < len(data) else (RAW, data)


def _encode(
    data: bytes, hint: tuple, options: StreamOptions, packer: Packer, stats: StreamStats,
) -> tuple[int, bytes]:
    if options.fast_sample and not hint and not options.scan_budget and len(data) >= 256 * 1024:
        # Conservative speed heuristic, not an entropy proof. Keep near-random
        # frames raw rather than spending another full Deflate pass on them.
        size = 16 * 1024
        for start in (0, len(data) // 2, len(data) - size):
            if len(zlib.compress(data[start : start + size], 1)) < size * 0.992:
                break
        else:
            return RAW, data
    if not hint and options.scan_budget:
        archive = packer.pack(data)
        stats.probes += packer.probe_count
        stats.scan_seconds += packer.scan_seconds
        flag = archive[5]
        if flag == FLAG_STORED:
            return RAW, data
        if flag == FLAG_DEFLATE:
            return DEFLATE, archive[SXZ1_HEADER.size:]
        normal = _baseline(data, options.level)
        if len(archive) < len(normal[1]):
            stats.formula_bytes += sum(seg.size for seg in packer.segments if seg.codec == CODEC_FORMULA)
            return SXZ1, archive
        return normal

    normal = _baseline(data, options.level)
    if not hint:
        return normal
    if hint[0] == PCM:
        channels = hint[1]
        chosen = pack_pcm(data, PCMLayout(0, len(data), channels), options.level, len(normal[1]) - 1)
        if chosen is not None:
            mode, payload = chosen
            return PCM, bytes([((channels - 1) << 4) | mode]) + payload
    else:
        _, row, channels = hint
        # Rank on adjacent rows at three positions, then encode one candidate in full.
        rows = len(data) // row
        sample_rows = min(8, rows, max(1, 32768 // row))
        sample_offsets = {0, (rows - sample_rows) // 2, rows - sample_rows}
        samples = [data[i * row : (i + sample_rows) * row] for i in sorted(sample_offsets)]
        mode = min(range(len(PREDICTORS)), key=lambda m: sum(
            len(zlib.compress(predict_pixels(sample, row, channels, m), options.level)) for sample in samples
        ))
        residual = zlib.compress(predict_pixels(data, row, channels, mode), options.level)
        if PNM_PARAMS.size + len(residual) < len(normal[1]):
            return PNM, PNM_PARAMS.pack(row, channels, mode) + residual
    return normal


def _encode_stream(src: BinaryIO, dst: BinaryIO, options: StreamOptions, *, nested: bool) -> StreamStats:
    stats = StreamStats()
    flags = (NESTED if nested else 0) | (BRIDGE if options.bridge else 0)
    dst.write(HEADER.pack(MAGIC, VERSION, flags, options.chunk_size, options.lookback))
    packer = Packer(max_window=128, extend_bytes=65536, scan_budget=options.scan_budget,
                    experimental_models=options.experimental_models, level=options.level)
    history: deque[tuple[int, bytes]] = deque(maxlen=options.lookback)
    tail = b""
    checksum = 0
    for data, hint in _chunks(src, options):
        crc = zlib.crc32(data)
        distance = next((i for i, (old_crc, old) in enumerate(reversed(history), 1)
                         if old_crc == crc and old == data), 0)
        if distance and len(data) > 1:
            codec, payload = COPY, bytes([distance])
        else:
            formula_before = stats.formula_bytes
            codec, payload = _encode(data, hint, options, packer, stats)
            if tail:
                encoder = zlib.compressobj(options.level, zdict=tail)
                bridged = encoder.compress(data) + encoder.flush()
                if len(bridged) < len(payload):
                    codec, payload = DEFLATE_DICT, bridged
                    # Formula statistics describe emitted frames, not discarded candidates.
                    stats.formula_bytes = formula_before
        dst.write(FRAME.pack(codec, len(data), len(payload), crc))
        dst.write(payload)
        checksum = zlib.crc32(data, checksum)
        stats.add(codec, len(data), len(payload))
        history.append((crc, data))
        if options.bridge:
            tail = data[-DICT_SIZE:]
    if stats.frames > 0xFFFFFFFF or stats.original_size > 0xFFFFFFFFFFFFFFFF:
        raise ValueError("SXZ2 size fields exceeded")
    dst.write(bytes([END]) + FOOTER.pack(stats.original_size, checksum, stats.frames))
    return stats


def pack_stream(
    src: BinaryIO, dst: BinaryIO, options: StreamOptions = StreamOptions(), *,
    second_pass: bool = False, temp_dir=None,
) -> PackResult:
    """Write the first stream, or try exactly one outer pass and keep the smaller."""
    if not second_pass:
        start = perf_counter()
        first = _encode_stream(src, dst, options, nested=False)
        return PackResult(first, first_seconds=perf_counter() - start)
    with tempfile.TemporaryFile(dir=temp_dir) as inner, tempfile.TemporaryFile(dir=temp_dir) as outer:
        start = perf_counter()
        first = _encode_stream(src, inner, options, nested=False)
        first_seconds = perf_counter() - start
        inner.seek(0)
        start = perf_counter()
        second = _encode_stream(inner, outer, options, nested=True)
        result = PackResult(first, second, first_seconds, perf_counter() - start)
        selected = outer if result.nested else inner
        selected.seek(0)
        shutil.copyfileobj(selected, dst, min(options.chunk_size, 1 << 20))
        return result


def _header(src: BinaryIO) -> tuple[int, int, int]:
    magic, version, flags, chunk_size, lookback = HEADER.unpack(_exact(src, HEADER.size))
    if magic != MAGIC or version != VERSION or flags & ~(NESTED | BRIDGE):
        raise ValueError("invalid SXZ2 magic, version or flags")
    _bounds(chunk_size, lookback)
    return flags, chunk_size, lookback


def _records(src: BinaryIO, cap: int, stats: StreamStats) -> Iterator[tuple[int, int, int, bytes]]:
    while True:
        ident = _exact(src, 1)
        code = ident[0]
        if code == END:
            total, crc, count = FOOTER.unpack(_exact(src, FOOTER.size))
            if (total, count) != (stats.original_size, stats.frames) or src.read(1):
                raise ValueError("SXZ2 footer size, count or boundary mismatch")
            yield END, total, crc, b""
            return
        _, size, length, crc = FRAME.unpack(ident + _exact(src, FRAME.size - 1))
        if not 0 <= code < len(CODECS) or not 0 < size <= cap or not 0 < length <= size:
            raise ValueError("invalid SXZ2 frame type or length")
        if (code == RAW and length != size) or (code == COPY and length != 1):
            raise ValueError("invalid raw or copy frame size")
        if (code == SXZ1 and length < SXZ1_HEADER.size) or (code == PNM and length <= PNM_PARAMS.size):
            raise ValueError("truncated SXZ2 frame description")
        if code == PCM and length < 2:
            raise ValueError("truncated PCM frame")
        stats.add(code, size, length)
        yield code, size, crc, _exact(src, length)


def _decode_frame(code: int, size: int, payload: bytes, history: deque[bytes], tail: bytes) -> bytes:
    if code == RAW:
        return payload
    if code == COPY:
        distance = payload[0]
        if not 1 <= distance <= len(history):
            raise ValueError("invalid SXZ2 frame reference")
        return history[-distance]
    if code == DEFLATE:
        return _inflate(payload, size)
    if code == DEFLATE_DICT:
        if not tail:
            raise ValueError("dictionary frame has no enabled predecessor")
        return _inflate(payload, size, dictionary=tail)
    if code == SXZ1:
        _, _, inner_size, _, _ = _parse_header(payload)
        if inner_size != size:
            raise ValueError("SXZ1 frame declares an unexpected output size")
        return unpack(payload)
    if code == PCM:
        channels, mode = ((payload[0] >> 4) + 1), payload[0] & 15
        if channels not in (1, 2) or size % (channels * 2):
            raise ValueError("invalid PCM frame alignment")
        return restore_pcm_payload(_inflate(payload[1:], size), PCMLayout(0, size, channels), mode)
    row, channels, mode = PNM_PARAMS.unpack_from(payload)
    return predict_pixels(_inflate(payload[PNM_PARAMS.size:], size), row, channels, mode, inverse=True)


def _decode_chunks(
    src: BinaryIO, cap: int, window: int, limit: int | None, bridge: bool, stats: StreamStats,
) -> Iterator[bytes]:
    history: deque[bytes] = deque(maxlen=window)
    checksum = 0
    tail = b""
    for code, size, crc, payload in _records(src, cap, stats):
        if code == END:
            if crc != checksum:
                raise ValueError("SXZ2 stream checksum mismatch")
            break
        if limit is not None and stats.original_size > limit:
            raise ValueError("SXZ2 output exceeds configured limit")
        data = _decode_frame(code, size, payload, history, tail)
        if len(data) != size or zlib.crc32(data) != crc:
            raise ValueError("SXZ2 frame size or checksum mismatch")
        checksum = zlib.crc32(data, checksum)
        history.append(data)
        if bridge:
            tail = data[-DICT_SIZE:]
        yield data


def _decode_records(
    src: BinaryIO, dst: BinaryIO, cap: int, window: int, limit: int | None, bridge: bool,
) -> StreamStats:
    stats = StreamStats()
    for data in _decode_chunks(src, cap, window, limit, bridge, stats):
        dst.write(data)
    return stats


def unpack_stream(src: BinaryIO, dst: BinaryIO, *, max_output: int | None = None, temp_dir=None) -> StreamStats:
    """Decode SXZ2, removing at most one outer layer. Use atomic output for files."""
    if max_output is not None and max_output < 0:
        raise ValueError("max_output must be nonnegative")
    flags, chunk_size, lookback = _header(src)
    if not flags & NESTED:
        return _decode_records(src, dst, chunk_size, lookback, max_output, bool(flags & BRIDGE))
    with tempfile.TemporaryFile(dir=temp_dir) as inner:
        # Every valid inner frame emits >=1 byte and stores <= that size + its header.
        limit = None if max_output is None else (FRAME.size + 1) * max_output + StreamStats().stored_size
        outer_stats = _decode_records(src, inner, chunk_size, lookback, limit, bool(flags & BRIDGE))
        inner.seek(0)
        inner_flags, inner_chunk, inner_lookback = _header(inner)
        if inner_flags & NESTED:
            raise ValueError("SXZ2 supports only one outer pass")
        stats = _decode_records(inner, dst, inner_chunk, inner_lookback, max_output, bool(inner_flags & BRIDGE))
        stats.stored_size = outer_stats.stored_size
        return stats


def inspect_stream(src: BinaryIO, *, limit: int = 30) -> dict:
    """Summarize outer framing without inflating payloads or keeping all entries."""
    if limit < 0:
        raise ValueError("limit must be nonnegative")
    flags, chunk_size, lookback = _header(src)
    stats = StreamStats()
    entries = []
    for code, size, _, payload in _records(src, chunk_size, stats):
        if code != END and len(entries) < limit:
            entries.append({"codec": CODECS[code], "size": size, "offset": stats.original_size - size,
                            "cost_bytes": FRAME.size + len(payload)})
    return {"format": "SXZ2", "version": VERSION, "nested": bool(flags & NESTED),
            "dictionary_bridge": bool(flags & BRIDGE), "chunk_size": chunk_size,
            "lookback": lookback, "payload_size": stats.original_size, "stored_size": stats.stored_size,
            "frames": stats.frames, "codec_counts": dict(stats.codecs), "segments": entries}
