"""Experimental framing for like-for-like MDL comparisons."""
import struct
import zlib
from collections import Counter

import zstandard

import dsl
import representation as rep
import search
from accelerate import NATIVE, scan_native

HEADER = struct.Struct("<4sIII")  # magic, final length, CRC32, decompressed recipe length
BODY_CAP = 32 << 20
MAX_SECTIONS = 8192


def frame(body,data,level):
    if len(body) > BODY_CAP or len(data) > dsl.LIMIT:
        raise ValueError("frame limit")
    return HEADER.pack(b"XNB1",len(data),zlib.crc32(data),len(body)) + zstandard.ZstdCompressor(
        level=level,write_checksum=True).compress(body)


def proposal(ch, option):
    data, kind = ch.data, ch.kind
    if kind == "auto":
        sample = data[:1024]
        kind = "text" if sum(32 <= b < 127 or b in (9,10,13) for b in sample)*10 >= 9*len(sample) else "raw"
    if option == "grammar" and kind == "text":
        ans = search.grammar(data)
        return (ans[0], "grammar", ans[1]) if ans is not None else None
    if option == "tensor" and kind == "tensor":
        ans = search.tensor(data)
        return (ans[0], "patch-block", ans[1]) if ans is not None else None
    if option in ("spatial-fixed","spatial-learned") and kind == "image":
        ans = search.spatial_search(data,*ch.shape,learn=option=="spatial-learned")
        return (ans[0], "spatial", ans[1]) if ans is not None else None
    if option in ("tree-fixed","tree-learned") and kind == "image":
        ans = search.spatial_tree(data,*ch.shape,learn=option=="tree-learned")
        return (ans[0], "spatial-tree", ans[1]) if ans is not None else None
    if option == "algebra" and kind == "raw" and NATIVE and len(data) >= 32:
        hits,total = scan_native(data,minimum=32)
        if hits:
            return search.bytes_graph(data,hits), "order2-scan", total
    return None


def recipe(sections, option=None, policy="local"):
    if not 1 <= len(sections) <= MAX_SECTIONS:
        raise ValueError("section count")
    body = bytearray(dsl.v(len(sections)))
    stats = Counter()
    params = []
    for section in sections:
        body += dsl.seq(section.kind,section.length,len(section.aux)) + section.aux
        body += dsl.v(len(section.channels))
        stats["aux_bytes"] += len(section.aux)
        for ch in section.channels:
            data = ch.data
            wire = dsl.seq(0,len(data),len(data))+data
            ans = proposal(ch, option)
            if ans is not None:
                model, name, count = ans
                candidate = dsl.seq(1,len(data),len(model))+model
                stats["proposals"] += 1
                if policy == "all" or search.local_size(candidate) < search.local_size(wire):
                    params.append(count)
                    stats[name] += 1
                    stats["program_wire_bytes"] += len(model)
                    stats["modelled_bytes"] += len(data)
                    wire = candidate
            stats["channel_bytes"] += len(data)
            body += wire
    return bytes(body), dict(stats), params


def program_archive(wire,data,level=3):
    # Same header/section as baseline; only the channel coding mode changes.
    body = dsl.seq(1,rep.RAW,len(data),0,1,1,len(data),len(wire))+wire
    return frame(body,data,level)


def unpack(blob):
    if len(blob) < HEADER.size:
        raise ValueError("short header")
    magic,n,crc,nbody = HEADER.unpack_from(blob)
    if magic != b"XNB1" or n > dsl.LIMIT or nbody > BODY_CAP or len(blob) > BODY_CAP+65536:
        raise ValueError("frame limit")
    payload = blob[HEADER.size:]
    config = zstandard.get_frame_parameters(payload)
    if config.content_size != nbody or config.window_size > BODY_CAP:
        raise ValueError("zstd limits")
    packed = zstandard.ZstdDecompressor().decompress(payload,max_output_size=nbody,allow_extra_data=False)
    r = dsl.Reader(packed)
    ns = r.get()
    if not 1 <= ns <= MAX_SECTIONS:
        raise ValueError("section count")
    out = bytearray()
    remaining = BODY_CAP
    shared_work = [dsl.WORK]
    for _ in range(ns):
        kind,nsec,m = r.get(),r.get(),r.get()
        if nsec > n-len(out):
            raise ValueError("container output limit")
        aux = r.take(m).tobytes()
        k = r.get()
        if not 1 <= k <= 8:
            raise ValueError("channel count")
        channels = []
        # Every program charges work separately. Limit the number of calls and
        # the decoded channel bytes at archive scope as well.
        for _ in range(k):
            mode,lenout,lenwire = r.get(),r.get(),r.get()
            remaining -= lenout
            if remaining < 0 or lenout > dsl.LIMIT:
                raise ValueError("expanded channels limit")
            wire = r.take(lenwire)
            if mode == 0 and lenwire == lenout:
                ch = bytes(wire)
            elif mode == 1:
                ch = dsl.evaluate(wire,lenout,shared_work)
            else:
                raise ValueError("channel mode")
            channels.append(ch)
        out.extend(rep.inverse(kind,nsec,aux,channels))
    r.finish()
    if len(out) != n or zlib.crc32(out) != crc:
        raise ValueError("length/checksum mismatch")
    return bytes(out)
