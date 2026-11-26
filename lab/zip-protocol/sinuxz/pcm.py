"""Reversible predictors for 16-bit integer mono/stereo RIFF/WAVE.

Each block of 4096 frames resets its predictor. Within a block the stored
planes are channel-major, low byte then high byte. All word arithmetic is
modulo 2**16; no floating-point behavior enters the format.
"""

from __future__ import annotations

import struct
import sys
import zlib
from array import array
from dataclasses import dataclass
from typing import Callable, Iterator

BLOCK_FRAMES = 4096
MASK = 65535
SIGN = 32768
MODE_COUNT = 12


@dataclass(frozen=True)
class PCMLayout:
    start: int
    end: int
    channels: int

    @property
    def block_bytes(self) -> int:
        return BLOCK_FRAMES * self.channels * 2


def wav_layout(data: bytes) -> PCMLayout | None:
    return read_wav_layout(len(data), lambda start, n: data[start:start + n])


def read_wav_layout(size: int, read_at: Callable[[int, int], bytes]) -> PCMLayout | None:
    """Parse just the RIFF/chunk headers; sample bytes need not be in memory."""
    header = read_at(0, 12) if size >= 12 else b""
    if len(header) != 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        return None
    if struct.unpack_from("<I", header, 4)[0] + 8 != size:
        return None
    pos = 12
    audio = channels = None
    while pos + 8 <= size:
        tag, length = struct.unpack("<4sI", read_at(pos, 8))
        start = pos + 8
        end = start + length
        pos = end + (length & 1)
        if pos > size:
            return None
        if tag == b"fmt ":
            if channels is not None or length < 16:
                return None
            code, channels, rate, speed, align, bits = struct.unpack("<HHIIHH", read_at(start, 16))
            if code != 1 or channels not in (1, 2) or bits != 16:
                return None
            if align != channels * 2 or rate == 0 or speed != rate * align:
                return None
        elif tag == b"data":
            if audio is not None:
                return None
            audio = start, end
    if pos != size or channels is None or audio is None:
        return None
    start, end = audio
    if start == end or (end - start) % (channels * 2):
        return None
    return PCMLayout(start, end, channels)


def mode_name(mode: int) -> str:
    if not 0 <= mode < MODE_COUNT:
        raise ValueError("unknown PCM predictor")
    mode_group, order = divmod(mode, 3)
    stereo = "mid-side/" if mode_group & 2 else ""
    signed = "/zigzag" if mode_group & 1 else ""
    return f"{stereo}delta{order}/planes{signed}"


def _mode(mode: int, channels: int) -> tuple[int, bool, bool]:
    if not 0 <= mode < (MODE_COUNT if channels == 2 else MODE_COUNT // 2):
        raise ValueError("invalid PCM predictor for the number of channels")
    group, order = divmod(mode, 3)
    return order, bool(group & 1), bool(group & 2)


def _words(data: bytes | memoryview | bytearray) -> array:
    out = array("H")
    out.frombytes(data)
    if sys.byteorder != "little":
        out.byteswap()
    return out


def _word_bytes(words: array) -> bytes:
    if sys.byteorder != "little":
        words = words[:]
        words.byteswap()
    return words.tobytes()


def _signed(word: int) -> int:
    return (word ^ SIGN) - SIGN


def _difference(words: array) -> array:
    return array("H", _differences(words))


def _differences(words: array) -> Iterator[int]:
    prev = 0
    for word in words:
        yield (word - prev) & MASK
        prev = word


def _encode_block(block: memoryview, channels: int, params: tuple[int, bool, bool]) -> bytes:
    order, fold, mid_side = params
    words = _words(block)
    streams = [words] if channels == 1 else [words[::2], words[1::2]]
    if mid_side:
        left, right = streams
        side = array("H", ((r - l) & MASK for l, r in zip(left, right)))
        mid = array("H", ((l + (_signed(s) // 2)) & MASK for l, s in zip(left, side)))
        streams = [mid, side]
    planes = []
    for stream in streams:
        for _ in range(order):
            stream = _difference(stream)
        if fold:
            stream = array("H", (((word << 1) & MASK) ^ (MASK if word & SIGN else 0) for word in stream))
        packed = _word_bytes(stream)
        planes.extend((packed[::2], packed[1::2]))
    return b"".join(planes)


def _decode_block(block: memoryview, channels: int, params: tuple[int, bool, bool]) -> bytes:
    order, fold, mid_side = params
    count = len(block) // (channels * 2)
    streams = []
    for start in range(0, len(block), count * 2):
        packed = bytearray(count * 2)
        packed[::2] = block[start : start + count]
        packed[1::2] = block[start + count : start + count * 2]
        stream = _words(packed)
        if fold:
            stream = array("H", (((word >> 1) ^ -(word & 1)) & MASK for word in stream))
        for _ in range(order):
            prev = 0
            for i, word in enumerate(stream):
                prev = (prev + word) & MASK
                stream[i] = prev
        streams.append(stream)
    if channels == 1:
        return _word_bytes(streams[0])
    left, right = streams
    if mid_side:
        for i, (mid, side) in enumerate(zip(left, right)):
            original_left = (mid - (_signed(side) // 2)) & MASK
            left[i] = original_left
            right[i] = (original_left + side) & MASK
    words = array("H", [0]) * (2 * count)
    words[::2], words[1::2] = left, right
    return _word_bytes(words)


def restore_pcm(data: bytes, mode: int) -> bytes:
    layout = wav_layout(data)
    if layout is None:
        raise ValueError("invalid PCM residual layout")
    return restore_pcm_payload(data, layout, mode)


def restore_pcm_payload(data: bytes, layout: PCMLayout, mode: int) -> bytes:
    params = _mode(mode, layout.channels)
    out = bytearray(data)
    view = memoryview(data)
    for pos in range(layout.start, layout.end, layout.block_bytes):
        end = min(pos + layout.block_bytes, layout.end)
        out[pos:end] = _decode_block(view[pos:end], layout.channels, params)
    return bytes(out)


def pack_pcm(data: bytes, layout: PCMLayout, level: int, limit: int) -> tuple[int, bytes] | None:
    """Rank modes on up to five blocks; fully compress at most the best two.

    ``limit`` is an exclusive bound on compressed payload bytes. Compare the
    actual emitted lengths, not the sampled scores, before selecting a mode.
    """
    view = memoryview(data)
    size = layout.block_bytes
    blocks = (layout.end - layout.start + size - 1) // size
    sample_ids = sorted({i * (blocks - 1) // 4 for i in range(5)})
    samples = [view[layout.start + i * size : min(layout.end, layout.start + (i + 1) * size)]
               for i in sample_ids]
    ranked = []
    for mode in range(MODE_COUNT if layout.channels == 2 else MODE_COUNT // 2):
        params = _mode(mode, layout.channels)
        cost = sum(len(zlib.compress(_encode_block(block, layout.channels, params), level)) for block in samples)
        ranked.append((cost, mode))

    best = None
    for _, mode in sorted(ranked)[:2]:
        params = _mode(mode, layout.channels)
        enc = zlib.compressobj(level)
        out = bytearray(enc.compress(view[:layout.start]))
        for pos in range(layout.start, layout.end, size):
            block = view[pos : min(pos + size, layout.end)]
            out += enc.compress(_encode_block(block, layout.channels, params))
            if len(out) >= limit:
                break
        else:
            out += enc.compress(view[layout.end:])
            out += enc.flush()
            if len(out) < limit:
                best = mode, bytes(out)
                limit = len(out)
    return best
