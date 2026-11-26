"""SXZ4 residual channels: bytes, words, Rice/ZigZag, and causal predictors.

Two families are kept apart:

* generative residual - a model produces ``pred`` from its parameters alone;
  the residual is the difference between ``pred`` and the data.
* causal residual - the predictor only uses already reconstructed values; it
  has no descriptor beyond its kind, and the decoder can replay it exactly.

Every payload is self-describing and its full stored cost (mode byte + length +
payload) is returned so the engine can compare it with Deflate.
"""

from __future__ import annotations

import zlib

EXACT, XOR, MODDIFF, EXCEPTIONS = 0, 1, 2, 3
WORDDIFF = 10
CAUSAL = 20
NAMES = {EXACT: "exact", XOR: "xor", MODDIFF: "moddiff", EXCEPTIONS: "exceptions",
         WORDDIFF: "worddiff+rice", CAUSAL: "causal"}


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7


# ---------------------------------------------------------------------------
# Rice coding
# ---------------------------------------------------------------------------
def _zigzag(value: int) -> int:
    return (value << 1) if value >= 0 else ((-value << 1) - 1)


def _unzigzag(value: int) -> int:
    return (value >> 1) if not value & 1 else -((value + 1) >> 1)


def rice_size(values: list[int], k: int) -> int:
    return sum((value >> k) + 1 + k for value in values)


def rice_encode(values: list[int], k: int) -> bytes:
    out = bytearray()
    acc = count = 0
    for value in values:
        quotient = value >> k
        for _ in range(quotient):
            acc = (acc << 1) | 1
            count += 1
            if count == 8:
                out.append(acc); acc = count = 0
        acc <<= 1
        count += 1
        if count == 8:
            out.append(acc); acc = count = 0
        for shift in range(k - 1, -1, -1):
            acc = (acc << 1) | ((value >> shift) & 1)
            count += 1
            if count == 8:
                out.append(acc); acc = count = 0
    if count:
        out.append(acc << (8 - count))
    return bytes(out)


def rice_decode(data: bytes, count: int, k: int) -> list[int]:
    values = []
    bit = [0]

    def take() -> int:
        index = bit[0]
        if index >= len(data) * 8:
            raise ValueError("truncated rice stream")
        bit[0] += 1
        return (data[index >> 3] >> (7 - (index & 7))) & 1

    for _ in range(count):
        quotient = 0
        while take():
            quotient += 1
            if quotient > (1 << 26):
                raise ValueError("rice quotient too large")
        remainder = 0
        for _ in range(k):
            remainder = (remainder << 1) | take()
        values.append((quotient << k) | remainder)
    return values


def _best_rice(values: list[int], max_k: int = 32) -> tuple[int, bytes]:
    """Best Rice parameter. ``max_k`` must cover the word width (64 for u64)."""
    max_k = min(max_k, 64)
    best = None
    for k in range(0, max_k + 1):
        size = rice_size(values, k)
        if best is None or size < best[0]:
            best = (size, k)
    k = best[1]
    return k, rice_encode(values, k)


# ---------------------------------------------------------------------------
# Byte residuals
# ---------------------------------------------------------------------------
def encode_exceptions(pred: bytes, actual: bytes) -> bytes:
    out = bytearray()
    previous = count = 0
    for index, (p, a) in enumerate(zip(pred, actual)):
        if p != a:
            out += varint(index - previous)
            out.append(a)
            previous = index
            count += 1
    return varint(count) + bytes(out)


def decode_exceptions(pred: bytearray, blob: bytes) -> None:
    count, pos = read_varint(blob, 0)
    index = 0
    for _ in range(count):
        delta, pos = read_varint(blob, pos)
        if pos >= len(blob):
            raise ValueError("truncated exception")
        index += delta
        if index >= len(pred):
            raise ValueError("exception outside span")
        pred[index] = blob[pos]
        pos += 1


def cost(payload: bytes) -> int:
    return 1 + len(varint(len(payload))) + len(payload)


def best_byte(pred: bytes, actual: bytes, level: int = 6) -> tuple[int, bytes, int]:
    if pred == actual:
        return EXACT, b"", 1
    xor = zlib.compress(bytes(a ^ p for p, a in zip(pred, actual)), level)
    diff = zlib.compress(bytes((a - p) & 0xFF for p, a in zip(pred, actual)), level)
    exceptions = zlib.compress(encode_exceptions(pred, actual), level)
    options = [(XOR, xor), (MODDIFF, diff), (EXCEPTIONS, exceptions)]
    mode, payload = min(options, key=lambda item: len(item[1]))
    return mode, payload, cost(payload)


def apply_byte(pred: bytes, mode: int, payload: bytes) -> bytes:
    if mode == EXACT:
        return pred
    if mode == XOR:
        residual = zlib.decompress(payload)
        if len(residual) != len(pred):
            raise ValueError("xor residual size mismatch")
        return bytes(p ^ r for p, r in zip(pred, residual))
    if mode == MODDIFF:
        residual = zlib.decompress(payload)
        if len(residual) != len(pred):
            raise ValueError("moddiff residual size mismatch")
        return bytes((p + r) & 0xFF for p, r in zip(pred, residual))
    if mode == EXCEPTIONS:
        out = bytearray(pred)
        decode_exceptions(out, zlib.decompress(payload))
        return bytes(out)
    raise ValueError(f"not a byte residual mode: {mode}")


# ---------------------------------------------------------------------------
# Word residuals and causal predictors
# ---------------------------------------------------------------------------
def words_of(data: bytes, width: int, order: str) -> list[int]:
    return [int.from_bytes(data[i : i + width], order)
            for i in range(0, len(data) - len(data) % width, width)]


def worddiff(pred: bytes, actual: bytes, width: int, order: str) -> tuple[int, int, bytes] | None:
    if len(pred) < width or len(actual) != len(pred):
        return None
    bits = 8 * width
    mask = (1 << bits) - 1
    a = words_of(pred, width, order)
    b = words_of(actual, width, order)
    if not a:
        return None
    diffs = []
    for x, y in zip(a, b):
        delta = (y - x) & mask
        if delta >= (1 << (bits - 1)):
            delta -= (1 << bits)
        diffs.append(_zigzag(delta))
    best = _best_rice(diffs, bits)
    k, payload_bits = best
    tail = len(actual) - len(b) * width
    payload = varint(len(diffs)) + bytes([k]) + payload_bits
    if tail:
        payload += actual[-tail:]
    if len(payload) >= len(actual):
        return None
    return width, k, payload


def apply_worddiff(pred: bytes, width: int, order: str, k: int, payload: bytes) -> bytes:
    bits = 8 * width
    mask = (1 << bits) - 1
    a = words_of(pred, width, order)
    count, pos = read_varint(payload, 0)
    if count != len(a):
        raise ValueError("word residual count mismatch")
    k = payload[pos]
    tail = len(pred) - len(a) * width
    body_end = len(payload) - tail if tail else len(payload)
    values = rice_decode(payload[pos + 1 : body_end], count, k)
    out = bytearray()
    for word, value in zip(a, values):
        delta = _unzigzag(value)
        out += ((word + delta) & mask).to_bytes(width, order)
    if tail:
        out += payload[body_end:]
    else:
        out += pred[len(out):]
    return bytes(out)


def causal_predict(history: list[int], start: int, count: int, width: int, kind: int, mask: int) -> list[int]:
    """Predict ``count`` words from the last two reconstructed values."""
    out = []
    x1, x2 = history[-1] if len(history) > 0 else 0, history[-2] if len(history) > 1 else 0
    for _ in range(count):
        if kind == 0:
            pred = 0
        elif kind == 1:
            pred = x1
        elif kind == 2:
            pred = (2 * x1 - x2) & mask
        else:
            raise ValueError("unknown causal predictor")
        out.append(pred)
        x2, x1 = x1, pred
    return out


def causal_encode(data: bytes, start: int, length: int, width: int, order: str,
                  kind: int) -> tuple[int, int, bytes] | None:
    if length < width or length % width:
        return None
    bits = 8 * width
    mask = (1 << bits) - 1
    words = words_of(data[start : start + length], width, order)
    if len(words) < 3:
        return None
    history = words_of(data[max(0, start - 2 * width) : start], width, order)[-2:]
    x1 = history[-1] if history else 0
    x2 = history[-2] if len(history) > 1 else 0
    diffs = []
    for word in words:
        pred = 0 if kind == 0 else x1 if kind == 1 else (2 * x1 - x2) & mask
        delta = (word - pred) & mask
        if delta >= (1 << (bits - 1)):
            delta -= (1 << bits)
        diffs.append(_zigzag(delta))
        x2, x1 = x1, word
    best = _best_rice(diffs, bits)
    k, payload_bits = best
    payload = varint(len(diffs)) + bytes([k]) + payload_bits
    if len(payload) >= length:
        return None
    return kind, k, payload


def apply_causal(buffer: bytearray, start: int, length: int, width: int, order: str,
                 kind: int, payload: bytes) -> None:
    bits = 8 * width
    mask = (1 << bits) - 1
    count = length // width
    history = words_of(bytes(buffer[max(0, start - 2 * width) : start]), width, order)[-2:]
    pos = 0
    stored, pos = read_varint(payload, 0)
    if stored != count:
        raise ValueError("causal residual count mismatch")
    k = payload[pos]
    values = rice_decode(payload[pos + 1 :], count, k)
    x1, x2 = (history[-1] if history else 0), (history[-2] if len(history) > 1 else 0)
    out = bytearray()
    for value in values:
        if kind == 0:
            pred = 0
        elif kind == 1:
            pred = x1
        elif kind == 2:
            pred = (2 * x1 - x2) & mask
        else:
            raise ValueError("unknown causal predictor")
        word = (pred + _unzigzag(value)) & mask
        out += word.to_bytes(width, order)
        x2, x1 = x1, word
    buffer[start : start + length] = out


def best_causal(data: bytes, start: int, length: int, level: int = 6) -> tuple[dict, int] | None:
    """Try causal predictors; return the cheapest description or None."""
    best = None
    for width in (2, 4):
        if length < 4 * width:
            continue
        for order in ("little", "big"):
            for kind in (1, 2):
                result = causal_encode(data, start, length, width, order, kind)
                if result is None:
                    continue
                _, k, payload = result
                description = bytes([width.bit_length() - 1, 0 if order == "little" else 1, kind, k])
                store = len(description) + len(varint(len(payload))) + len(payload)
                if best is None or store < best[0]:
                    best = (store, {"width": width, "order": order, "kind": kind,
                                    "k": k, "payload": payload, "description": description})
    return best
