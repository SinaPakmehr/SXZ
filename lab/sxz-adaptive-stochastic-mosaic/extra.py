from pathlib import Path
"""Independent ablations: algebra, objective locality, entropy, and residuals."""
import argparse
import cProfile
import hashlib
import heapq
import io
import math
import pstats
import random
import struct
from collections import Counter,defaultdict
from itertools import count
from statistics import median
from time import perf_counter
import zlib

import numpy as np

import asm as a
from experiment import OUT,save,run,trial,plant,ws
from inputs import pick,TRAIN

MASK=0xffffffff


def step(x):
    x^=(x<<13)&MASK;x^=x>>17;return (x^(x<<5))&MASK


def unshift(x,k,left):
    y=x
    for t in range(k,32,k):y^=(x<<t)&MASK if left else x>>t
    return y


def previous(x):return unshift(unshift(unshift(x,5,True),17,False),13,True)


def recover_xorshift(data,bits,extent=1536):
    """Blind at all four alignments; verify a state pair before trying origins."""
    out=[];tries=0;windows=0
    for phase in range(4):
        n=(len(data)-phase)//4
        words=np.frombuffer(data[phase:phase+n*4],"<u4")
        if len(words)<4:continue
        x=words[:-1].copy();x^=x<<13;x^=x>>17;x^=x<<5
        good=(x==words[1:]) & (x!=0)
        starts=np.flatnonzero(good[:-1]&good[1:])
        for i0 in starts[:256]:
            i=int(i0);y=int(words[i]);j=i+3;windows+=1
            while j<len(words) and good[j-1] and j-i<128:j+=1
            length=(j-i)*4
            for k in range((extent-length)//4+1):
                if y<1<<bits:
                    src=a.Source(2,y)
                    off=phase+i*4
                    assert a.generate(src,4*k,length)==data[off:off+length]
                    out.append(a.Edge(off,off+length,src,4*k,length))
                y=previous(y);tries+=1
    return out,dict(seed_offset_trials=tries,exact_verified_windows=windows,
                    data_words_checked=4*max(0,len(data)//4-2))


def fit_lcg(data):
    if len(data)<32 or len(data)%4:return None
    x=list(struct.unpack("<"+"I"*(len(data)//4),data))
    d=[y-u for u,y in zip(x,x[1:])]
    h=math.gcd(*(abs(u*w-v*v) for u,v,w in zip(d,d[1:],d[2:])))
    mods=[1<<32]+(list(dict.fromkeys(h//k for k in range(1,129) if h%k==0)) if h else [])
    for m in mods:
        if not max(x)<m<=1<<32:continue
        for i in range(min(12,len(d)-1)):
            if math.gcd(d[i],m)!=1:continue
            c=d[i+1]*pow(d[i],-1,m)%m
            b=(x[1]-c*x[0])%m
            if all((y*c+b)%m==z for y,z in zip(x,x[1:])):
                return a.Source(12,x[0],0,(m,c,b))
    return None


def algebra():
    rng=random.Random(650285)
    s=a.Source(2,0xe981b1)
    d=b"".join(rng.randbytes(70+i)+a.generate(s,64+i*148,72) for i in range(6))+rng.randbytes(49)
    rows=[]
    entries=[("artificial-xorshift-24",d)]
    entries+= [(p["name"],x) for p,x in pick("dev") if p["name"] in ("alice29.txt","irs1040.pdf","python-logo.png")]
    for name,x in entries:
        (h,meta),t=run(recover_xorshift,x,24)
        rows.append(dict(name=name,input_bytes=len(x),search_s=t,**meta,**trial(x,h,more=True)))
    for spec in (a.Source(12,0xba231,0,(2147483647,48271,101)),a.Source(12,721252,0,(1<<32,1664525,1013904223))):
        d=a.generate(spec,0,4096)
        recovered,t=run(fit_lcg,d[:96]);assert recovered==spec
        assert a.generate(recovered,0,len(d))==d
        es=[a.Edge(0,len(d),recovered,0,len(d))]
        rows.append(dict(name="artificial-unknown-modulus",parameters=spec.describe(),inference_s=t,
                         verified_outside_fit=len(d)-96,**trial(d,es,more=True)))
    save("algebra",rows)


def empirical():
    train=b"".join(p.read_bytes() for p in TRAIN)
    u=a.lookup(a.train_counts(train),256)
    v=a.lookup(a.train_counts(train,True),16)
    out=[]
    for f in range(12):
        for param in (range(4) if f==5 else range(2) if f in (3,4,7,9) else (0,)):
            s=a.Source(f,4662,param);t=u if f==10 else v if f==11 else b""
            d,dt=run(a.generate,s,0,100000,t)
            section,j=run(a.generate,s,65537,256,t);assert section==d[65537:65537+256]
            freq=Counter(d);h=-sum((k/len(d))*math.log2(k/len(d)) for k in freq.values())
            out.append(dict(**s.describe(),access=a.ACCESS[f],bytes=len(d),seconds=dt,
              throughput=len(d)/1e6/dt,seek_address=65537,seek_n=256,seek_s=j,
              empirical_h0=h,symbols_used=len(freq),
              adjacent_equal=sum(x==y for x,y in zip(d,d[1:]))/(len(d)-1),
              expected_adjacent_iid=sum((k/len(d))**2 for k in freq.values()),exact=True))
    save("families",out)


def objective():
    # Same-position byte agreement gives local search *more* information than
    # the blind exact task. Measure whether Hamming-1 neighbours inherit it.
    rng=random.Random(366113)
    ss=a.seeds(12)
    rows=[]
    for f in (0,3,4):
        x=a.matrix(f,0,ss,96,b"")
        bank=np.frombuffer(x,np.uint8).reshape(-1,96)
        for name,ref in (("planted",bank[1827]),("text",np.frombuffer(pick("dev")[0][1][:96],np.uint8))):
            score=np.count_nonzero(bank==ref,axis=1)
            pairs=np.array([(i,i^(1<<r)) for i in rng.sample(range(len(ss)),512) for r in (rng.randrange(12),)])
            rand=np.array([(i,rng.randrange(len(ss))) for i in pairs[:,0]])
            c1=float(np.corrcoef(score[pairs[:,0]],score[pairs[:,1]])[0,1])
            c2=float(np.corrcoef(score[rand[:,0]],score[rand[:,1]])[0,1])
            walked=[]
            ns=0
            for pos in rng.sample(range(len(ss)),48):
                for _ in range(12):
                    opts=[pos^(1<<j) for j in range(12)]
                    ns+=12
                    best=max(opts,key=lambda p:score[p])
                    if score[best]<=score[pos]:break
                    pos=best
                walked.append(int(score[pos]))
            naive=[int(score[rng.randrange(len(ss))]) for _ in range(ns)]
            rows.append(dict(family=a.FAMILIES[f],case=name,neighbour_corr=c1,random_corr=c2,
                      hill_trials=ns,hill_best=max(walked),random_best=max(naive),oracle_best=int(max(score)),
                      same_indices_known=True))
    save("objective",rows)


def tree(weights):
    heap=[];ix=count()
    for i,n in enumerate(weights):
        if n>0:heap.append((int(n),next(ix),i))
    heapq.heapify(heap)
    while len(heap)>1:
        x=heapq.heappop(heap);y=heapq.heappop(heap);heapq.heappush(heap,(x[0]+y[0],next(ix),(x[2],y[2])))
    return heap[0][2]


def huff_tables(lut,width,add):
    rows=[]
    for i in range(0,len(lut),width):
        weights=np.bincount(np.frombuffer(lut[i:i+width],np.uint8),minlength=256)+add
        t=tree(weights);sym={}
        def recurse(q,b,w):
            if isinstance(q,int):sym[q]=(b,max(1,w));return
            recurse(q[0],2*b,w+1);recurse(q[1],2*b+1,w+1)
        recurse(t,0,0)
        rows.append((t,sym,weights))
    return rows


def entropy_pack(data,table,width,model_charge=True):
    # Smoothing gives an escape-equivalent positive weight to every byte,
    # including those absent from the generator's quantized distribution.
    rows=huff_tables(table,width,1);out=bytearray();b=nb=0;prev=0;shannon=0.;bits=0
    logs=[[-math.log2(float(n)/int(w.sum())) for n in w] for _,_,w in rows]
    for x in data:
        q=prev if width==16 else 0
        v,n=rows[q][1][x]
        b=b<<n|v;nb+=n;bits+=n;shannon+=logs[q][x]
        while nb>=8:
            nb-=8;out.append((b>>nb)&255);b&=(1<<nb)-1
        prev=x
    if nb:out.append(b<<(8-nb))
    mt=a.Z.compress(table);frame=struct.pack("<BII",int(width==16),len(data),len(mt) if model_charge else 0)
    return frame+(mt if model_charge else b"")+out,dict(model_bytes=len(mt),coded_bits=bits,shannon_bits=shannon)


def entropy_unpack(blob,provided=None):
    m,n,nt=struct.unpack_from("<BII",blob);width=16 if m else 256
    table=a.U.decompress(blob[9:9+nt]) if nt else provided
    ts=[t for t,_,_ in huff_tables(table,width,1)];out=bytearray();node=ts[0]
    if not n:return b""
    for x in blob[9+nt:]:
        for bit in range(7,-1,-1):
            node=node[(x>>bit)&1]
            if isinstance(node,int):
                out.append(node)
                if len(out)==n:return bytes(out)
                node=ts[node if m else 0]
    raise ValueError("truncated entropy stream")


def entropy():
    train=b"".join(p.read_bytes() for p in TRAIN)
    tables={w:a.lookup(a.train_counts(train,w==16),w) for w in (256,16)}
    rows=[]
    ins=[(p["name"],d) for p,d in pick("dev") if p["name"] in ("alice29.txt","python-logo.png","irs1040.pdf")]
    ins.append(("artificial-histogram",plant("distribution")[0]))
    for name,d in ins:
        for width in (256,16):
            for trained in (True,False):
                t=tables[width] if trained else a.lookup(a.train_counts(d,width==16),width)
                (blob,meta),pt=run(entropy_pack,d,t,width)
                restored,dt=run(entropy_unpack,blob);assert restored==d
                row=dict(name=name,file_bytes=len(d),fitted=not trained,order=int(width==16),
                         huffman_bytes=len(blob),huffman_excluding_model=len(blob)-meta["model_bytes"],
                         huffman_enc_s=pt,huffman_dec_s=dt,zstd=len(a.Z.compress(d)),exact=True,**meta)
                with a.Bank([(10 if width==256 else 11,0,a.seeds(12))],table=t) as ix:
                    h,s=ix.search(d)
                    row.update(search=s,generator_result=trial(d,h,table=t))
                rows.append(row)
    save("entropy",rows)


def mixture():
    document=b"".join(p.read_bytes() for p in TRAIN)
    table=a.lookup(a.train_counts(document),256)+bytes(range(256))
    selected=[(p["name"],d) for p,d in pick("dev") if p["name"] in ("alice29.txt","python-logo.png","irs1040.pdf")]
    synthetic=a.generate(a.Source(13,146,1),0,96,table)
    selected.append(("artificial-hidden-state",synthetic+random.Random(977612).randbytes(251)))
    rows=[]
    for f,params,t in ((0,0,b""),(13,1,table)):
        with a.Bank([(f,params,a.seeds(8))],table=t) as bank:
            for name,d in selected:
                h,s=bank.search(d)
                rows.append(dict(name=name,source=a.FAMILIES[f],search=s,**trial(d,h,table=t,more=True)))
    save("mixture",rows)


def approx_edges(data,h,n=1536):
    proposals=[]
    cache={}
    for e in sorted(h,key=lambda e:-e.n)[:4000]:
        if e.source not in cache:cache[e.source]=a.generate(e.source,0,n)
        s=cache[e.source];off=e.address;st=e.start;r=e.n
        err=0
        start,stop=0,r
        for side in (-1,1):
            j=-1 if side<0 else r
            while -180<=j<=r+180 and 0<=off+j<n and 0<=st+j<len(data):
                if data[st+j]!=s[off+j]:
                    if err>=2:break
                    err+=1
                if side<0:start=j
                else:stop=j+1
                j+=side
        if not err or stop-start-r<11:continue
        x=data[st+start:st+stop];z=s[off+start:off+stop]
        mism=[(i,b) for i,(b,c) in enumerate(zip(x,z)) if b!=c]
        prev=0;buf=bytearray(a.v(len(mism)))
        for i,b in mism:buf+=a.ints(i-prev)+bytes([b]);prev=i
        proposals.append((a.Edge(st+start,st+stop,e.source,off+start,len(x),bytes(buf),a.PATCH),
                         a.Edge(st+start,st+stop,e.source,off+start,len(x),bytes(b^c for b,c in zip(x,z)),a.XOR),
                         a.Edge(st+start,st+stop,e.source,off+start,len(x),bytes((b-c)&255 for b,c in zip(x,z)),a.MODDIFF)))
    return proposals


def approximate():
    data,planted=plant("noisy")
    ins=[("artificial-two-errors",data)]
    ins.extend((p["name"],d) for p,d in pick("dev") if p["name"] in ("alice29.txt","python-logo.png","irs1040.pdf"))
    out=[]
    with a.Bank([(0,0,np.arange(1024,dtype=np.uint32))],1536) as b:
        for name,d in ins:
            h,s=b.search(d,low_bytes=7)
            ap=approx_edges(d,h)
            results={}
            _,route=a.dp(h)
            if ap:
                for j,tag in enumerate(("sparse","xor","moddiff")):
                    # Compare identical boundaries/address recipes for every residue.
                    # Only the residue encoding changes; packed size is the judge.
                    if j==0:
                        _,rr=a.dp(h+[p[0] for p in ap],True)
                    models={(x.start,x.end,x.source,x.address):p[j] for p in ap for x in p[:1]}
                    seq=[models.get((x.start,x.end,x.source,x.address),x) if x.op==a.PATCH else x for x in rr]
                    blob,info=a.arch(d,a.sequences(d,seq),group=True)
                    assert a.decode(blob)==d
                    results[tag]=dict(bytes=len(blob),**info)
            for tag,seq in (("direct",[]),("exact",route)):
                blob,info=a.arch(d,a.sequences(d,seq),group=bool(seq))
                assert a.decode(blob)==d
                results[tag]=dict(bytes=len(blob),**info)
            out.append(dict(name=name,n=len(d),approx_candidates=len(ap),search_stats=s,methods=results))
    save("approximate",out)


def profile():
    d,_=plant("multi")
    seeds=np.arange(1024,dtype=np.uint32);mem=ws()
    p=cProfile.Profile()
    def run_all():
        with a.Bank([(0,0,seeds)],1536) as ix:
            after=ws()
            h,s=ix.search(d)
            return after,trial(d,h,more=True),ix.gen_s,ix.index_s
    after,v,gen,idx=p.runcall(run_all)
    string=io.StringIO()
    pstats.Stats(p,stream=string).sort_stats("cumulative").print_stats(35)
    (OUT/"profile.txt").write_text(string.getvalue(),encoding="utf-8")
    save("profile",dict(before=mem,after_index=after,after_all=ws(),generator_s=gen,index_s=idx,
        input_bytes=len(d),native_dll_bytes=Path(a.N._name).stat().st_size,
        python_decoder_bytes=(a.ROOT/"asm.py").stat().st_size,result=v,
        dependencies=["CPython","zstandard","NumPy","Rust cdylib","read-only represent.py"],memory_scope="process working set"))


if __name__=="__main__":
    x=argparse.ArgumentParser()
    x.add_argument("experiment",choices=["algebra","empirical","objective","entropy","approximate","profile","mixture"])
    globals()[x.parse_args().experiment]()
