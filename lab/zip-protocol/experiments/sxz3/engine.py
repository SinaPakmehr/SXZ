"""SXZ3 block coder: model + residual, three history architectures.

Architecture A keeps blocks independent (the SXZ2 data flow).
Architecture B extracts formula blocks, concatenates every remaining byte into
one Deflate stream, and keeps a block map plus descriptors on the side.
Architecture C rewrites formula blocks in place with their residual, so a
single Deflate stream sees the whole file and residual context.

All three are byte-exact; the caller verifies.
"""

from __future__ import annotations

import struct
import zlib
import math
from collections import Counter
from dataclasses import dataclass, field

from sinuxz.bitio import BitReader, BitWriter, bits_to_bytes, bytes_to_bits
from sinuxz.models import LfsrModel, XorShiftModel

from experiments.sxz3 import bank, residual

MAGIC = b"SXZ3"
VERSION = 1
ARCH_A, ARCH_B, ARCH_C, ARCH_PLAIN = 0, 1, 2, 3
HEADER = struct.Struct("<4sBBIIQI")
BLOCK = 32768

MODELS = [bank.PeriodBytes(), LfsrModel(), XorShiftModel(),
          bank.AffineWord(), bank.QuadraticWord(), bank.LanesWord(),
          bank.LcgWord(), bank.XorRotWord(), bank.XorShiftAny(), bank.ReferenceSlice()]
BY_ID = {model.mid: model for model in MODELS}


def descriptor(model, params) -> bytes:
    writer = BitWriter()
    model.encode(writer, params)
    bits = writer.bit_length
    return bytes([model.mid, bits & 0xFF, (bits >> 8) & 0xFF]) + writer.to_bytes()


def read_descriptor(blob: bytes, pos: int):
    if pos + 3 > len(blob):
        raise ValueError("truncated model descriptor")
    mid, low, high = blob[pos], blob[pos + 1], blob[pos + 2]
    bits = low | (high << 8)
    length = (bits + 7) // 8
    payload = blob[pos + 3 : pos + 3 + length]
    if len(payload) != length:
        raise ValueError("truncated model parameters")
    model = BY_ID.get(mid)
    if model is None:
        raise ValueError(f"unknown model {mid}")
    reader = BitReader(payload, bits)
    params = model.decode(reader)
    if reader.remaining():
        raise ValueError("unexpected parameter bits")
    return model, params, pos + 3 + length


def predict(model, params, size: int) -> bytes:
    fast = getattr(model, "predict_bytes", None)
    if fast is not None:
        return fast(params, size)
    data = bits_to_bytes(model.gen(params, size * 8))
    if len(data) < size:
        raise ValueError("model produced too few bytes")
    return data[:size]


def _bit_fit(model, block: bytes):
    """Shipped bit-oriented models fit on a prefix of the block."""
    return model.fit(bytes_to_bits(block))


def promising(block: bytes) -> bool:
    """Coarse, cheap screen; the dense bank only runs when this says maybe.

    Random bytes and PRNG output both look entropic, so entropy alone is not
    enough: exact anchors, short periods and a 16-bit affine vote are checked
    first, and they cost about 1 ms per block.
    """
    sample = block[:8192]
    if not sample:
        return False
    if len(block) <= 4096:
        from sinuxz.constants import find_reference

        if find_reference(block, 0, len(block), 18) is not None:
            return True
    short = block[:4096]
    for period in (1, 2, 4, 8, 16, 20, 32):
        if len(short) > period + 256 and all(
                short[i] == short[i - period] for i in range(period, period + 256)):
            return True
    for width, order in ((2, "little"), (2, "big"), (4, "little"), (4, "big"), (8, "little")):
        words = [int.from_bytes(short[i : i + width], order)
                 for i in range(0, min(len(short) - width, 2048), width)]
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
    # Cheap PRNG probes: any of the shipped families, 32 steps is enough.
    from experiments.sxz3.bank import XorShiftAny

    for order in ("big", "little"):
        words = [int.from_bytes(short[i : i + 4], order) for i in range(0, min(len(short), 256), 4)]
        if len(words) >= 32:
            for triple in XorShiftAny.TRIPLES:
                state = words[0]
                matched = True
                for i in range(31):
                    state = XorShiftAny.step(state, triple)
                    if state != words[i + 1]:
                        matched = False
                        break
                if matched:
                    return True
            if len(words) >= 8:
                x0, x1, x2 = words[0], words[1], words[2]
                den = (x1 - x0) & 0xFFFFFFFF
                if den % 2:
                    a = ((x2 - x1) * pow(den, -1, 1 << 32)) & 0xFFFFFFFF
                    c = (x1 - a * x0) & 0xFFFFFFFF
                    if all(((a * words[i] + c) & 0xFFFFFFFF) == words[i + 1] for i in range(7)):
                        return True
    counts = Counter(sample)
    total = len(sample)
    entropy = -sum((n / total) * math.log2(n / total) for n in counts.values())
    groups = {sample[i : i + 4] for i in range(0, max(0, len(sample) - 4), 4)}
    diversity = len(groups) / max(1, len(sample) // 4)
    return entropy < 7.9 or diversity < 0.9


def candidates(block: bytes, level: int = 6, models=None, use_residual: bool = True) -> list[dict]:
    out = []
    for model in (models or MODELS):
        try:
            fits = _bit_fit(model, block) if model.mid in (4, 5) else model.fit_params(block)
        except Exception:
            continue
        for params in fits:
            if getattr(model, "last_score", 1.0) < 0.15:
                continue
            try:
                desc = descriptor(model, params)
                if len(desc) >= len(block) // 2 + 1:
                    continue
                pred = predict(model, params, len(block))
            except Exception:
                continue
            if not use_residual:
                if pred != block:
                    continue
                mode, payload, residual_cost = residual.EXACT, b"", 1
                if len(desc) + 1 >= len(block):
                    continue
            else:
                mode, payload, residual_cost = residual.best(pred, block, level)
            out.append({
                "kind": "model", "model": model.name, "params": params,
                "descriptor": desc, "mode": mode, "payload": payload,
                "predicted": pred, "cost": len(desc) + residual_cost,
                "residual_cost": residual_cost,
            })
    return out


def baseline(block: bytes, level: int = 6) -> dict:
    compressed = zlib.compress(block, level)
    if len(compressed) < len(block):
        return {"kind": "deflate", "payload": compressed, "cost": 1 + len(residual.varint(len(compressed))) + len(compressed)}
    return {"kind": "raw", "payload": block, "cost": 1 + len(block)}


def choose(block: bytes, level: int = 6, models=None, use_residual: bool = True,
           adaptive: bool = False) -> dict:
    best = baseline(block, level)
    if adaptive and not promising(block):
        return best
    for cand in candidates(block, level, models, use_residual):
        if cand["cost"] < best["cost"]:
            best = cand
    return best


@dataclass
class Stats:
    blocks: int = 0
    modelled: int = 0
    formula_bytes: int = 0
    models: dict = field(default_factory=dict)
    modes: dict = field(default_factory=dict)

    def add(self, choice: dict, size: int) -> None:
        self.blocks += 1
        if choice["kind"] == "model":
            self.modelled += 1
            self.formula_bytes += size
            self.models[choice["model"]] = self.models.get(choice["model"], 0) + 1
            name = residual.NAMES[choice["mode"]]
            self.modes[name] = self.modes.get(name, 0) + 1


def _header(arch: int, block: int, blocks: int, size: int, crc: int) -> bytes:
    return HEADER.pack(MAGIC, VERSION, arch, block, blocks, size, crc)


def _plain(data: bytes, level: int, block: int, blocks: int, crc: int) -> bytes:
    """No model paid off: one Deflate stream, no block map at all."""
    compressed = zlib.compress(data, level)
    return (_header(ARCH_PLAIN, block, blocks, len(data), crc)
            + residual.varint(len(compressed)) + compressed)


def pack(data: bytes, arch: int = ARCH_A, block_size: int = BLOCK, level: int = 6,
         models=None, use_residual: bool = True,
         adaptive: bool = False) -> tuple[bytes, Stats]:
    stats = Stats()
    blocks = [data[i : i + block_size] for i in range(0, len(data), block_size)] or [b""]
    crc = zlib.crc32(data) & 0xFFFFFFFF
    if arch == ARCH_A:
        body = bytearray(_header(arch, block_size, len(blocks), len(data), crc))
        for block in blocks:
            choice = choose(block, level, models, use_residual, adaptive)
            stats.add(choice, len(block))
            if choice["kind"] == "raw":
                body.append(0)
                body += block
            elif choice["kind"] == "deflate":
                body.append(1)
                body += residual.varint(len(choice["payload"])) + choice["payload"]
            else:
                body.append(2)
                body += choice["descriptor"]
                body.append(choice["mode"])
                body += residual.varint(len(choice["payload"])) + choice["payload"]
        if stats.modelled == 0:
            return _plain(data, level, block_size, len(blocks), crc), stats
        return bytes(body), stats

    if arch == ARCH_B:
        choices = []
        for block in blocks:
            choice = choose(block, level, models, use_residual, adaptive)
            stats.add(choice, len(block))
            choices.append(choice)
        data_stream = bytearray()
        side = bytearray()
        bitmap = bytearray((len(blocks) + 7) // 8)
        for index, choice in enumerate(choices):
            if choice["kind"] == "model":
                bitmap[index // 8] |= 1 << (index % 8)
                side += choice["descriptor"]
                side.append(choice["mode"])
                side += residual.varint(len(choice["payload"]))
                data_stream += choice["payload"]
            else:
                # B keeps every non-formula byte verbatim in one stream; the
                # Deflate pass over the whole stream is what preserves history.
                data_stream += blocks[index]
        packed_data = zlib.compress(bytes(data_stream), level)
        packed_side = zlib.compress(bytes(side), level)
        body = bytearray(_header(arch, block_size, len(blocks), len(data), crc))
        body += residual.varint(len(bitmap)) + bitmap
        body += residual.varint(len(data_stream)) + residual.varint(len(packed_data)) + packed_data
        body += residual.varint(len(side)) + residual.varint(len(packed_side)) + packed_side
        if stats.modelled == 0:
            return _plain(data, level, block_size, len(blocks), crc), stats
        return bytes(body), stats

    if arch == ARCH_C:
        transformed = bytearray()
        side = bytearray()
        count = 0
        previous_index = 0
        for index, block in enumerate(blocks):
            choice = choose(block, level, models, use_residual, adaptive)
            stats.add(choice, len(block))
            if choice["kind"] == "model":
                pred = choice["predicted"]
                xor = bytes(a ^ p for p, a in zip(pred, block))
                diff = bytes((a - p) & 0xFF for p, a in zip(pred, block))
                keep, raw = min(((residual.XOR, xor), (residual.MODDIFF, diff)),
                                key=lambda item: len(zlib.compress(item[1], level)))
                transformed += raw
                side += residual.varint(index - previous_index)
                previous_index = index
                side += choice["descriptor"]
                side.append(keep)
                count += 1
            else:
                transformed += block
        packed_data = zlib.compress(bytes(transformed), level)
        packed_side = zlib.compress(bytes(side), level)
        body = bytearray(_header(arch, block_size, len(blocks), len(data), crc))
        body += residual.varint(count)
        body += residual.varint(len(transformed)) + residual.varint(len(packed_data)) + packed_data
        body += residual.varint(len(side)) + residual.varint(len(packed_side)) + packed_side
        if stats.modelled == 0:
            return _plain(data, level, block_size, len(blocks), crc), stats
        return bytes(body), stats

    raise ValueError("unknown architecture")


def unpack(blob: bytes, verify: bool = True) -> bytes:
    magic, version, arch, block_size, nblocks, size, crc = HEADER.unpack_from(blob, 0)
    if magic != MAGIC or version != VERSION:
        raise ValueError("not an SXZ3 archive")
    pos = HEADER.size
    expected = [min(block_size, size - i * block_size) for i in range(nblocks)]
    out = bytearray()

    if arch == ARCH_PLAIN:
        length, pos = residual.read_varint(blob, pos)
        out = bytearray(_inflate(blob[pos : pos + length], size))
        pos += length
        if pos != len(blob):
            raise ValueError("unexpected bytes after plain stream")
    elif arch == ARCH_A:
        for want in expected:
            tag = blob[pos]
            pos += 1
            if tag == 0:
                out += blob[pos : pos + want]
                pos += want
            elif tag == 1:
                length, pos = residual.read_varint(blob, pos)
                out += _inflate(blob[pos : pos + length], want)
                pos += length
            elif tag == 2:
                model, params, pos = read_descriptor(blob, pos)
                mode = blob[pos]
                pos += 1
                length, pos = residual.read_varint(blob, pos)
                pred = predict(model, params, want)
                out += residual.apply(pred, mode, blob[pos : pos + length])
                pos += length
            else:
                raise ValueError(f"unknown block tag {tag}")
    elif arch == ARCH_B:
        map_len, pos = residual.read_varint(blob, pos)
        bitmap = blob[pos : pos + map_len]
        pos += map_len
        data_len, pos = residual.read_varint(blob, pos)
        packed_len, pos = residual.read_varint(blob, pos)
        data = zlib.decompress(blob[pos : pos + packed_len])
        pos += packed_len
        side_len, pos = residual.read_varint(blob, pos)
        packed_side_len, pos = residual.read_varint(blob, pos)
        side = zlib.decompress(blob[pos : pos + packed_side_len])
        pos += packed_side_len
        if len(data) != data_len or len(side) != side_len:
            raise ValueError("stream length mismatch")
        data_pos = side_pos = 0
        for index, want in enumerate(expected):
            if bitmap[index // 8] >> (index % 8) & 1:
                model, params, side_pos = read_descriptor(side, side_pos)
                mode = side[side_pos]
                side_pos += 1
                length, side_pos = residual.read_varint(side, side_pos)
                pred = predict(model, params, want)
                out += residual.apply(pred, mode, data[data_pos : data_pos + length])
                data_pos += length
            else:
                out += data[data_pos : data_pos + want]
                data_pos += want
        if data_pos != len(data) or side_pos != len(side):
            raise ValueError("unconsumed B streams")
    elif arch == ARCH_C:
        count, pos = residual.read_varint(blob, pos)
        transformed_len, pos = residual.read_varint(blob, pos)
        packed_len, pos = residual.read_varint(blob, pos)
        transformed = zlib.decompress(blob[pos : pos + packed_len])
        pos += packed_len
        side_len, pos = residual.read_varint(blob, pos)
        packed_side_len, pos = residual.read_varint(blob, pos)
        side = zlib.decompress(blob[pos : pos + packed_side_len])
        pos += packed_side_len
        if len(transformed) != transformed_len or len(side) != side_len:
            raise ValueError("stream length mismatch")
        descs = {}
        side_pos = 0
        index = 0
        for _ in range(count):
            delta, side_pos = residual.read_varint(side, side_pos)
            index += delta
            model, params, side_pos = read_descriptor(side, side_pos)
            mode = side[side_pos]
            side_pos += 1
            descs[index] = (model, params, mode)
        if side_pos != len(side):
            raise ValueError("unconsumed C side stream")
        offset = 0
        for index, want in enumerate(expected):
            chunk = transformed[offset : offset + want]
            entry = descs.get(index)
            if entry is not None:
                model, params, mode = entry
                pred = predict(model, params, want)
                if mode == residual.MODDIFF:
                    out += bytes((p + r) & 0xFF for p, r in zip(pred, chunk))
                elif mode == residual.XOR:
                    out += bytes(p ^ r for p, r in zip(pred, chunk))
                else:
                    raise ValueError("invalid in-place residual mode")
            else:
                out += chunk
            offset += want
        if offset != len(transformed):
            raise ValueError("unconsumed C data stream")
    else:
        raise ValueError("unknown architecture")

    if verify and (zlib.crc32(out) & 0xFFFFFFFF) != crc:
        raise ValueError("SXZ3 crc mismatch")
    return bytes(out)


def _inflate(payload: bytes, size: int) -> bytes:
    data = zlib.decompress(payload)
    if len(data) != size:
        raise ValueError("deflate block size mismatch")
    return data
