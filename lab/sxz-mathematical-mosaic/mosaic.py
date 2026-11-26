"""Research-only byte-aligned graph, decoder, and complete wire measurement."""
import bisect
import struct
import time
import zlib
from collections import defaultdict,Counter
from dataclasses import dataclass

import numpy as np
import zstandard as z

import catalog as c
from represent import MODES,project,revert,view

CAP=128<<20
MAX_OPS=500000
MAX_SYMBOLS=40_000_000  # sum over slice work; cached generated prefix budget is <=10M
HDR=struct.Struct("<4sBBBBBIIII")
Z=z.ZstdCompressor(level=3,write_checksum=True)
UC=z.ZstdDecompressor()
LIT,SLICE,COPY,APPROX,INLINE=range(5)


def v(n):
    if not 0<=n<1<<32: raise ValueError("wire integer domain")
    d=bytearray()
    while n>=128:
        d.append((n&127)|128); n>>=7
    d.append(n)
    return bytes(d)


def vs(x): return 2*x if x>=0 else -2*x-1
def sv(x): return x//2 if x%2==0 else -(x//2+1)
def ints(*n): return b"".join(map(v,n))
def vl(x): return max(1,(x.bit_length()+6)//7)


class Reader:
    def __init__(self,d):
        self.d=d; self.p=0
    def v(self):
        n=0
        for i in range(0,35,7):
            b=self.take(1)[0]
            n|=(b&127)<<i
            if b<128 and n<1<<32: return n
        raise ValueError("overlong integer")
    def take(self,n):
        if n>len(self.d)-self.p: raise ValueError("truncated")
        x=self.d[self.p:self.p+n]; self.p+=n
        return x


@dataclass(frozen=True,slots=True)
class Edge:
    a:int
    b:int
    gid:int
    addr:int
    sym:int
    widths:bytes=b""
    patch:bytes=b""
    errors:int=0

    @property
    def desc(self):
        extra=vl(len(self.widths))+len(self.widths) if self.widths else 1
        return 1+vl(self.b-self.a)+1+vl(self.addr)+vl(self.sym)+extra+(
            vl(self.errors)+len(self.patch) if self.errors else 0)

    def dict(self):
        return dict(target_byte=self.a,target_byte_end=self.b,gid=self.gid,source_symbol=self.addr,
                    symbols=self.sym,widths_bytes=len(self.widths),description_bytes=self.desc,
                    errors=self.errors)


def expanded_edges(hits,mode,offsets,allow_trim=True):
    best={}
    for a,g,p,s in hits:
        q=project(mode,offsets,a,s)
        if q is None: continue
        lo,hi,tr,n,w=q
        d=Edge(lo,hi,g,p+tr,n,w)
        if hi-lo<=d.desc: continue
        k=(lo,hi,g)
        if k not in best or d.addr<best[k].addr: best[k]=d
        # Cheaper source or a later candidate can win if this coverage is cut short.
        if allow_trim and not w and hi-lo>48:
            for delta in (1,4,16):
                q1=project(mode,offsets,a,s-delta)
                if q1 is None or q1[:2]==q[:2]: continue
                lo1,hi1,tr1,n1,w1=q1
                d1=Edge(lo1,hi1,g,p+tr1,n1,w1)
                k=(lo1,hi1,g)
                if k not in best or d1.addr<best[k].addr: best[k]=d1
    return list(best.values())


def plan(edges,method="dp",hot=True,gid=None):
    if gid is not None: edges=[x for x in edges if x.gid==gid]
    def gain(e):
        return e.b-e.a-e.desc-(2 if hot else 0)
    if method=="greedy":
        x=sorted(edges,key=lambda e:(e.a,-(e.b-e.a),e.desc,e.addr))
        a=-1; out=[]
        for e in x:
            if e.a>=a and gain(e)>0:
                out.append(e); a=e.b
        return out
    if method!="dp": raise ValueError("planning mode")
    e=sorted(edges,key=lambda x:(x.b,x.a,x.desc,x.addr))
    rs=[x.b for x in e]
    val=[0]; prev=[]; take=[]
    for i,r in enumerate(e):
        j=bisect.bisect_right(rs,r.a,hi=i)
        v1=val[j]+gain(r)
        yes=v1>val[-1]
        val.append(max(v1,val[-1]));prev.append(j);take.append(yes)
    i=len(e)-1;out=[]
    while i>=0:
        if take[i]:
            out.append(e[i]);i=prev[i]-1
        else:
            i-=1
    return out[::-1]


def guarded_edges(edges,raw):
    """Check local backend price of the original region, not digit length alone."""
    memo={}
    out=[]
    for e in edges:
        q=(e.a,e.b)
        if q not in memo:
            # A conservative accounting proxy; independent overhead removed.
            memo[q]=min(e.b-e.a,max(0,len(Z.compress(raw[e.a:e.b]))-13))
        if memo[q]>e.desc+2: out.append(e)
    return out


def definitions(raw,edges,repeat=False,no_math=False):
    """B: one local fragment, then byte-length COPY. Exact comparisons of bytes."""
    if repeat:
        # Discover byte-identical copies of already identified fragments anywhere.
        # The same candidates are supplied to the conventional repeat-only ablation.
        groups={}
        for e in edges:
            s=raw[e.a:e.b]
            if len(s)>=12 and len(raw)<=1<<20: groups.setdefault(s,e)
            if len(groups)>=64: break
        more=list(edges)
        for s,e in groups.items():
            if no_math or not e.errors:
                q=raw.find(s);cnt=0
                while q>=0 and cnt<128:
                    if q!=e.a: more.append(Edge(q,q+len(s),e.gid,e.addr,e.sym,e.widths,e.patch,e.errors))
                    cnt+=1; q=raw.find(s,q+len(s))
        edges=plan(more)
    output=[]; start=0; seen={}
    for e in edges:
        if e.a>start: output.append((LIT,start,e.a,None))
        s=raw[e.a:e.b]
        if repeat and s in seen:
            output.append((COPY,e.a,e.b,e.a-seen[s]))
        elif no_math:
            if repeat: seen[s]=e.a
            output.append((LIT,e.a,e.b,None))
        else:
            if repeat: seen[s]=e.a
            output.append((APPROX if e.errors else SLICE,e.a,e.b,e))
        start=e.b
    if start<len(raw): output.append((LIT,start,len(raw),None))
    compact=[]
    for op,a,b,d in output:
        if op==LIT and compact and compact[-1][0]==LIT:
            compact[-1]=(op,compact[-1][1],b,None)
        else: compact.append((op,a,b,d))
    return compact


def archive(raw,ops,mode,kind,seed,total,style,delta=False,crc=None):
    if len(raw)>CAP or len(ops)>MAX_OPS: raise ValueError("archive capacity")
    meta=bytearray(v(len(ops))); residual=[]; prev_addr=defaultdict(int)
    counts=Counter(); descs=Counter(); dictionary=[]
    for op,a,b,d in ops:
        m0=len(meta)
        meta+=ints(op,b-a)
        if op==LIT:
            residual.append(raw[a:b])
        elif op==INLINE:
            meta+=raw[a:b]  # segmentation counterfactual, never a math candidate
        elif op==COPY:
            meta+=v(d)
        else:
            p=vs(d.addr-prev_addr[d.gid]) if delta else d.addr
            prev_addr[d.gid]=d.addr
            meta+=ints(d.gid,p,d.sym,len(d.widths))+d.widths
            if op==APPROX:
                meta+=v(d.errors)+d.patch
            dictionary.append(dict(d.dict(),base=mode,opcode=op,
                                   charged_description_bytes=len(meta)-m0))
        counts[op]+=b-a
        descs[op]+=len(meta)-m0
    raw_meta=len(meta); lit=b"".join(residual);raw_lit=len(lit)
    if style&1: meta=Z.compress(bytes(meta))
    if style&2: lit=Z.compress(lit)
    blob=HDR.pack(b"MSM0",MODES.index(mode),c.KINDS.index(kind),seed,c.LEVELS.index(total),
                  style+(4 if delta else 0),len(raw),zlib.crc32(raw) if crc is None else crc,len(meta),len(lit))+meta+lit
    return blob,dict(header_bytes=HDR.size,metadata_raw=raw_meta,metadata_bytes=len(meta),
                     literals_raw=raw_lit,literals_bytes=len(lit),covered_bytes=counts[SLICE]+counts[APPROX],
                     repeated_bytes=counts[COPY],instruction_count=len(ops),description_raw=dict(descs),
                     matches=dictionary)


class Banks:
    def __init__(self,ready=None):
        self.cache={} if ready is None else dict(ready)
        self.seconds=0.; self.symbols=0;self.used=set()
    def get(self,kind,mode,total,seed,gid,start,n):
        limits=c.sizes(total)
        if gid>=len(limits) or n<1 or start+n>limits[gid]: raise ValueError("slice outside bank")
        key=(kind,mode,total,seed,gid)
        self.used.add(key)
        if key not in self.cache:
            t=time.perf_counter()
            if kind=="math":
                direct=c.direct(gid,mode,start,n,limits[gid])
                if direct is not None:
                    self.seconds+=time.perf_counter()-t
                    return direct
                d=c.stream(gid,mode,limits[gid])
            else:
                g=np.random.Generator(np.random.PCG64(c.SEEDS[seed]+100003*gid))
                if kind=="uniform":
                    d=g.integers(0,c.BASE[mode],limits[gid],dtype=np.uint8).tobytes()
                else:
                    raw=c.stream(gid,mode,limits[gid])
                    a=np.frombuffer(raw,np.uint8)
                    if kind=="shuffled": d=g.permutation(a).tobytes()
                    elif kind=="matched":
                        b=np.bincount(a,minlength=c.BASE[mode]).cumsum()
                        d=b.searchsorted(g.integers(0,len(raw),len(raw),dtype=np.int64),"right").astype(np.uint8).tobytes()
                    else: raise ValueError("control kind")
            self.symbols+=len(d)
            if self.symbols>c.MAX_SEQ: raise ValueError("generated-symbol limit")
            self.cache[key]=d
            self.seconds+=time.perf_counter()-t
        return self.cache[key][start:start+n]


def bounded_z(blob,n):
    p=z.get_frame_parameters(blob)
    if p.content_size>n or p.window_size>CAP: raise ValueError("zstd cap")
    return UC.decompress(blob,max_output_size=n,allow_extra_data=False)


def decode(blob,banks=None,trace=None):
    try:
        magic,mode,kind,seed,lv,which,n,crc,ml,ll=HDR.unpack_from(blob)
        if (magic!=b"MSM0" or mode>=len(MODES) or kind>=len(c.KINDS) or seed>=len(c.SEEDS)
            or lv>=len(c.LEVELS) or which>=8 or n>CAP or ml>24<<20 or ll>CAP+256*1024
            or len(blob)!=HDR.size+ml+ll):
            raise ValueError("header")
        mode,kind,total=MODES[mode],c.KINDS[kind],c.LEVELS[lv]
        mb=blob[HDR.size:HDR.size+ml];lb=blob[-ll:] if ll else b""
        m=Reader(bounded_z(mb,24<<20) if which&1 else mb)
        l=Reader(bounded_z(lb,n) if which&2 else lb)
        ops=m.v(); out=bytearray(); prev_addr=defaultdict(int); work=0
        if ops>MAX_OPS: raise ValueError("instruction cap")
        bank=Banks() if banks is None else banks
        for _ in range(ops):
            op,k=m.v(),m.v()
            if k<1 or k>n-len(out): raise ValueError("output cap")
            if op==LIT:
                s=l.take(k)
            elif op==INLINE:
                if k>4096: raise ValueError("inline control cap")
                s=m.take(k)
            elif op==COPY:
                back=m.v()
                if not k<=back<=len(out): raise ValueError("repeat range")
                start=len(out)-back
                s=out[start:start+k]
            elif op in (SLICE,APPROX):
                gid,p,num,w=m.v(),m.v(),m.v(),m.v()
                if which&4: p=prev_addr[gid]+sv(p)
                prev_addr[gid]=p
                work+=num
                if work>MAX_SYMBOLS or not 0<=p or not num or num>4096 or w>4096: raise ValueError("slice work")
                ws=m.take(w)
                if (mode=="decvar")!=(w>0): raise ValueError("width metadata")
                t=time.perf_counter() if trace is not None else 0.
                d=bank.get(kind,mode,total,seed,gid,p,num)
                if op==APPROX:
                    d=bytearray(d)
                    errors=m.v()
                    if not 1<=errors<=4: raise ValueError("patch cap")
                    for _ in range(errors):
                        j,x=m.v(),m.v()
                        if j>=len(d) or x>=256: raise ValueError("patch index")
                        d[j]=x
                    d=bytes(d)
                s=revert(d,mode,ws)
                if trace is not None:
                    trace.append(dict(gid=gid,source_symbol=p,length=num,target_byte=len(out),
                                      regeneration_s=time.perf_counter()-t))
            else: raise ValueError("instruction")
            if len(s)!=k: raise ValueError("output length mismatch")
            out.extend(s)
        if m.p!=len(m.d) or l.p!=len(l.d) or n!=len(out) or zlib.crc32(out)!=crc:
            raise ValueError("checksum or extent")
        return bytes(out)
    except (struct.error,IndexError,z.ZstdError) as err:
        raise ValueError("malformed mosaic") from err


def internal_periodic(raw,step=64,maxsize=4096):
    # Ordinary exact dictionary, fixed blocks for this separate cheap control.
    # Ground truth repeats for B are also measured by repeat-only above.
    out=[]; memory={}
    for start in range(0,len(raw),step):
        d=raw[start:start+step]
        if len(d)<12:
            out.append((LIT,start,start+len(d),None));continue
        p=memory.get(d)
        if p is not None: out.append((COPY,start,start+len(d),start-p))
        else: out.append((LIT,start,start+len(d),None))
        if len(memory)<maxsize or p is not None: memory[d]=start
    merged=[]
    for op,a,b,q in out:
        if merged and op==LIT and merged[-1][0]==LIT:
            merged[-1]=(op,merged[-1][1],b,None)
        else: merged.append((op,a,b,q))
    return merged
