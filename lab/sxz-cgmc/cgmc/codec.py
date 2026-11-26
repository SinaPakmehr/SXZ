"""CGMC token planner, container format and decoder.

Two container generations are supported:

* **v2** (`CG12`) — the original Phase 11 format.  Kept for historical
  reproduction.  It has no whole-archive checksum.
* **v3** (`CG13`) — corrected format.  Adds a SHA-256 of the original bytes,
  explicit selected-span accounting, and a strict same-boundary control mode.
  New corrected experiments use v3.

Both decoders enforce the same resource limits *before* decompression:
declared output, payload, metadata and selected-stream sizes, token count,
offsets, lengths and frame accounting.

Modes
-----
gen    : generator tokens only (candidate bytes are regenerated).
ctrl   : historical same-boundary control; every generator token is replaced
         by a control literal carrying the exact bytes.  The literal payload is
         the whole original file, so this control preserves the file as one
         literal stream but loses the generator/literal split.  It measures
         tokenisation + replacement, not pure mathematical value.
strict : corrected same-boundary control.  The non-selected literal stream and
         its compressed frame are byte-identical to ``gen``; the selected span
         bytes are carried in a separately compressed control stream.  The
         token metadata is identical to ``gen``.  The difference
         ``strict - gen`` isolates the cost of storing the selected bytes
         instead of generating them, with segmentation and backend context held
         fixed.
lzref  : conventional offset/length references at the same boundaries.
"""
from __future__ import annotations

import hashlib
import struct
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import zstandard as zstd

from .context import ContextTable
from .streams import CONFIGS, MAXLEN, STREAM_SPECS, gen_scalar

MAGIC = b"CG12"
VERSION = 2
HEADER = struct.Struct("<4sBBBBIIIIII")
MAGIC3 = b"CG13"
VERSION3 = 3
HEADER3 = struct.Struct("<4sBBBBIIIIIIII32s")
LIT, REF, CTRL = 0x00, 0xFD, 0xFE
MAX_VARINT_BYTES = 5

# Resource policy for the research decoder.  Callers may pass a larger
# max_output explicitly, but all other bounds remain.
DEFAULT_MAX_OUTPUT = 1 << 28          # 256 MiB
MAX_TOKENS = 1 << 22                  # 4,194,304 tokens
MAX_META_BYTES = 1 << 24              # 16 MiB of token metadata
MAX_REF_LEN = 1 << 20                 # 1 MiB per LZ reference
MAX_GEN_LEN = MAXLEN                  # 256 bytes
MAX_STRIDE = 64


def varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("negative varint")
    out = bytearray()
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def varint_len(n: int) -> int:
    if n < 0:
        raise ValueError
    k = 1
    while n >= 0x80:
        n >>= 7
        k += 1
    return k


def read_varint(buf, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(MAX_VARINT_BYTES):
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, pos
        shift += 7
    raise ValueError("overlong varint")


@dataclass
class Plan:
    tokens: list[tuple]
    estimated_bytes: int
    kind: str


def _token_cost(length: int) -> int:
    return 1 + varint_len(length)


def plan_greedy(best_len: np.ndarray, best_sid: np.ndarray, positions: np.ndarray,
                nbytes: int, stride: int = 8, min_len: int = 8) -> Plan:
    tokens: list[tuple] = []
    last = 0
    j = 0
    npos = len(positions)
    est = 0
    while j < npos:
        p = int(positions[j])
        L = int(best_len[j])
        if L >= min_len:
            if p > last:
                tokens.append(("lit", last, p - last))
                est += p - last
            sid = int(best_sid[j])
            tokens.append(("gen", sid, L, p))
            est += _token_cost(L)
            last = p + L
            while j < npos and int(positions[j]) < last:
                j += 1
        else:
            j += 1
    if last < nbytes:
        tokens.append(("lit", last, nbytes - last))
        est += nbytes - last
    return Plan(tokens, est, "greedy")


def plan_dp(best_len: np.ndarray, best_sid: np.ndarray, positions: np.ndarray,
            nbytes: int, stride: int = 8, min_len: int = 8,
            try_half: bool = True) -> Plan:
    nxt = (nbytes + stride - 1) // stride
    inf = 1 << 60
    cost = [inf] * (nxt + 1)
    choice: list[tuple | None] = [None] * (nxt + 1)
    cost[nxt] = 0
    npos = len(positions)
    for j in range(nxt - 1, -1, -1):
        literal_bytes = min(stride, nbytes - j * stride)
        best = literal_bytes + cost[j + 1]
        pick = ("lit",)
        if j < npos:
            L = int(best_len[j])
            if L >= min_len:
                opts = [L]
                if try_half:
                    half = ((L // 2) // stride) * stride
                    if half >= min_len and half != L:
                        opts.append(half)
                for opt in opts:
                    Lr = (opt // stride) * stride
                    if Lr < min_len:
                        continue
                    k = j + Lr // stride
                    if k > nxt:
                        continue
                    c = _token_cost(Lr) + cost[k]
                    if c < best:
                        best = c
                        pick = ("gen", int(best_sid[j]), Lr)
        cost[j] = best
        choice[j] = pick
    tokens: list[tuple] = []
    j = 0
    while j < nxt:
        pick = choice[j]
        if pick is None:
            raise AssertionError("dp path missing")
        if pick[0] == "lit":
            tokens.append(("lit", j * stride, min(stride, nbytes - j * stride)))
            j += 1
        else:
            _, sid, L = pick
            tokens.append(("gen", sid, L, j * stride))
            j += L // stride
    merged: list[tuple] = []
    for tok in tokens:
        if tok[0] == "lit" and merged and merged[-1][0] == "lit":
            prev = merged[-1]
            merged[-1] = ("lit", prev[1], prev[2] + tok[2])
        else:
            merged.append(tok)
    return Plan(merged, cost[0], "dp")


class _RefIndex:
    """Incremental 8-gram index over all byte positions below the cursor."""

    def __init__(self, data: bytes, cap: int = 8):
        self.data = data
        self.cap = cap
        self.table: dict[bytes, list[int]] = {}
        self.cursor = 0

    def advance(self, p: int) -> None:
        data = self.data
        while self.cursor < p:
            q = self.cursor
            if q + 8 <= len(data):
                self.table.setdefault(data[q:q + 8], []).append(q)
                if len(self.table[data[q:q + 8]]) > self.cap:
                    self.table[data[q:q + 8]].pop(0)
            self.cursor += 1

    def find(self, p: int, length: int) -> int:
        self.advance(p)
        if p + 8 > len(self.data):
            return -1
        key = self.data[p:p + 8]
        for q in reversed(self.table.get(key, ())):
            off = p - q
            if 0 < off <= 0xFFFFFF and np.array_equal(
                    np.frombuffer(self.data, dtype=np.uint8, count=length, offset=p),
                    np.frombuffer(self.data, dtype=np.uint8, count=length, offset=p - off)):
                return off
        return -1


def _split_plan(data: bytes, plan: Plan) -> tuple[bytes, bytes, bytes, bytes]:
    """Return (literal_payload, selected_payload, meta_gen, meta_ctrl).

    ``meta_gen`` and ``meta_ctrl`` are the same token sequence with GEN tags or
    CTRL tags respectively.  They have identical encoded length.
    """
    literal = bytearray()
    selected = bytearray()
    meta_gen = bytearray()
    meta_ctrl = bytearray()
    for tok in plan.tokens:
        if tok[0] == "lit":
            _, start, length = tok
            literal += data[start:start + length]
            for m in (meta_gen, meta_ctrl):
                m.append(LIT)
                m += varint(length)
        elif tok[0] == "gen":
            _, sid, length, start = tok
            selected += data[start:start + length]
            meta_gen.append(1 + sid)
            meta_gen += varint(length)
            meta_ctrl.append(CTRL)
            meta_ctrl += varint(length)
        else:
            raise ValueError(tok)
    return bytes(literal), bytes(selected), bytes(meta_gen), bytes(meta_ctrl)


def build_container(data: bytes, plan: Plan, cfg: str, mode: str, stride: int = 8,
                    level: int = 19, collect_refs: bool = False, version: int = 3):
    """Serialise a plan.

    ``version=2`` is the historical format.  ``version=3`` adds the SHA-256
    checksum and supports ``mode='strict'``.
    """
    cfg_id = sorted(CONFIGS).index(cfg)
    mode_id = {"gen": 0, "ctrl": 1, "lzref": 2, "strict": 3}[mode]
    if mode == "strict" and version != 3:
        raise ValueError("strict mode requires container v3")
    if version not in (2, 3):
        raise ValueError("unsupported container version")

    if mode == "strict":
        literal, selected, meta_gen, _ = _split_plan(data, plan)
        payload = literal
        meta = meta_gen
        pc = compress(payload, level)
        mc = compress(meta, level)
        sc = compress(selected, level) if selected else b""
        header = HEADER3.pack(MAGIC3, VERSION3, cfg_id, mode_id, stride,
                              len(data), len(plan.tokens), len(payload), len(meta),
                              len(selected), len(pc), len(mc), len(sc),
                              hashlib.sha256(data).digest())
        return header + pc + mc + sc

    payload = bytearray()
    meta = bytearray()
    ref = _RefIndex(data) if mode == "lzref" else None
    refs: list[tuple[int, int, int]] = []
    for tok in plan.tokens:
        if tok[0] == "lit":
            _, start, length = tok
            meta.append(LIT)
            meta += varint(length)
            payload += data[start:start + length]
        elif tok[0] == "gen":
            _, sid, length, start = tok
            if mode == "gen":
                meta.append(1 + sid)
                meta += varint(length)
            elif mode == "ctrl":
                meta.append(CTRL)
                meta += varint(length)
                payload += data[start:start + length]
            else:
                assert ref is not None
                off = ref.find(start, length)
                if off > 0:
                    meta.append(REF)
                    meta += varint(off)
                    meta += varint(length)
                    if collect_refs:
                        refs.append((start, off, length))
                else:
                    meta.append(CTRL)
                    meta += varint(length)
                    payload += data[start:start + length]
        else:
            raise ValueError(tok)
    pc = compress(bytes(payload), level)
    mc = compress(bytes(meta), level)
    if version == 3:
        header = HEADER3.pack(MAGIC3, VERSION3, cfg_id, mode_id, stride,
                              len(data), len(plan.tokens), len(payload), len(meta),
                              0, len(pc), len(mc), 0,
                              hashlib.sha256(data).digest())
        blob = header + pc + mc
    else:
        header = HEADER.pack(MAGIC, VERSION, cfg_id, mode_id, stride, len(data),
                             len(plan.tokens), len(payload), len(meta), len(pc), len(mc))
        blob = header + pc + mc
    if collect_refs:
        return blob, refs
    return blob


def compress(blob: bytes, level: int = 19) -> bytes:
    return zstd.ZstdCompressor(level=level, write_checksum=True).compress(blob)


def decompress(blob: bytes, max_output: int | None = None) -> bytes:
    try:
        return zstd.ZstdDecompressor().decompress(blob, max_output_size=max_output)
    except zstd.ZstdError as exc:
        raise ValueError("corrupt zstd frame") from exc


@dataclass
class DecodeStats:
    tokens: int = 0
    literals: int = 0
    gens: int = 0
    refs: int = 0
    ctrls: int = 0
    math_gens: int = 0
    hist_gens: int = 0
    fit_gens: int = 0
    sec: float = 0.0
    bytes_out: int = 0
    sha256: str = ""
    checksum_ok: bool = False
    version: int = 0
    mode: str = ""
    selected_bytes: int = 0


def archive_info(blob: bytes) -> dict:
    """Parse either header generation without decoding any frame."""
    if len(blob) < 8:
        raise ValueError("short archive")
    magic = blob[:4]
    if magic == MAGIC3:
        if len(blob) < HEADER3.size:
            raise ValueError("short v3 header")
        (m, ver, cfg, mode, stride, orig, ntok, plen, mlen, slen,
         pclen, mclen, sclen, digest) = HEADER3.unpack_from(blob, 0)
        return {"version": ver, "magic": m, "config_id": cfg, "mode_id": mode,
                "stride": stride, "orig_len": orig, "tokens": ntok,
                "payload_len": plen, "meta_len": mlen, "selected_len": slen,
                "payload_c": pclen, "meta_c": mclen, "selected_c": sclen,
                "digest": digest.hex(), "header_bytes": HEADER3.size}
    if magic == MAGIC:
        if len(blob) < HEADER.size:
            raise ValueError("short v2 header")
        (m, ver, cfg, mode, stride, orig, ntok, plen, mlen, pclen, mclen) = HEADER.unpack_from(blob, 0)
        return {"version": ver, "magic": m, "config_id": cfg, "mode_id": mode,
                "stride": stride, "orig_len": orig, "tokens": ntok,
                "payload_len": plen, "meta_len": mlen, "selected_len": 0,
                "payload_c": pclen, "meta_c": mclen, "selected_c": 0,
                "digest": "", "header_bytes": HEADER.size}
    raise ValueError("bad magic/version")


def _inflate(frame: bytes, declared: int, name: str) -> bytes:
    if declared < 0:
        raise ValueError(f"bad {name} length")
    out = decompress(frame, max_output=max(declared, 1))
    if len(out) != declared:
        raise ValueError(f"{name} length mismatch")
    return out


def decode_container(blob: bytes, max_output: int | None = None,
                     verify_checksum: bool = True) -> tuple[bytes, DecodeStats]:
    t0 = time.perf_counter()
    if len(blob) < 8:
        raise ValueError("short header")
    info = archive_info(blob)
    version = info["version"]
    cfg_id = info["config_id"]
    mode_id = info["mode_id"]
    stride = info["stride"]
    orig_len = info["orig_len"]
    ntok = info["tokens"]
    payload_len = info["payload_len"]
    meta_len = info["meta_len"]
    selected_len = info["selected_len"]
    pc_len = info["payload_c"]
    mc_len = info["meta_c"]
    sc_len = info["selected_c"]
    header_bytes = info["header_bytes"]

    cap = DEFAULT_MAX_OUTPUT if max_output is None else int(max_output)
    if cap <= 0:
        raise ValueError("non-positive output budget")
    # All limits are enforced before any frame is decompressed.
    if orig_len > cap:
        raise ValueError("declared output exceeds limit")
    if ntok > MAX_TOKENS:
        raise ValueError("too many tokens")
    if ntok > orig_len:
        raise ValueError("token count exceeds output length")
    if payload_len > orig_len:
        raise ValueError("literal payload exceeds output length")
    if selected_len > orig_len:
        raise ValueError("selected payload exceeds output length")
    meta_bound = min(MAX_META_BYTES, 11 * ntok)
    if meta_len > meta_bound:
        raise ValueError("metadata exceeds token bound")
    if stride < 1 or stride > MAX_STRIDE:
        raise ValueError("bad stride")
    if mode_id not in (0, 1, 2, 3):
        raise ValueError("bad mode")
    if mode_id == 3 and version != 3:
        raise ValueError("strict mode requires v3")
    if mode_id != 3 and (selected_len != 0 or sc_len != 0):
        raise ValueError("unexpected selected stream")
    if mode_id == 3:
        if selected_len == 0 and sc_len != 0:
            raise ValueError("selected frame without bytes")
        if selected_len > 0 and sc_len == 0:
            raise ValueError("selected bytes without frame")
    if header_bytes + pc_len + mc_len + sc_len != len(blob):
        raise ValueError("bad frame lengths")

    cfg_names = sorted(CONFIGS)
    if cfg_id >= len(cfg_names):
        raise ValueError("bad config")
    cfg = cfg_names[cfg_id]
    ids = set(CONFIGS[cfg])

    pc = blob[header_bytes:header_bytes + pc_len]
    mc = blob[header_bytes + pc_len:header_bytes + pc_len + mc_len]
    sc = blob[header_bytes + pc_len + mc_len:]
    payload = _inflate(pc, payload_len, "literal payload")
    meta = _inflate(mc, meta_len, "metadata")
    if mode_id == 3 and selected_len > 0:
        selected = _inflate(sc, selected_len, "selected payload")
    else:
        selected = b""

    out = bytearray()
    table = ContextTable(stride=stride)
    stats = DecodeStats(version=version,
                        mode=("gen", "ctrl", "lzref", "strict")[mode_id])
    pos = 0
    ppos = 0
    spos = 0
    for _ in range(ntok):
        if pos >= len(meta):
            raise ValueError("truncated token stream")
        tag = meta[pos]
        pos += 1
        if tag == LIT:
            n, pos = read_varint(meta, pos)
            if n <= 0 or ppos + n > len(payload) or len(out) + n > orig_len:
                raise ValueError("bad literal")
            out += payload[ppos:ppos + n]
            ppos += n
            stats.literals += 1
        elif tag == CTRL:
            n, pos = read_varint(meta, pos)
            if n <= 0 or n > MAX_GEN_LEN or ppos + n > len(payload) or len(out) + n > orig_len:
                raise ValueError("bad control literal")
            out += payload[ppos:ppos + n]
            ppos += n
            stats.ctrls += 1
        elif tag == REF:
            off, pos = read_varint(meta, pos)
            n, pos = read_varint(meta, pos)
            if off <= 0 or off > len(out) or n <= 0 or n > MAX_REF_LEN or len(out) + n > orig_len:
                raise ValueError("bad reference")
            for _i in range(n):
                out.append(out[-off])
            stats.refs += 1
        elif 1 <= tag <= len(STREAM_SPECS):
            sid = tag - 1
            if sid not in ids:
                raise ValueError("stream outside configuration")
            n, pos = read_varint(meta, pos)
            if n <= 0 or n > MAX_GEN_LEN or len(out) + n > orig_len:
                raise ValueError("bad generator length")
            if mode_id == 3:
                if spos + n > len(selected):
                    raise ValueError("selected stream exhausted")
                out += selected[spos:spos + n]
                spos += n
            else:
                p = len(out)
                family = STREAM_SPECS[sid][1]
                off = -1
                if family == "lzp":
                    off = table.lookup(out, p, int(STREAM_SPECS[sid][3]))
                gen = gen_scalar(sid, out, p, n, off)
                if len(gen) != n:
                    raise ValueError("generator unavailable")
                out += gen
            stats.gens += 1
            if sid < 32:
                stats.math_gens += 1
            elif sid < 42:
                stats.hist_gens += 1
            elif sid >= 50:
                stats.fit_gens += 1
        else:
            raise ValueError(f"unknown tag {tag}")
        stats.tokens += 1
    if pos != len(meta):
        raise ValueError("unconsumed metadata")
    if ppos != len(payload):
        raise ValueError("unconsumed literal payload")
    if mode_id == 3 and spos != len(selected):
        raise ValueError("unconsumed selected payload")
    if len(out) != orig_len:
        raise ValueError("length mismatch")
    if version == 3 and verify_checksum:
        if hashlib.sha256(out).digest() != bytes.fromhex(info["digest"]):
            raise ValueError("archive checksum mismatch")
        stats.checksum_ok = True
    stats.sec = time.perf_counter() - t0
    stats.bytes_out = len(out)
    stats.sha256 = hashlib.sha256(out).hexdigest()
    stats.selected_bytes = len(selected)
    return bytes(out), stats


def describe_plan(plan: Plan, data_len: int) -> dict:
    gens = [t for t in plan.tokens if t[0] == "gen"]
    lits = [t for t in plan.tokens if t[0] == "lit"]
    covered = sum(t[2] for t in gens)
    return {
        "tokens": len(plan.tokens),
        "gen_tokens": len(gens),
        "gen_bytes": covered,
        "coverage": covered / data_len if data_len else 0.0,
        "literal_tokens": len(lits),
        "estimated_bytes": plan.estimated_bytes,
        "planner": plan.kind,
    }
