"""Lab harness: serialized sizes, not a supported new SXZ archive format."""
import struct
import time
import zlib
from collections import Counter

import numpy as np
import zstandard

from inputs import MAX_RECORDS, prev
from dsl import Reader, seq
import dsl
import models as m
import search as prior_grammar

HDR = struct.Struct("<4sBIIIIII")
LIMIT = 64 << 20
PART_LIMIT = 16 << 20


def layout(parts):
    out = bytearray(seq(len(parts)))
    records = []
    for p in parts:
        out += seq(p.kind,p.length,len(p.aux),len(p.channels))+p.aux
        for c in p.channels:
            out += seq(len(c.records),c.w,c.h,c.tile)
            records.extend(c.records)
    if len(records)>MAX_RECORDS:
        raise ValueError("too many records")
    return bytes(out),records


def decode_frame_bytes(blob):
    info = zstandard.get_frame_parameters(blob)
    if info.content_size>LIMIT or info.window_size>LIMIT:
        raise ValueError("backend limit")
    return zstandard.ZstdDecompressor().decompress(blob,max_output_size=LIMIT,allow_extra_data=False)


def grammar_body(data):
    """Conventional Re-Pair-like grammar from SXZ-NEXT, no typed operators.

    Up to 12 text-ish 128 KiB windows, chosen by a fixed gate. Run the forced
    ablation as well as local MDL; everything else is stored as literal.
    """
    forced,local = bytearray(),bytearray()
    total=0
    allowed=0
    stats=Counter()
    for i in range(0,len(data),131072):
        raw=data[i:i+131072]
        s=raw[:512]
        text=sum(32<=x<127 or x in (9,10,13) for x in s)>=.8*len(s)
        header=seq(0,len(raw))
        opt=header+raw
        choice=opt
        if text and allowed<12:
            allowed+=1
            p=prior_grammar.grammar(raw)
            if p:
                w=p[0]
                cand=seq(1,len(w))+w
                choice=cand
                stats["grammar_windows"]+=1
                stats["rules"]+=p[1]
                if m.zs(cand)<m.zs(opt):
                    opt=cand
                    stats["local_selected"]+=1
        forced+=choice
        local+=opt
        total+=1
    return seq(total)+bytes(forced),seq(total)+bytes(local),dict(stats)


def ungrammar(data):
    r=Reader(data)
    amount=r.get()
    if amount>512:
        raise ValueError("grammar count")
    out=bytearray()
    work=[dsl.WORK]
    for _ in range(amount):
        mode,n=r.get(),r.get()
        if n>PART_LIMIT:
            raise ValueError("grammar payload")
        s=r.take(n)
        if mode==0 and n<=131072:
            out+=s
        elif mode==1:
            d=dsl.evaluate(s,shared=work)
            if len(d)>131072:
                raise ValueError("grammar window")
            out+=d
        else:
            raise ValueError("grammar mode")
        if len(out)>LIMIT:
            raise ValueError("expanded grammar payload")
    r.finish()
    return bytes(out)


def encode(data,layout_bytes,choices,level=3,grammar=None,layout_comp=None,crc=None):
    z = zstandard.ZstdCompressor(level=level,write_checksum=True)
    inst=seq(len(choices))+b"".join(x.description() for x in choices)
    body=b"".join(x.payload for x in choices) if grammar is None else grammar
    if layout_comp is None:
        layout_comp=z.compress(layout_bytes)
    chunks=layout_comp,z.compress(inst),z.compress(body)
    size,crc=len(data),zlib.crc32(data) if crc is None else crc
    blob=HDR.pack(b"SRX0",int(grammar is not None),size,crc,*map(len,chunks),0)+b"".join(chunks)
    params=sum(len(x.params) for x in choices)
    meta=dict(header_bytes=HDR.size, layout_raw=len(layout_bytes),layout_stored=len(chunks[0]),
              descriptor_raw=len(inst),descriptor_stored=len(chunks[1]),
              payload_raw=len(body),payload_stored=len(chunks[2]),
              params_raw=params,references=sum(bool(x.back) for x in choices),
              backref_raw=sum(len(seq(x.back)) for x in choices if x.back),
              residual_raw=sum(len(x.payload) for x in choices if x.op in (m.XOR,m.SUB,m.EDIT,m.PXOR,m.PSUB,m.PEDIT)),
              literal_raw=sum(len(x.payload) for x in choices if x.op==m.LIT),
              mode_counts=dict(Counter(str(x.op) for x in choices)),
              parametric_count=sum(x.op in (m.PXOR,m.PSUB,m.PEDIT) for x in choices),
              template_count=len({i-x.back for i,x in enumerate(choices) if x.back}),
              max_distance=max((x.back for x in choices),default=0))
    assert len(blob)==HDR.size+sum(len(x) for x in chunks)
    return blob,meta


def expand(desc,body):
    r=Reader(desc)
    count=r.get()
    if not 1<=count<=MAX_RECORDS:
        raise ValueError("record count")
    out=[]
    at=0
    used=0
    for i in range(count):
        op,w,n,k,back,p=(r.get() for _ in range(6))
        if w not in (1,2,4,5,8) or n>PART_LIMIT or at+k>len(body) or back>i or p>32:
            raise ValueError("record header")
        used+=n
        if used>LIMIT:
            raise ValueError("record expansion")
        params=r.take(p)
        d=body[at:at+k]
        at+=k
        if (op==m.LIT and not back and not p and k==n):
            value=m.plane(d,w,True)
        elif back and op in (m.REF,m.XOR,m.SUB,m.EDIT,m.PXOR,m.PSUB,m.PEDIT):
            template=out[i-back]
            if op in (m.PXOR,m.PSUB,m.PEDIT):
                if not p or len(template)>m.CAP:
                    raise ValueError("missing parameters")
                template=m.predict(template,params)
            elif p:
                raise ValueError("unexpected params")
            if op==m.REF and not k:
                value=template
            elif op in (m.XOR,m.SUB,m.PXOR,m.PSUB) and k==n:
                value=m.delta(template,m.plane(d,w,True),m.XOR if op in (m.XOR,m.PXOR) else m.SUB,True)
            elif op in (m.EDIT,m.PEDIT) and n<=8192:
                value=m.apply_copy(template,d,n)
            else:
                raise ValueError("residual opcode")
        else:
            raise ValueError("record opcode")
        if len(value)!=n:
            raise ValueError("record length")
        out.append(value)
    r.finish()
    if at!=len(body):
        raise ValueError("record payload length")
    return out


def untile(records,w,h,t):
    if not w or not h or t!=16 or w*h>PART_LIMIT:
        raise ValueError("tile limits")
    if len(records)!=((w+t-1)//t)*((h+t-1)//t):
        raise ValueError("tile count")
    a=np.empty((h,w),np.uint8)
    i=0
    for y in range(0,h,t):
        for x in range(0,w,t):
            b=a[y:y+t,x:x+t]
            b[:]=np.frombuffer(records[i],np.uint8).reshape(b.shape)
            i+=1
    return a.tobytes()


def assemble(lay,records,n):
    out=bytearray()
    r=Reader(lay)
    ns=r.get()
    if not 1<=ns<=MAX_RECORDS:
        raise ValueError("layout count")
    k=0
    for _ in range(ns):
        op,nsec,l,nch=(r.get() for _ in range(4))
        if nsec>n-len(out) or not 1<=nch<=8:
            raise ValueError("section limit")
        aux=bytes(r.take(l))
        ch=[]
        for _ in range(nch):
            count,w,h,t=(r.get() for _ in range(4))
            if not 1<=count<=len(records)-k:
                raise ValueError("channel count")
            s=records[k:k+count]
            k+=count
            ch.append(untile(s,w,h,t) if t else b"".join(s))
        out.extend(prev.inverse(op,nsec,aux,ch))
    r.finish()
    if len(out)!=n or k!=len(records):
        raise ValueError("layout extent")
    return bytes(out)


def unpack(blob, stages=False):
    a=time.perf_counter_ns()
    magic,gram,n,crc,x,y,z,end=HDR.unpack_from(blob)
    if magic!=b"SRX0" or n>LIMIT or gram>1 or end or x+y+z+HDR.size!=len(blob):
        raise ValueError("header")
    at=HDR.size
    lay,desc,body=(decode_frame_bytes(blob[i:i+k]) for i,k in ((at,x),(at+x,y),(at+x+y,z)))
    b=time.perf_counter_ns()
    if gram:
        body=ungrammar(body)
    records=expand(desc,body)
    c=time.perf_counter_ns()
    out=assemble(lay,records,n)
    if zlib.crc32(out)!=crc:
        raise ValueError("output mismatch")
    e=time.perf_counter_ns()
    return (out,[(b-a)/1e9,(c-b)/1e9,(e-c)/1e9]) if stages else out
