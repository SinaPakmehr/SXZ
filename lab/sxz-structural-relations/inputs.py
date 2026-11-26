"""Oracle boundaries from public complete files; reuse SXZ-NEXT inverse read-only."""
import os
import re
import struct
import sys
import xml.parsers.expat as expat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEXT = ROOT.parent/"sxz-next-research"
DATA = ROOT.parents[1]/"datasets/sxz5-data"/"raw"
TEMP = ROOT.parent.parent/"datasets/tools"
sys.dont_write_bytecode = True
sys.path.insert(0,str(NEXT))

import numpy as np
import representation as prev
from dsl import Reader

L, TILE = 0, 1
PEGAP = 32
MAX_RECORDS = 30000
ONNX = "https://media.githubusercontent.com/media/onnx/models/main/validated/vision/classification/"
PIL = "https://raw.githubusercontent.com/python-pillow/Pillow/main/Tests/images/"
DOC = "https://github.com/python-openxml/python-docx"
PPT = "https://github.com/scanny/python-pptx"
ENTRY = [
    ("xml","dev",DATA/"docx-shapes.docx",DOC),
    ("xml","test",DATA/"docx-table.docx",DOC),
    ("xml","test",DATA/"docx-images.docx",DOC),
    ("xml","test",DATA/"pptx-chart.pptx",PPT),
    ("pdf","dev",DATA/"irs1040.pdf","https://www.irs.gov/pub/irs-pdf/f1040.pdf"),
    ("pdf","test",DATA/"bert.pdf","https://arxiv.org/pdf/1810.04805"),
    ("pdf","test",DATA/"attention.pdf","https://arxiv.org/pdf/1706.03762"),
    ("tensor","dev",ROOT.parents[1]/"datasets/corpus/squeezenet1.1-7.onnx",ONNX+"squeezenet/model/squeezenet1.1-7.onnx"),
    ("tensor","test",ROOT.parents[1]/"datasets/models/squeezenet1.0-12.onnx",ONNX+"squeezenet/model/squeezenet1.0-12.onnx"),
    ("tensor","test",ROOT.parents[1]/"datasets/models/mobilenetv2-7.onnx",ONNX+"mobilenet/model/mobilenetv2-7.onnx"),
    ("binary","dev",ROOT/"zstd-release/zstd-v1.6.0-win64/zstd.exe",
        "https://github.com/meta/zstd/releases/download/v1.6.0/zstd-v1.6.0-win64.zip"),
    ("binary","test",TEMP/"djxl.exe","https://github.com/libjxl/libjxl/releases/tag/v0.13.0"),
    ("binary","test",TEMP/"cjxl.exe","https://github.com/libjxl/libjxl/releases/tag/v0.13.0"),
    ("image","dev",ROOT.parents[1]/"datasets/corpus/python-logo.png","https://www.python.org/static/community_logos/python-logo.png"),
    ("image","test",ROOT.parents[1]/"datasets/corpus/hopper.png",PIL+"hopper.png"),
    ("image","test",ROOT.parents[1]/"datasets/corpus/flower_thumbnail.png",PIL+"flower_thumbnail.png"),
    ("image","test",ROOT.parents[1]/"datasets/corpus/exif.png",PIL+"exif.png"),
]


@dataclass
class Record:
    data: bytes
    group: tuple = ()
    width: int = 1
    hw: tuple = ()
    position: tuple = ()


@dataclass
class Channel:
    records: list[Record]
    w: int = 0
    h: int = 0
    tile: int = 0


@dataclass
class Part:
    kind: int
    length: int
    aux: bytes
    channels: list[Channel]


def raw(data):
    return Part(prev.RAW,len(data),b"",[Channel([Record(data)])])


def glue(data, intervals):
    out = []
    pos = 0
    for a,b,r in sorted(intervals,key=lambda t:t[:2]):
        if not pos <= a < b <= len(data):
            raise ValueError("interval overlap")
        if a > pos:
            out.append(Record(data[pos:a]))
        out.append(r)
        pos = b
    if pos != len(data):
        out.append(Record(data[pos:]))
    return out or [Record(data)]


def split_file(data,ranges):
    parts, i = [], 0
    for a,b,p in sorted(ranges,key=lambda t:t[:2]):
        if not i <= a < b <= len(data):
            raise ValueError("parts overlap")
        if a > i:
            parts.append(raw(data[i:a]))
        parts.append(p)
        i = b
    if i < len(data):
        parts.append(raw(data[i:]))
    return parts or [raw(data)]


TAG_END = re.compile(rb'''(?:[^"'<>]+|"[^"]*"|'[^']*')*>''')
INTEREST = {"p","r","style","tbl","tr","tc","Relationship","Override","sp","row","c","si",
            "num","abstractNum","lvl","idx","t","v"}


def xml_records(data):
    """Get original lexical byte offsets; do not canonicalize/re-export XML."""
    if not data or len(data) > 2<<20 or not data.lstrip().startswith(b"<") or b"<!DOCTYPE" in data.upper():
        return [Record(data)]
    parser = expat.ParserCreate()
    stack, proposed = [], []

    def start(tag,_):
        i = parser.CurrentByteIndex
        m = TAG_END.match(data,i+1)
        j = m.end() if m else i
        stack.append((tag,i,j,data[j-2:j]==b"/>"))

    def end(tag):
        key,i,j,self_close = stack.pop()
        k = parser.CurrentByteIndex
        if not self_close:
            m = TAG_END.match(data,k+1)
            j = m.end() if m else k
        if 32 <= j-i <= 8192 and tag.split(":")[-1] in INTEREST:
            proposed.append((i,j,("xml",stack[-1][0] if stack else "",key)))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.ExternalEntityRefHandler = lambda *args: 0
    try:
        parser.Parse(data,True)
    except expat.ExpatError:
        return [Record(data)]
    counts = {}
    for _,_,key in proposed:
        counts[key] = counts.get(key,0)+1
    out, stop = [], 0
    for a,b,g in sorted(proposed,key=lambda x:(x[0],-x[1])):
        if a >= stop and counts[g] >= 2:
            out.append((a,b,Record(data[a:b],g)))
            stop = b
    return glue(data,out)


PDF_OBJ = re.compile(rb"(?m)(?:^|(?<=[\r\n]))[ \t]*(\d{1,8})[ \t]+(\d+)[ \t]+obj\b(.*?)\bendobj\b",re.S)
PDF_TYPE = re.compile(rb"/(?:Type|Subtype)\s*/([A-Za-z0-9]+)")


def pdf_records(data):
    """Ordinary lexical dictionaries inside a raw gap; compressed payloads are separate."""
    out = []
    for m in PDF_OBJ.finditer(data):
        a,b = m.span()
        v = data[a:b]
        body = m[3].strip()
        if not 36 <= b-a <= 8192 or not body.startswith(b"<<") or b"\0" in v or b"stream" in body:
            continue
        names = tuple(PDF_TYPE.findall(v)[:2])
        out.append((a,b,Record(v,("pdf-dict",)+names)))
    return glue(data,out)


def documents(data, family):
    exposed, note = prev.deflates(data,"PDF" if family=="pdf" else "DOCX")
    parts = []
    covered = 0
    for s in exposed:
        d = s.channels[0].data
        if family=="xml":
            records = xml_records(d) if s.kind==prev.DEFLATE and s.channels[0].kind=="text" else [Record(d)]
        elif s.kind==prev.DEFLATE and 32 <= len(d) <= 512<<10:
            sample = d[:256]
            printable = sum(32<=x<127 or x in (9,10,13) for x in sample)
            kind = "pdf-text" if printable*10 >= 9*len(sample) else "pdf-stream"
            records = [Record(d,(kind,))] if kind=="pdf-text" else [Record(d,(kind,len(d)))]
        else:
            records = pdf_records(d) if s.kind==prev.RAW else [Record(d)]
        covered += sum(len(r.data) for r in records if r.group)
        parts.append(Part(s.kind,s.length,s.aux,[Channel(records)]))
    return parts,{**note,"grouped_plain_bytes":covered}


def tensors(data):
    widths = {1:4,2:1,3:1,4:2,5:2,6:4,7:8,10:2,11:8,12:4,13:8,16:2}
    ranges, info = [], []
    for k,w,g,e in prev.pb_fields(data,0,len(data)):
        if (k,w)!=(7,2):
            continue
        for k,w,a,b in prev.pb_fields(data,g,e):
            if (k,w)!=(5,2):
                continue
            f = list(prev.pb_fields(data,a,b))
            dtype = next((x for k,w,x,y in f if (k,w)==(2,0)),0)
            width = widths.get(dtype,0)
            dims = []
            for key,wire,x,y in f:
                if key==1 and wire==0:
                    dims.append(x)
                elif key==1 and wire==2:
                    r = Reader(data[x:y])
                    while r.at < y-x:
                        dims.append(r.get())
            loc = next(((x,y) for k,w,x,y in f if (k,w)==(9,2)),None)
            if loc is None and dtype==1:
                loc = next(((x,y) for k,w,x,y in f if (k,w)==(4,2)),None)
            if not loc or not width:
                continue
            i,j = loc
            import math
            if not j>i or math.prod(dims)*width != j-i:
                continue
            d = data[i:j]
            name = next((data[x:y].decode("utf-8","replace") for k,w,x,y in f if (k,w)==(8,2)),"")
            sig = ("tensor",dtype,*dims)
            ranges.append((i,j,Part(prev.RAW,j-i,b"",[Channel([Record(d,sig,width)])])))
            info.append(dict(name=name,dtype=dtype,shape=dims,offset=i,bytes=j-i))
    return split_file(data,ranges),{"initializers":info}


def images(data):
    _,typed,note = prev.png(data)
    out = []
    for p in typed:
        channels = []
        for i,c in enumerate(p.channels):
            if p.kind!=prev.PIXEL:
                channels.append(Channel([Record(c.data)]))
                continue
            w,h = c.shape
            ar = np.frombuffer(c.data,np.uint8).reshape(h,w)
            t = 16
            rs = []
            for y in range(0,h,t):
                for x in range(0,w,t):
                    a = ar[y:y+t,x:x+t]
                    hh,ww = a.shape
                    rs.append(Record(a.tobytes(),("image",i,hh,ww),1,(hh,ww),(y//t,x//t)))
            channels.append(Channel(rs,w,h,t))
        out.append(Part(p.kind,p.length,p.aux,channels))
    return out,note


def pe(data):
    if data[:2] != b"MZ":
        raise ValueError("not PE")
    base = struct.unpack_from("<I",data,0x3c)[0]
    if data[base:base+4]!=b"PE\0\0":
        raise ValueError("PE signature")
    machine,count = struct.unpack_from("<HH",data,base+4)
    opt = base+24
    optlen = struct.unpack_from("<H",data,base+20)[0]
    sections = []
    for i in range(count):
        pos = opt+optlen+40*i
        tag,vs,rva,n,off = struct.unpack_from("<8sIIII",data,pos)
        if off+n<=len(data):
            sections.append((tag.rstrip(b"\0"),rva,n,off))
    def translate(rva,n):
        for _,a,size,off in sections:
            if a<=rva and rva+n<=a+size:
                return off+rva-a
        return None
    if machine!=0x8664 or struct.unpack_from("<H",data,opt)[0]!=0x20b or optlen<144:
        return [raw(data)],{"machine":machine,"functions":0,"pdata_records":0}
    table,n = struct.unpack_from("<II",data,opt+112+8*3)
    tab = translate(table,n)
    if tab is None or n%12:
        return [raw(data)],{"machine":machine,"functions":0,"pdata_records":0}
    funcs = []
    for a,b,u in struct.iter_unpack("<III",data[tab:tab+n]):
        if 48<=b-a<=1536 and (off:=translate(a,b-a)) is not None and not tab<=off<tab+n:
            funcs.append((off,b-a))
    # Stable regular sample to keep this oracle stage bounded for large binaries.
    stride = max(1,(len(funcs)+449)//450)
    regions, last = [], -1
    for off,size in sorted(set(funcs))[::stride]:
        if off >= last and not (off < tab+n and off+size > tab):
            regions.append((off,off+size,Record(data[off:off+size],("pe-func",size//64))))
            last = off+size
    nrecord = 0
    for a in range(tab,tab+n-12*16+1,12*16):
        b = a+12*16
        regions.append((a,b,Record(data[a:b],("pe-pdata",),4)))
        nrecord += 1
    return [Part(prev.RAW,len(data),b"",[Channel(glue(data,regions))])],dict(
        machine=machine,functions=len(funcs),function_stride=stride,pdata_records=nrecord,
        sampled_functions=len(regions)-nrecord)


def structure(data,family):
    if family in ("xml","pdf"):
        return documents(data,family)
    return {"tensor":tensors,"image":images,"binary":pe}[family](data)
