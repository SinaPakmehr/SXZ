"""Independent ASMC lab engine; earlier project is read only."""
import ctypes as C
from collections import Counter,defaultdict
from dataclasses import dataclass
from bisect import bisect_right
import struct
import sys
from pathlib import Path
from time import perf_counter
import zlib

import numpy as np
import zstandard as z

ROOT=Path(__file__).resolve().parent
MS=ROOT.parent/"sxz-mathematical-mosaic"
sys.path.insert(0,str(MS))
import represent as rp

FAMILIES=("splitmix64","independent-counter-mix","xorshift32","PCG32","LCG32",
          "composition","xoroshiro128+","GF256","rule30","LFSR","histogram","Markov",
          "LCG-general","two-state mixture")
ACCESS=("counter","counter","linear","logarithmic LCG jump","logarithmic LCG jump","counter",
        "linear","linear","linear","linear","prefix implementation","linear","logarithmic affine jump",
        "linear hidden-state prefix")
MODES=("bytes","b2","b4","b8","dec3","b16")
CAP=128<<20
MAXW=16<<20
HEADER=struct.Struct("<4sBBIIII")
Z=z.ZstdCompressor(level=3,write_checksum=True)
U=z.ZstdDecompressor()
LIT,INLINE,REF,COPY,ARITH,XOR,MODDIFF,PATCH=range(8)


def v(n):
    if not 0<=n<1<<32: raise ValueError("integer range")
    b=bytearray()
    while n>=128: b.append((n&127)|128);n>>=7
    b.append(n);return bytes(b)

def vs(n): return 2*n if n>=0 else -2*n-1
def sv(n): return n//2 if n%2==0 else -(n//2+1)
def vsz(n): return max(1,(n.bit_length()+6)//7)
def ints(*ns): return b"".join(map(v,ns))


class Reader:
    def __init__(self,d):self.d=d;self.p=0
    def take(self,n):
        if n>len(self.d)-self.p:raise ValueError("truncation")
        a=self.d[self.p:self.p+n];self.p+=n;return a
    def get(self):
        x=0
        for i in range(0,35,7):
            b=self.take(1)[0];x|=(b&127)<<i
            if b<128 and x<1<<32:return x
        raise ValueError("overlong integer")
    def end(self):
        if self.p!=len(self.d):raise ValueError("extra bits")


class Hit(C.Structure):
    _fields_=[(f,C.c_uint32) for f in ("a","row","q","n")]
class Stats(C.Structure):
    _fields_=[(f,C.c_uint64) for f in ("hits","covered","max","sum","multi","dropped","entries")]


def lib():
    f=C.CDLL(str(ROOT/("asm_native.dll" if __import__("os").name == "nt" else "libasm_native.dylib" if __import__("sys").platform == "darwin" else "libasm_native.so")))
    P,N,I,B=C.c_void_p,C.c_size_t,C.c_uint32,C.c_char_p
    f.generate.argtypes=[I,I,I,N,P,N,B,N]; f.generate.restype=I
    f.matrix.argtypes=[I,I,P,N,N,P,B,N]; f.matrix.restype=I
    f.build.argtypes=[B,N,N,N,I]; f.build.restype=P
    f.query.argtypes=[P,B,N,P,N,N,P]; f.query.restype=N
    f.release.argtypes=[P];f.release.restype=None
    return f

N=lib()


@dataclass(frozen=True,slots=True)
class Source:
    family:int
    seed:int
    param:int=0
    extra:tuple=()
    def wire(self):
        base=ints(self.family,self.param,self.seed)
        return base+ints(self.extra[0]-1,*self.extra[1:]) if self.family==12 else base
    def describe(self):return dict(family=FAMILIES[self.family],id=self.family,seed=self.seed,param=self.param,
                                   algebraic_params=self.extra)


@dataclass(frozen=True,slots=True)
class Edge:
    start:int
    end:int
    source:Source
    address:int
    symbols:int
    patch:bytes=b""
    op:int=REF
    @property
    def n(self): return self.end-self.start


def generate(src,start,n,table=b""):
    if not 0<=src.family<len(FAMILIES) or not 0<=src.param<=3 or not 0<=src.seed<1<<32 or n<0:
        raise ValueError("generator definition")
    if src.family==12:
        m,c,h=src.extra
        if not 2<=m<=1<<32 or max(c,h,src.seed)>=m or start<0 or start+n>262144:
            raise ValueError("LCG domain")
        state=src.seed; k=start//4; q=start%4
        while k:
            if k&1:state=(state*c+h)%m
            h=h*(c+1)%m;c=c*c%m;k>>=1
        c,h=src.extra[1:]
        out=bytearray()
        for _ in range((q+n+3)//4):
            out+=state.to_bytes(4,"little");state=(state*c+h)%m
        return bytes(out[q:q+n])
    if src.family==13:
        if len(table)!=512 or start<0 or start+n>262144:raise ValueError("hidden-state bounds")
        return hidden_matrix(np.array([src.seed],np.uint32),start+n,table,src.param)[start:]
    b=C.create_string_buffer(n)
    if not N.generate(src.family,src.param,src.seed,start,b,n,table,len(table)):
        raise ValueError("generator limits")
    return b.raw


def slice_view(src,mode,addr,n,table=b""):
    nb,ns=rp.UNITS[mode]
    w=addr%ns
    b=generate(src,addr//ns*nb,(w+n+ns-1)//ns*nb,table)
    s,_=rp.view(b,mode)
    return s[w:w+n]


def seeds(bits,maxn=65536,salt=0):
    n=min(1<<bits,maxn)
    a=np.arange(n,dtype=np.uint64)
    if n<1<<bits:
        a=(a*0x9e3779b1+(0x279dc82f+salt))&((1<<bits)-1)
    return a.astype(np.uint32)


def matrix(f,p,se,step,table):
    if f==13:return hidden_matrix(se,step,table,p)
    b=C.create_string_buffer(len(se)*step)
    if not N.matrix(f,p,se.ctypes.data,len(se),step,b,table,len(table)): raise ValueError("matrix limits")
    return b.raw


def hidden_matrix(se,step,table,param):
    # A fixed two-state process. Alternates high/low symbol-entropy emission
    # tables; transition and emission use disjoint bits of the same counter mix.
    if len(table)!=512 or not 0<=param<=3:raise ValueError("hidden table")
    ss=se.astype(np.uint64); state=np.zeros(len(ss),np.uint16)
    lu=np.frombuffer(table,np.uint8)
    out=np.empty((len(ss),step),np.uint8)
    for i in range(step):
        x=ss+np.uint64((i*0x9e3779b97f4a7c15)&((1<<64)-1))
        x=(x^(x>>30))*np.uint64(0xbf58476d1ce4e5b9)
        x=(x^(x>>27))*np.uint64(0x94d049bb133111eb)
        x=x^(x>>31)
        state^=((x>>8)&((1<<(3+param))-1)==0).astype(np.uint16)
        out[:,i]=lu[state*256+(x&255).astype(np.uint16)]
    return out.tobytes()


class Bank:
    def __init__(self,specs,len_bytes=96,mode="bytes",table=b""):
        t=perf_counter(); self.table=table;self.mode=mode
        data=[]; self.sources=[]
        for family,param,ss in specs:
            self.sources.extend(Source(family,int(s),param) for s in ss)
            chunk=matrix(family,param,ss,len_bytes,table)
            enc,_=rp.view(chunk,mode);data.append(enc)
        self.gen_s=perf_counter()-t
        self.steps=len_byte=len_bytes*rp.UNITS[mode][1]//rp.UNITS[mode][0]
        self.size=sum(map(len,data))
        t=perf_counter()
        base=rp.BASE[mode]
        self.k=rp.K[base]
        self.ip=N.build(b"".join(data),self.size,len_byte,self.k,base)
        if not self.ip: raise ValueError("index bounds")
        self.index_s=perf_counter()-t
    def close(self):
        if self.ip:N.release(self.ip);self.ip=None
    def __enter__(self):return self
    def __exit__(self,*x):self.close()
    def search(self,data,cap=32000,low_bytes=7):
        t=perf_counter()
        mode=self.mode; s,off=rp.view(data,mode); t1=perf_counter()
        nb,ns=rp.UNITS[mode]
        box=(Hit*cap)(); st=Stats()
        nh=N.query(self.ip,s,len(s),box,cap,max(self.k,(low_bytes*ns+nb-1)//nb),C.byref(st))
        ts=perf_counter()-t1
        q=[]
        for h in box[:nh]:
            e=rp.project(mode,off,h.a,h.n)
            if e:
                a,b,w,n,_=e
                q.append(Edge(a,b,self.sources[h.row],h.q+w,n))
        return q,dict(**{k:int(getattr(st,k)) for k,_ in st._fields_},mode=mode,
                      query_s=ts,view_s=t1-t,target_symbols=len(s),bank_symbols=self.size,
                      seed_candidates=len(self.sources),retained=len(q),k=self.k)


def train_counts(data,mark=False):
    a=np.frombuffer(data,np.uint8)
    if not mark:
        return np.bincount(a,minlength=256).reshape(1,256)
    return np.bincount(a[:-1].astype(np.int32)*256+a[1:],minlength=65536).reshape(256,256)


def lookup(counts,budget):
    def row(v):
        v=v.astype(np.float64)+0.01
        x=(np.arange(budget)+0.5)*v.sum()/budget
        return v.cumsum().searchsorted(x,"right").astype(np.uint8).tobytes()
    return b"".join(row(v) for v in counts)


def cost(e,group):
    return (2+vsz(e.n)+vsz(e.address)+vsz(e.symbols)+len(e.patch)
            +(0 if group else len(e.source.wire())))


def dp(edges,group=False,guard=False,data=None):
    a=sorted(set(edges),key=lambda e:(e.end,e.start,e.source.family,e.source.param,e.source.seed,
                                    e.source.extra,e.address,e.op,e.patch))
    ends=[x.end for x in a]; value=[0]; choice=[]; prev=[]
    cache={}
    for i,e in enumerate(a):
        j=bisect_right(ends,e.start,hi=i)
        n=e.n
        if guard:
            key=(e.start,e.end)
            if key not in cache:cache[key]=min(n,max(0,len(Z.compress(data[e.start:e.end]))-13))
            n=cache[key]
        win=value[j]+n-cost(e,group)-1
        g=win>value[-1]
        value.append(max(win,value[-1]));choice.append(g);prev.append(j)
    out=[];i=len(a)-1
    while i>=0:
        if choice[i]:out.append(a[i]);i=prev[i]-1
        else:i-=1
    return value[-1],out[::-1]


def group_candidates(edges,data=None):
    hist=defaultdict(list)
    for e in edges:hist[e.source].append(e)
    scores=[]
    for g,rs in hist.items():
        if len(rs)<2:continue
        price,rs=dp(rs,True)
        net=price-len(g.wire())-1
        if len(rs)>=2 and net>0:scores.append((net,g,rs))
    return sorted(scores,key=lambda t:(-t[0],t[1].family,t[1].seed,t[1].param))


def sequences(data,edges,inline=False):
    out=[];i=0
    for e in edges:
        if i<e.start:out.append((LIT,i,e.start-i,None))
        out.append((INLINE if inline else e.op,e.start,e.n,None if inline else e))
        i=e.end
    if i<len(data):out.append((LIT,i,len(data)-i,None))
    return out


def repeat_route(data,step=64):
    last={};out=[];start=0
    for i in range(0,len(data)-step+1,step):
        s=data[i:i+step];ref=last.get(s)
        if ref is not None:
            if i>start:out.append((LIT,start,i-start,None))
            out.append((COPY,i,step,i-ref));start=i+step
        if len(last)<32768 or ref is not None:last[s]=i
    if start<len(data):out.append((LIT,start,len(data)-start,None))
    return out


def arch(data,ops,mode="bytes",group=True,addr="abs",table=b"",crc=None):
    if len(data)>CAP or len(ops)>400000:raise ValueError("archive limit")
    sources=list(dict.fromkeys(e.source for op,_,_,e in ops if op in (REF,XOR,MODDIFF,PATCH)))
    if not any(s.family in (10,11,13) for s in sources):table=b""
    src={g:i for i,g in enumerate(sources)}
    xy=defaultdict(list)
    for op,_,_,e in ops:
        if op in (REF,XOR,MODDIFF,PATCH):xy[e.source].append(e.address)
    params={}
    meta=bytearray(ints(int(group),len(table)))+table
    if group:
        meta+=v(len(sources))
        for g in sources:
            h=xy[g]
            use=addr=="affine" and len(h)>=3 and all(h[i]-h[i-1]==h[1]-h[0] for i in range(2,len(h)))
            style=2 if use else int(addr=="delta" or addr=="affine")
            params[g]=[style,0,h[1]-h[0] if use else 0]
            meta+=g.wire()+v(style)
            if use:meta+=ints(h[0],vs(h[1]-h[0]))
    raw_header=len(meta)
    meta+=v(len(ops)); out=[]; residue=0;covered=0;details=[];count=Counter()
    for op,a,n,x in ops:
        at=len(meta);meta+=ints(op,n);count[op]+=1
        if op==LIT:out.append(data[a:a+n])
        elif op==INLINE:meta+=data[a:a+n]
        elif op==COPY:meta+=v(x)
        else:
            covered+=n
            g=x.source
            if group:
                meta+=v(src[g])
                style,prev,_=params[g]
                if style==0:meta+=v(x.address)
                if style==1:meta+=v(vs(x.address-prev))
                params[g][1]=x.address
            else:meta+=g.wire()+v(x.address)
            meta+=v(x.symbols)
            if op!=REF:
                meta+=v(len(x.patch))+x.patch;residue+=len(x.patch)
            if len(details)<1000:details.append(dict(file_offset=a,nbytes=n,source_address=x.address,
                symbols=x.symbols,description=len(meta)-at,opcode=op,**g.describe()))
    mz=Z.compress(bytes(meta));p=Z.compress(b"".join(out))
    hdr=HEADER.pack(b"ASM0",MODES.index(mode),0,len(data),zlib.crc32(data) if crc is None else crc,len(mz),len(p))
    return hdr+mz+p,dict(header_bytes=len(hdr),meta_bytes=len(mz),literals_bytes=len(p),meta_raw=len(meta),
                     source_table_raw=raw_header,model_table_raw=len(table),sources=len(sources),covered=covered,
                     residual_raw=residue,groups_affine=sum(v[0]==2 for v in params.values()),
                     exact_runs=count[REF],instructions=len(ops),matches=details,count=dict(count),address_style=addr)


def uz(d,lim):
    p=z.get_frame_parameters(d)
    if p.content_size>lim or p.window_size>CAP:raise ValueError("backend bound")
    return U.decompress(d,max_output_size=lim,allow_extra_data=False)


def decode(b,ready=None,profile=None):
    try:
        magic,mo,_,n,crc,a,l=HEADER.unpack_from(b)
        h=HEADER.size
        if magic!=b"ASM0" or mo>=len(MODES) or n>CAP or h+a+l!=len(b):raise ValueError("archive frame")
        mode=MODES[mo];r=Reader(uz(b[h:h+a],24<<20));literal=Reader(uz(b[h+a:],n))
        group,tn=r.get(),r.get()
        if group>1 or tn not in (0,256,512,4096):raise ValueError("model table")
        table=r.take(tn);defs=[]
        def src():
            gid,p,seed=r.get(),r.get(),r.get()
            if gid>=len(FAMILIES) or p>3:raise ValueError("generator")
            extra=(r.get()+1,r.get(),r.get()) if gid==12 else ()
            return Source(gid,seed,p,extra)
        if group:
            cnt=r.get()
            if cnt>4096:raise ValueError("source count")
            for _ in range(cnt):
                g,q=src(),r.get()
                if q>2:raise ValueError("address style")
                defs.append([g,q,r.get() if q==2 else 0,sv(r.get()) if q==2 else 0])
        count=r.get();out=bytearray();work=gen_elapsed=0
        if count>400000:raise ValueError("instruction count")
        cache={} if ready is None else ready
        for _ in range(count):
            op,amount=r.get(),r.get()
            if not 1<=amount<=n-len(out):raise ValueError("output bound")
            if op==LIT:d=literal.take(amount)
            elif op==INLINE:d=r.take(amount)
            elif op==COPY:
                q=r.get()
                if not amount<=q<=len(out):raise ValueError("copy")
                d=out[len(out)-q:len(out)-q+amount]
            elif op in (REF,XOR,MODDIFF,PATCH):
                if group:
                    k=r.get()
                    if k>=len(defs):raise ValueError("id")
                    d0=defs[k];g,kind,last,p=d0
                    q=r.get() if kind==0 else last+sv(r.get()) if kind==1 else last
                    d0[2]=q+p
                else:g,q=src(),r.get()
                length=r.get()
                work+=length+(q if g.family in (2,6,7,8,9,10,11,13) else 0)
                if not 0<=q<262144 or not 1<=length<=32768 or work>MAXW:raise ValueError("work")
                t=perf_counter()
                k=(g,mode,q,length,table)
                if k in cache:s=cache[k]
                else:
                    s=slice_view(g,mode,q,length,table)
                    if ready is not None and len(cache)<8192:cache[k]=s
                gen_elapsed+=perf_counter()-t
                d=rp.revert(s,mode)
                if op!=REF:
                    x=r.take(r.get())
                    if op==XOR:d=bytes(a^b for a,b in zip(d,x,strict=True))
                    elif op==MODDIFF:d=bytes((a+b)&255 for a,b in zip(d,x,strict=True))
                    else:
                        y=Reader(x);d=bytearray(d);m=y.get()
                        if m>len(d):raise ValueError("patch count")
                        prev=0
                        for _ in range(m):
                            prev+=y.get()
                            if prev>=len(d):raise ValueError("patch position")
                            d[prev]=y.take(1)[0]
                        y.end()
            else:raise ValueError("instruction")
            if len(d)!=amount:raise ValueError("record size")
            out.extend(d)
        r.end();literal.end()
        if len(out)!=n or zlib.crc32(out)!=crc:raise ValueError("roundtrip check")
        if profile is not None:profile.update(generation_s=gen_elapsed,regenerated_symbols=work)
        return bytes(out)
    except (struct.error,IndexError,z.ZstdError) as exc:raise ValueError("invalid frame") from exc
