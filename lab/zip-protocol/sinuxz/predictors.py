"""Exact spatial predictors for binary, 8-bit PGM/PPM files."""

import re

PREDICTORS = ("left", "above", "paeth")
_HEADER = re.compile(rb"P([56])[ \t\r\n]+([0-9]{1,9})[ \t\r\n]+([0-9]{1,9})[ \t\r\n]+255[ \t\r\n]")


def pnm_layout(data: bytes, size: int | None = None) -> tuple[int, int, int] | None:
    """Return (pixel offset, bytes per row, channels), or no supported layout."""
    match = _HEADER.match(data, 0, 256)
    if not match:
        return None
    kind, width, height = match.groups()
    channels = 1 if kind == b"5" else 3
    row = int(width) * channels
    height = int(height)
    if not row or not height:
        return None
    size = len(data) if size is None else size
    start = match.end()
    # Use the exact image length to disambiguate CRLF from a 0x0a first pixel.
    if data[start - 1 : start + 1] == b"\r\n" and size == start + 1 + row * height:
        start += 1
    if size == start + row * height:
        return start, row, channels
    return None


def _paeth(a: int, b: int, c: int) -> int:
    estimate = a + b - c
    pa, pb, pc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def predict_pnm(data: bytes, mode: int, *, inverse: bool = False) -> bytes:
    """Subtract or add the predictor modulo 256, leaving the header untouched."""
    layout = pnm_layout(data)
    if layout is None or not 0 <= mode < len(PREDICTORS):
        raise ValueError("invalid PNM layout or predictor")
    start, row, channels = layout
    return _predict(data, start, row, channels, mode, inverse)


def predict_pixels(data: bytes, row: int, channels: int, mode: int, *, inverse: bool = False) -> bytes:
    if (channels not in (1, 3) or row < channels or row % channels or len(data) % row
            or not 0 <= mode < len(PREDICTORS)):
        raise ValueError("invalid PNM frame geometry or predictor")
    return _predict(data, 0, row, channels, mode, inverse)


def _predict(data: bytes, start: int, row: int, channels: int, mode: int, inverse: bool) -> bytes:
    out = bytearray(data) if inverse else bytearray(len(data))
    out[:start] = data[:start]
    source = out if inverse else data
    for row_start in range(start, len(data), row):
        has_above = row_start > start
        for i in range(row_start, row_start + row):
            has_left = i - row_start >= channels
            a = source[i - channels] if has_left and mode != 1 else 0
            b = source[i - row] if has_above and mode != 0 else 0
            if mode == 0:
                p = a
            elif mode == 1:
                p = b
            else:
                c = source[i - row - channels] if has_above and has_left else 0
                p = _paeth(a, b, c)
            out[i] = (data[i] + p if inverse else data[i] - p) & 255
    return bytes(out)
