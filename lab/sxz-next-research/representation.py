"""Whole-file reversible representations. No normalization of the source."""
import io
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass

import numpy as np
from ctypes import c_char_p, c_size_t, c_void_p, create_string_buffer

from accelerate import ROOT, NATIVE, load
from dsl import LIMIT, Reader, seq, v

RAW, DEFLATE, PIXEL, JPEG, PLANES, PNG_STREAM = range(6)
PREF_MAX = 8 << 20
PREF = load(ROOT / "preflate-bridge/target/release" / ("sxz_preflate_bridge.dll" if __import__("os").name == "nt" else "libsxz_preflate_bridge.dylib" if __import__("sys").platform == "darwin" else "libsxz_preflate_bridge.so"), {
    name: (c_size_t, [c_char_p, c_size_t, c_void_p, c_size_t]) for name in ("split", "rejoin")
})


@dataclass
class Channel:
    data: bytes
    kind: str = "raw"
    shape: tuple = ()


@dataclass
class Section:
    kind: int
    length: int
    aux: bytes
    channels: list[Channel]


def raw(data, kind="raw"):
    return Section(RAW, len(data), b"", [Channel(data, kind)])


def split_deflate(body):
    # An encoder-only buffer reused across streams in the same process.
    if PREF is None or not 0 < len(body) <= PREF_MAX:
        return None
    b = split_deflate.__dict__.get("buffer")
    if b is None:
        b = split_deflate.buffer = create_string_buffer(2*PREF_MAX)
    size = PREF.split(body, len(body), b, len(b))
    if size == 0:
        return None
    n = struct.unpack_from("<I", b)[0]
    s = memoryview(b).cast("B")
    return bytes(s[4:4+n]), bytes(s[4+n:size])


def rejoin_deflate(plain, correction, original):
    if PREF is None or not 0 < original <= PREF_MAX or len(plain) > PREF_MAX:
        raise ValueError("Preflate unavailable or length")
    src = struct.pack("<I", len(plain)) + plain + correction
    dst = create_string_buffer(original)
    if PREF.rejoin(src, len(src), dst, len(dst)) != original:
        raise ValueError("Preflate reconstruction refused")
    return dst.raw


def apply_ranges(data, ranges, gap_kind="raw"):
    result, end = [], 0
    for start, stop, sec in sorted(ranges, key=lambda x: x[0]):
        if not end <= start < stop <= len(data):
            raise ValueError("overlapping sections")
        if start > end:
            result.append(raw(data[end:start], gap_kind))
        result.append(sec)
        end = stop
    if end < len(data) or not result:
        result.append(raw(data[end:], gap_kind))
    return result


def deflates(data, fmt):
    positions = []
    if fmt == "DOCX":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for entry in z.infolist():
                if entry.compress_type != 8 or entry.flag_bits & 1 or entry.file_size > PREF_MAX:
                    continue
                off = entry.header_offset
                if data[off:off+4] != b"PK\x03\x04":
                    continue
                n, m = struct.unpack_from("<HH", data, off+26)
                start = off+30+n+m
                positions.append((start, start+entry.compress_size,
                                  "text" if entry.filename.endswith((".xml",".rels")) else "raw"))
    elif fmt == "PDF":
        last = 0
        for match in re.finditer(rb"(?<![A-Za-z])stream(?:\r\n|\n|\r)", data):
            i = match.end()
            if i < last or i+6 > len(data) or data[i] & 15 != 8 or data[i] >> 4 > 7:
                continue
            if ((data[i] << 8) + data[i+1]) % 31 or data[i+1] & 32:
                continue
            stream = zlib.decompressobj()
            try:
                stream.decompress(data[i:i+PREF_MAX], PREF_MAX)
            except zlib.error:
                continue
            if stream.eof:
                last = i + min(PREF_MAX, len(data)-i) - len(stream.unused_data)
                positions.append((i+2, last-4, "auto"))
    ranges = []
    for start, stop, kind in positions:
        s = split_deflate(data[start:stop])
        if s:
            plain, corr = s
            ranges.append((start, stop, Section(DEFLATE, stop-start, corr, [Channel(plain, kind)])))
    return apply_ranges(data, ranges), dict(eligible=len(positions), exposed=len(ranges))


def png_ranges(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG signature")
    i = 8
    ihdr = None
    ids = []
    while i+12 <= len(data):
        n, tag = struct.unpack_from(">I4s", data, i)
        end = i+12+n
        if end > len(data):
            raise ValueError("PNG length")
        if tag == b"IHDR":
            ihdr = data[i+8:end-4]
        if tag == b"IDAT":
            ids.append((i,end,data[i+8:end-4],data[end-4:end]))
        i = end
        if tag == b"IEND":
            break
    if not ids or not ihdr or any(a[1] != b[0] for a,b in zip(ids,ids[1:])):
        return None
    return ihdr, ids


def filter_png(data, fs, w, h, bpp, invert):
    if not w or not h or not 1 <= bpp <= 4 or len(fs) != h or len(data) != w*h or max(fs) > 4:
        raise ValueError("PNG filter domain")
    if NATIVE:
        dst = create_string_buffer(len(data))
        if not NATIVE.png_filter(data,dst,fs,w,h,bpp,invert):
            raise ValueError("PNG filter")
        return dst.raw
    out = bytearray(len(data))
    hist = out if invert else data
    for row, f in enumerate(fs):
        for x in range(w):
            j = row*w+x
            a = hist[j-bpp] if x >= bpp else 0
            b = hist[j-w] if row else 0
            c = hist[j-w-bpp] if row and x >= bpp else 0
            if f == 4:
                p = a+b-c
                q = min((a,b,c), key=lambda y: abs(p-y))
            else:
                q = (0,a,b,(a+b)//2)[f]
            out[j] = (data[j]+q if invert else data[j]-q) & 255
    return bytes(out)


def pixel_split(data, w,h,px):
    gg = np.frombuffer(data,np.uint8).reshape(h,w*px+1)
    fs = gg[:,0].tobytes()
    pix = filter_png(gg[:,1:].tobytes(),fs,w*px,h,px,True)
    ar = np.frombuffer(pix,np.uint8).reshape(h*w,px).copy()
    if px >= 3:
        ar[:,0] -= ar[:,1]
        ar[:,2] -= ar[:,1]
    return fs, [Channel(ar[:,i].tobytes(),"image",(w,h)) for i in range(px)]


def pixel_join(channels, filters, w,h,px):
    if not w or not h or not 1 <= px <= 4 or len(channels) != px or w*h*px > PREF_MAX:
        raise ValueError("PNG shape")
    if any(len(ch) != w*h for ch in channels):
        raise ValueError("PNG channel length")
    ar = np.column_stack([np.frombuffer(ch,np.uint8) for ch in channels])
    if px >= 3:
        ar[:,0] += ar[:,1]
        ar[:,2] += ar[:,1]
    png = filter_png(ar.tobytes(),filters,w*px,h,px,False)
    return np.column_stack((np.frombuffer(filters,np.uint8),np.frombuffer(png,np.uint8).reshape(h,w*px))).tobytes()


def png(data):
    report = dict(eligible=1,exposed=0,pixels=False)
    fallback = [raw(data)]
    found = png_ranges(data)
    if not found:
        return fallback,fallback,report
    ihdr, ids = found
    z = b"".join(i[2] for i in ids)
    if len(z) < 6 or z[1] & 32:
        return fallback,fallback,report
    parts = split_deflate(z[2:-4])
    if not parts:
        return fallback,fallback,report
    plain, corr = parts
    aux = z[:2]+z[-4:]+v(len(ids))+b"".join(v(len(i[2]))+i[3] for i in ids)+v(len(corr))+corr
    first,last = ids[0][0],ids[-1][1]
    fmt = apply_ranges(data, [(first,last,Section(PNG_STREAM,last-first,aux,[Channel(plain)]))])
    report.update(exposed=1, idat_chunks=len(ids))
    w,h,bits,color,m,f,inter = struct.unpack(">IIBBBBB",ihdr)
    px = {0:1,2:3,4:2,6:4}.get(color,0)
    if bits != 8 or not px or m or f or inter or not w or not h or h*(w*px+1) != len(plain):
        return fmt,fmt,report
    filters, channels = pixel_split(plain,w,h,px)
    typed = apply_ranges(data,[(first,last,Section(PIXEL,last-first,seq(w,h,px)+filters+aux,channels))])
    report.update(pixels=True,width=w,height=h,channels=px)
    return fmt,typed,report


def jpeg(data):
    # Parse marker boundaries, never search inside APP/COM payloads. Keep
    # restart markers/fill bytes in the verbatim channel.
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("JPEG signature")
    ranges, i = [], 2
    marker = re.compile(rb"\xff(?!\x00)")
    while i+1 < len(data):
        if data[i] != 255:
            break
        while i < len(data) and data[i] == 255:
            i += 1
        if i >= len(data):
            break
        op = data[i]
        i += 1
        if op == 0xd9:
            break
        if op == 1 or 0xd0 <= op <= 0xd7:
            continue
        if i+2 > len(data):
            break
        n = int.from_bytes(data[i:i+2],"big")
        if n < 2 or i+n > len(data):
            break
        i += n
        if op != 0xda:
            continue
        start = i
        while True:
            m = marker.search(data, start)
            if not m:
                i = len(data)
                break
            end = m.start()
            if end > start:
                unst = data[start:end].replace(b"\xff\0",b"\xff")
                ranges.append((start,end,Section(JPEG,end-start,b"",[Channel(unst)])))
            x = end
            while x < len(data) and data[x] == 255:
                x += 1
            if x < len(data) and 0xd0 <= data[x] <= 0xd7:
                start = x+1
                continue
            i = end
            break
    return apply_ranges(data,ranges), dict(entropy_sections=len(ranges))


def pb_fields(data, start, end):
    r = Reader(memoryview(data)[start:end])
    while r.at < end-start:
        k = r.get()
        number, wire = k >> 3, k & 7
        if wire == 0:
            yield number, wire, r.get(), None
            continue
        if wire not in (1,2,5):
            raise ValueError("protobuf wire type")
        n = r.get() if wire == 2 else (8 if wire == 1 else 4)
        off = start+r.at
        r.take(n)
        yield number, wire, off, off+n


def onnx(data):
    ranges = []
    fmt_ranges = []
    info = []
    for k, wire, g, g_end in pb_fields(data,0,len(data)):
        if (k,wire) != (7,2):
            continue
        for k, wire, start, end in pb_fields(data,g,g_end):
            if (k,wire) != (5,2):
                continue
            fields = list(pb_fields(data,start,end))
            dtype = next((a for k,w,a,b in fields if (k,w) == (2,0)),0)
            width = {1:4,2:1,3:1,4:2,5:2,6:4,7:8,10:2,11:8,12:4,13:8,16:2}.get(dtype,0)
            if not width:
                continue
            payload = next(((a,b) for k,w,a,b in fields if (k,w) == (9,2)),None)
            if not payload and dtype == 1:
                payload = next(((a,b) for k,w,a,b in fields if (k,w) == (4,2)),None)
            if payload is None:
                continue
            a,b = payload
            if b == a or (b-a) % width:
                continue
            buf = data[a:b]
            vals = np.frombuffer(buf,np.uint8).reshape(-1,width)
            # No float conversion: all bit patterns, including NaNs, are preserved.
            planes = [Channel(vals[:,i].tobytes(),"tensor",(width,)) for i in range(width)]
            ranges.append((a,b,Section(PLANES,len(buf),v(width),planes)))
            fmt_ranges.append((a,b,raw(buf,"tensor")))
            info.append(dict(dtype=dtype, bytes=b-a, width=width))
    return apply_ranges(data,fmt_ranges), apply_ranges(data,ranges), dict(initializers=info)


def represent(data, fmt):
    if fmt in ("PDF","DOCX"):
        fmt, info = deflates(data,fmt)
        return fmt,fmt,info
    if fmt == "PNG":
        return png(data)
    if fmt == "JPEG":
        fmt, info = jpeg(data)
        return fmt,fmt,info
    if fmt == "ONNX":
        return onnx(data)
    fmt = [raw(data, "text" if fmt == "TXT" else "raw")]
    return fmt,fmt,{}


def inverse(kind, expected, aux, channels):
    if kind == RAW and len(channels) == 1 and not aux:
        out = channels[0]
    elif kind == DEFLATE and len(channels) == 1:
        out = rejoin_deflate(channels[0], aux, expected)
    elif kind == JPEG and len(channels) == 1 and not aux:
        out = channels[0].replace(b"\xff",b"\xff\x00")
    elif kind in (PIXEL,PNG_STREAM):
        r = Reader(aux)
        if kind == PIXEL:
            w,h,px = r.get(),r.get(),r.get()
            fs = bytes(r.take(h))
            plain = pixel_join(channels,fs,w,h,px)
        else:
            if len(channels) != 1:
                raise ValueError("IDAT channel")
            plain = channels[0]
        hd, tail, n = r.take(2), r.take(4), r.get()
        if not 1 <= n <= 65536:
            raise ValueError("IDAT chunk count")
        chunks = [(r.get(),bytes(r.take(4))) for _ in range(n)]
        corr = bytes(r.take(r.get()))
        r.finish()
        data_size = sum(n for n,_ in chunks)
        if data_size + 12*len(chunks) != expected:
            raise ValueError("IDAT length")
        stream = bytes(hd)+rejoin_deflate(plain,corr,data_size-6)+bytes(tail)
        pos, out = 0, bytearray()
        for n,crc in chunks:
            out += struct.pack(">I4s",n,b"IDAT")+stream[pos:pos+n]+crc
            pos += n
        out = bytes(out)
    elif kind == PLANES:
        r = Reader(aux)
        width = r.get()
        r.finish()
        if not 1 <= width <= 8 or len(channels) != width or any(len(x)*width != expected for x in channels):
            raise ValueError("tensor width")
        out = np.column_stack([np.frombuffer(x,np.uint8) for x in channels]).tobytes()
    else:
        raise ValueError("unknown section")
    if len(out) != expected or len(out) > LIMIT:
        raise ValueError("section output size mismatch")
    return out
