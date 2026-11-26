"""Experiment harness. Use sequential runs for timing; update only this folder."""
import argparse
import ctypes as ct
import hashlib
import io
import json
import lzma
import platform
import random
import statistics
import sys
import time
import zipfile
import zlib
from collections import Counter,defaultdict
from pathlib import Path

import brotli
import numpy as np
import zstandard as z

import catalog as c
import index
import mosaic as m
import represent as rp
from inputs import ROOT,pick,TRAIN,E

RESULT=ROOT/"results"
STYLES={"A-raw":0,"A-meta":1,"A-hybrid":3,"B-raw":0,"B-meta":1,"B-hybrid":3}


def write(name,data):
    RESULT.mkdir(exist_ok=True)
    f=RESULT/(name+".json");t=f.with_suffix(".tmp")
    t.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    t.replace(f)


def timed(fn,*args,**kw):
    t=time.perf_counter()
    data=fn(*args,**kw)
    return data,time.perf_counter()-t


def digest(d): return hashlib.sha256(d).hexdigest()


def clock(d,coded,fn,reps=3):
    dt=[]
    for _ in range(reps):
        val,t=timed(fn,coded)
        if val!=d: raise AssertionError("round trip")
        dt.append(t)
    med=statistics.median(dt)
    return dict(decode_s=med,decode_MBs=len(d)/1e6/max(1e-9,med),repeats_s=dt,bytes=len(coded),exact=True)


def ws():
    if __import__('os').name != 'nt':
        import resource, sys
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
        return dict(peak=peak,current=None)
    class C(ct.Structure):
        _fields_=[("size",ct.c_ulong),("faults",ct.c_ulong)]+[(k,ct.c_size_t) for k in
                 ("peak","now","p1","p2","p3","p4","p5","p6")]
    s=C(ct.sizeof(C)); ct.windll.kernel32.GetCurrentProcess.restype=ct.c_void_p
    f=ct.windll.psapi.GetProcessMemoryInfo
    f.argtypes=[ct.c_void_p,ct.POINTER(C),ct.c_ulong]
    if not f(ct.windll.kernel32.GetCurrentProcess(),ct.byref(s),ct.sizeof(s)): raise OSError("memory metrics")
    return dict(peak=s.peak,current=s.now)


def zc(level=3,dictionary=None):
    return z.ZstdCompressor(level=level,write_checksum=True,dict_data=dictionary)


def local_dictionary():
    # Training samples disjoint by filename and content source from test subset.
    samples=[]
    for p in TRAIN:
        b=p.read_bytes()
        samples.extend(b[i:i+4096] for i in range(0,len(b),4096) if len(b[i:i+4096])>=512)
    return z.train_dictionary(16384,samples)


def zip_pack(d):
    b=io.BytesIO()
    i=zipfile.ZipInfo("payload"); i.compress_type=zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(b,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as f: f.writestr(i,d)
    return b.getvalue()


def references(d,dct,full=True):
    pairs={
        "zstd-3":(zc().compress,m.UC.decompress),
        "deflate-6":(lambda d:zlib.compress(d,6),zlib.decompress),
        "zip-6":(zip_pack,lambda d:zipfile.ZipFile(io.BytesIO(d)).read("payload")),
        "zstd-trained-3":(zc(dictionary=dct).compress,z.ZstdDecompressor(dict_data=dct).decompress),
    }
    if full:
        pairs.update({"zstd-12":(zc(12).compress,m.UC.decompress),
                      "brotli-7":(lambda d:brotli.compress(d,quality=7),brotli.decompress),
                      "xz-6":(lambda d:lzma.compress(d,preset=6),lzma.decompress)})
    rows={}
    for name,(enc,dec) in pairs.items():
        b,t=timed(enc,d)
        vals=clock(d,b,dec)
        rows[name]=dict(encode_s=t,**vals)
        if name=="zstd-trained-3":
            q=len(dct.as_bytes())
            rows[name].update(dictionary_bytes=q,standalone_bytes=q+len(b),shared_at_19_bytes=len(b)+q/19)
    return rows


def base_ops(d): return [(m.LIT,0,len(d),None)] if d else []


def synthetic(total=1000000):
    n=c.sizes(total);r=random.Random(572859)
    d=bytearray(r.randbytes(799))
    planted=[]
    for j,g in enumerate((0,1,2,10,12,24,28,0,15)):
        p=r.randrange(30,n[g]-1100); k=(8,17,32,81,256,512,1024,720,128)[j]
        d+=r.randbytes(r.randrange(200,850))
        s=c.stream(g,"bytes",n[g])[p:p+k]
        planted.append(dict(target_byte=len(d),gid=g,addr=p,length=k))
        d+=s
        if j in (5,6,7):
            d+=r.randbytes(1221);d+=s
    return bytes(d),planted


def optimize(d,h,e,mode,total,kind,seed,parts,heavy=True):
    all_rows={}; candidates={}; cache={}
    crc=zlib.crc32(d)
    orig=base_ops(d)
    raw=e
    g=m.guarded_edges(e,d)
    chosen_raw=m.plan(raw)
    chosen_z=m.plan(g)
    chosen_g=m.plan(g,"greedy")
    maps={"direct":orig,
          "A":m.definitions(d,chosen_raw),
          "A-guard":m.definitions(d,chosen_z),
          "A-greedy":m.definitions(d,chosen_g)}
    if heavy:
        maps["B"]=m.definitions(d,chosen_raw,True)
        maps["B-guard"]=m.definitions(d,chosen_z,True)
        maps["B-repeat-only"]=m.definitions(d,chosen_raw,True,True)
        maps["internal"]=m.internal_periodic(d)
    else:
        maps["B"]=m.definitions(d,chosen_raw,True)
        maps["B-guard"]=m.definitions(d,chosen_z,True)
        maps["B-repeat-only"]=m.definitions(d,chosen_raw,True,True)
    for name,ops in maps.items():
        choices=(0,1,3) if len(d)<=6<<20 and name in ("direct","A","B","B-repeat-only") else (3,)
        for style in choices:
            key=f"{name}-{style}"
            warm=m.Banks({(kind,mode,total,seed,j):t for j,t in enumerate(parts)})
            (blob,audit),et=timed(m.archive,d,ops,mode,kind,seed,total,style,False,crc)
            dh=digest(blob)
            if dh not in cache:
                trace=[]
                if m.decode(blob,warm,trace)!=d: raise AssertionError("mosaic exactness")
                if heavy:
                    r=clock(d,blob,lambda b:m.decode(b,warm),3)
                else:
                    r=dict(bytes=len(blob),exact=True)
                cache[dh]=(r,trace)
            r,trace=cache[dh]
            if len(audit["matches"])>120:
                audit["matches_count"]=len(audit["matches"])
                audit["matches"]=audit["matches"][:120]
                trace=trace[:120]
            all_rows[key]=dict(**r,**audit,encode_recipe_s=et,digest=dh,delta=False,
                               regeneration_trace_warm=trace)
            if style==3 and name!="direct":
                candidates[key]=blob if heavy else None
                if name in ("A","B","A-guard"):
                    (alt,aux),at=timed(m.archive,d,ops,mode,kind,seed,total,style,True,crc)
                    if len(alt)<len(blob):
                        if m.decode(alt,warm)!=d: raise AssertionError("delta")
                        a=clock(d,alt,lambda x:m.decode(x,warm),3) if heavy else dict(bytes=len(alt),exact=True)
                        all_rows[key+"d"]=dict(**a,**aux,encode_recipe_s=at,digest=digest(alt),delta=True)
                        if len(aux["matches"])>120:
                            aux["matches"][:]=aux["matches"][:120]
                        candidates[key+"d"]=alt if heavy else None
    if heavy:
        for tag in ("A","B"):
            options={k:x for k,x in candidates.items() if k.startswith(tag) and "repeat-only" not in k}
            k,b=min(options.items(),key=lambda kv:len(kv[1]))
            bank=m.Banks(); trace=[]
            val,t=timed(m.decode,b,bank,trace)
            if val!=d: raise AssertionError("cold decode")
            all_rows[k].update(cold_decode_s=t,cold_gen_s=bank.seconds,cold_generated_symbols=bank.symbols,
                               cold_decode_MBs=len(d)/1e6/max(1e-9,t),regeneration_trace_cold=trace[:120])
    bestrel=min((k for k in candidates if k[0] in "AB" and "repeat-only" not in k),key=lambda k:all_rows[k]["bytes"])
    direct=all_rows["direct-3"]["bytes"]
    b=all_rows[bestrel]
    min_diff=direct-b["bytes"]
    # A is the attribution ablation; B repeat may have an advantage unrelated to math.
    besta=min((k for k in candidates if k.startswith("A")),key=lambda k:all_rows[k]["bytes"])
    return dict(rows=all_rows,summary=dict(positive_raw_candidates=len(raw),local_backend_candidates=len(g),
         selected_raw=len(chosen_raw),selected_greedy=len(chosen_g),best_math=bestrel,best_A=besta,
         net_vs_direct=min_diff,net_A_vs_direct=direct-all_rows[besta]["bytes"],
         net_vs_repeat_only=all_rows["B-repeat-only-3"]["bytes"]-b["bytes"],
         fallback_bytes=min(direct,b["bytes"]),economic_coverage=b["covered_bytes"]/len(d) if min_diff>0 else 0,
         matched_raw_covered_bytes=sum(t.b-t.a for t in chosen_raw),
         local_repeat_selected=all_rows["B-3"]["repeated_bytes"]))


def compare(suite):
    dct,training_time=timed(local_dictionary)
    rows=[]; inds=[];catalogs=[]
    if suite=="dev":
        entries=pick("dev"); mode_levels=[("bytes",n) for n in c.LEVELS]
    elif suite=="radix":
        entries=pick("radix"); mode_levels=[(mo,100000) for mo in rp.MODES]
    elif suite=="test":
        entries=pick("test"); mode_levels=[("bytes",1000000)]
    elif suite=="control":
        d,p=synthetic(); entries=[(dict(name="synthetic-mosaic",input_bytes=len(d),sha256=digest(d),planted=p),d)]
        mode_levels=[("bytes",1000000)]
    else: raise ValueError("suite")
    if suite in ("dev","test","control"):
        refs={}
        for meta,d in entries:
            print("reference",suite,meta["name"],len(d),flush=True)
            refs[meta["name"]]=references(d,dct,full=suite!="control")
        write("reference-"+suite,dict(inputs=[meta for meta,_ in entries],rows=refs,
                 train=dict(bytes=len(dct.as_bytes()),seconds=training_time,inputs=[str(x) for x in TRAIN],
                            dictionary_sha256=digest(dct.as_bytes()))))

    for mode,total in mode_levels:
        math,p=c.generate(mode,total)
        for kind in c.KINDS:
            seeds=(0,) if kind=="math" else range(len(c.SEEDS))
            for seed in seeds:
                if kind=="math": parts,prof=math,p
                else: parts,prof=c.generate(mode,total,kind,seed,math)
                mem0=ws()
                ix,it=timed(index.Index,parts,mode)
                memory=ws()
                tag=dict(mode=mode,total=total,kind=kind,seed=seed,
                         seed_effective=None if kind=="math" else c.SEEDS[seed])
                inds.append(dict(**tag,generation=prof,index_s=it,memory_before=mem0,
                                 memory_build=memory,estimated_native_bytes=9*total+131072))
                print("bank",suite,mode,total,kind,seed,"index",round(it,3),flush=True)
                for meta,d in entries:
                    (s,off),vt=timed(rp.view,d,mode)
                    cap=30000 if len(d)>4<<20 else 80000
                    (hh,st),qt=timed(ix.query,s,cap)
                    start=time.perf_counter()
                    edge=m.expanded_edges(hh,mode,off,allow_trim=len(d)<2_500_000)
                    # Repeated, locally dominated long data is not used to
                    # indefinitely grow the Python optimization graph.
                    q=optimize(d,hh,edge,mode,total,kind,seed,parts,
                               heavy=(kind=="math" and suite in ("test","control")
                                      and len(d)<=6<<20))
                    q.update(input=meta,**tag,index_query_s=qt,view_s=vt,plan_and_measure_s=time.perf_counter()-start,
                             stats=st,cap=cap,process_memory=ws())
                    rows.append(q)
                ix.close()
                write(suite,dict(index=inds,rows=rows))
    write("catalog",dict(generators=c.manifest(),bank_sizes={n:c.sizes(n) for n in c.LEVELS},
          controls=c.SEEDS,representations=rp.UNITS,python=sys.version,os=platform.platform(),
          numpy=np.__version__,zstd=z.__version__,brotli=brotli.__version__))


def scale():
    parts,g=c.generate("bytes",1000000)
    ix,bt=timed(index.Index,parts,"bytes")
    big=E.read_bytes()
    rows=[]
    for n in (1000000,10000000,100000000):
        d=big[:n]
        (h,s),it=timed(ix.query,d,30000)
        e=m.expanded_edges(h,"bytes",None,allow_trim=False)
        o,t=timed(optimize,d,h,e,"bytes",1000000,"math",0,parts,False)
        kinds={}
        for key in ("direct-3",o["summary"]["best_math"]):
            sm=o["rows"][key]
            # Reconstruct the exact recipes for warm/cold throughput tests.
            # Only fallback/selected records are counted: don't hide losing candidates.
            if key=="direct-3":
                ops=base_ops(d)
            else:
                candidates=m.guarded_edges(e,d) if "guard" in key or "greedy" in key else e
                es=m.plan(candidates,"greedy" if "greedy" in key else "dp")
                ops=m.definitions(d,es,key.startswith("B"))
            b,a=m.archive(d,ops,"bytes","math",0,1000000,3,sm["delta"])
            assert len(b)==sm["bytes"]
            cache=m.Banks({("math","bytes",1000000,0,j):x for j,x in enumerate(parts)})
            cold=m.Banks()
            q=clock(d,b,lambda x:m.decode(x,cache),3)
            v,ct=timed(m.decode,b,cold)
            assert v==d
            kinds[key]=dict(**q,cold_s=ct,cold_generation_s=cold.seconds,peak=ws(),**a)
        row=dict(name="enwik8",input_bytes=n,whole_file=n==len(big),sha256=digest(d),query_s=it,
                 plan_experiment_s=t,index_s=bt,generation=g,search=s,stats=o["summary"],
                 decode=kinds,working_set=ws())
        rows.append(row);write("scale",rows)
        print("scale",n,it,o["summary"],flush=True)
    ix.close()


def previous():
    sys.path.insert(0,str(ROOT.parent/"zip-protocol"))
    from experiments.sxz4 import spans4,transforms4
    rows=[]
    for meta,d in pick("reference"):
        chain,ts=timed(transforms4.screen,d,sample=32768)
        ch=chain[0][1] if chain else (0,)
        (b,s),t=timed(spans4.pack,d,chain=ch)
        a=clock(d,b,spans4.unpack)
        rows.append(dict(meta=meta,method="SXZ4-on",chain=ch,enc_s=t+ts,spans=s.spans,probes=s.probes,**a))
        write("previous",rows)
        print(meta["name"],len(b),flush=True)


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("suite",choices=["dev","radix","test","control","scale","previous"])
    q=a.parse_args()
    if q.suite in ("scale","previous"): globals()[q.suite]()
    else: compare(q.suite)
