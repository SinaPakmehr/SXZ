"""Independent index, BBP, resource, and post-exact approximate experiments."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import cProfile
import hashlib
import io
import json
import os
from pathlib import Path
import pstats
import random
import statistics
import subprocess
import sys
from tempfile import TemporaryDirectory

import catalog as c
import index
from inputs import ROOT,pick,E
import measure as e
import mosaic as m
import represent as rp


def suffix_array(d):
    """One ordinary prefix-doubling array; explicit separator rank."""
    n=len(d); r=list(d); order=list(range(n)); k=1
    while k<n:
        order.sort(key=lambda i:(r[i],r[i+k] if i+k<n else -1))
        nr=[0]*n
        p=-1; last=None
        for i in order:
            h=(r[i],r[i+k] if i+k<n else -1)
            if h!=last: p+=1; last=h
            nr[i]=p
        if p==n-1: break
        r=nr;k*=2
    return order


def suffix_count(t,ints,sa,k):
    n=0
    for i in range(len(t)-k+1):
        x=t[i:i+k]
        lo,hi=0,len(sa)
        while lo<hi:
            p=(lo+hi)//2
            b=sa[p]
            if ints[b:b+k]<x: lo=p+1
            else: hi=p
        n+=int(lo<len(sa) and ints[sa[lo]:sa[lo]+k]==x)
    return n


def comparison():
    _,data=pick("dev")[0]
    # Fixed probe prefix for index microbenchmark, never included as a validation file.
    d=data[:65536]; ti=tuple(d); out=[]
    for n in (8192,100000):
        a,p=c.generate("bytes",n)
        ix,it=e.timed(index.Index,a,"bytes")
        (h,st),qt=e.timed(ix.query,d,0,3)
        flat=tuple(b for part in a for b in (*part,256))
        sa,bt=e.timed(suffix_array,flat)
        matches,mt=e.timed(suffix_count,ti,flat,sa,3)
        assert matches==st["count"]
        out.append(dict(symbols=n,subject_bytes=len(d),target_starts=st["count"],
                     kmer=dict(index_s=it,search_s=qt),
                     suffix_python=dict(index_s=bt,search_s=mt)))
        ix.close()
    a,_=c.generate("bytes",1000000)
    with index.Index(a,"bytes") as ix:
        data=[d for meta,d in pick("dev") if meta["name"] in ("gull.jpg","irs1040.pdf")]
        def task(x): return ix.query(x,0)[1]
        sequential,ts=e.timed(lambda:list(map(task,data)))
        with ThreadPoolExecutor(2) as pool:
            parallel,tp=e.timed(lambda:list(pool.map(task,data)))
        assert parallel==sequential
    e.write("index-comparison",dict(rows=out,parallel=dict(seconds_1=ts,seconds_2=tp,
                        files=[len(x) for x in data],exact=True)))


def bbp_profile():
    q=[]
    for off in (0,8192,100000):
        n=24
        x,t=e.timed(c.bbp,off,n)
        y,tp=e.timed(c.constant,"pi",(),off+n,16)
        assert x==y[off:]
        q.append(dict(hex_address=off,num=n,direct_s=t,prefix_s=tp,hex=x.hex(),exact=True))
    e.write("bbp",q)


def decode_worker(path,kind):
    data=Path(path).read_bytes()
    before=e.ws()
    banks=m.Banks(); x,cold=e.timed(m.decode,data,banks)
    warm=[]
    for i in range(5):
        w,t=e.timed(m.decode,data,banks)
        assert w==x
        warm.append(t)
    now=e.ws()
    print(json.dumps(dict(peak_before=before["peak"],peak_after=now["peak"],cold_s=cold,
          cold_gen_s=banks.seconds,bank_cache_bytes=sum(map(len,banks.cache.values())),warm_s=warm,
          warm_median_s=statistics.median(warm),output_bytes=len(x),digest=e.digest(x),method=kind)))


def profile():
    n=1_000_000
    data,_=e.synthetic(n)
    a,_=c.generate("bytes",n)
    with index.Index(a,"bytes") as ix:
        h,st=ix.query(data)
        edges=m.expanded_edges(h,"bytes",None)
    p=cProfile.Profile()
    result=p.runcall(e.optimize,data,h,edges,"bytes",n,"math",0,a,True)
    s=io.StringIO()
    pstats.Stats(p,stream=s).sort_stats("cumulative").print_stats(32)
    (e.RESULT/"profile.txt").write_text(s.getvalue(),encoding="utf-8")
    inputs=[("synthetic",data,m.definitions(data,m.plan(edges),True))]
    # Measure a real equal-size/losing recipe and the direct fallback too.
    name,d=next((a["name"],d) for a,d in pick("dev") if a["name"]=="irs1040.pdf")
    with index.Index(a,"bytes") as ix:
        h,_=ix.query(d)
    es=m.expanded_edges(h,"bytes",None)
    inputs.extend([(name,d,m.definitions(d,m.plan(es))),
                   (name+"-direct",d,e.base_ops(d))])
    rs=[]
    with TemporaryDirectory() as td:
        path=Path(td)/"decode.msm"
        for name,d,ops in inputs:
            b,meta=m.archive(d,ops,"bytes","math",0,n,3)
            path.write_bytes(b)
            pp=subprocess.run([sys.executable,"-B",str(ROOT/"diagnostics.py"),"worker",str(path),name],
                              capture_output=True,text=True,check=True,timeout=40)
            row=json.loads(pp.stdout)
            assert row["digest"]==e.digest(d)
            rs.append(dict(**row,coded_bytes=len(b),meta=meta))
    dep_path=ROOT/".deps"
    e.write("decoder-resources",dict(rows=rs,
        flint_dependency_installed_B=sum(p.stat().st_size for p in dep_path.rglob("*") if p.is_file()),
        fixed_python_source_B=sum((ROOT/f).stat().st_size for f in ("catalog.py","represent.py","mosaic.py")),
        candidate_bank_bytes=n,optional_bank_zstd_bytes=len(m.Z.compress(b"".join(a))),
        shared_cost_examples=[dict(files=j,raw_bank_each_B=n/j,zstd_bank_each_B=len(m.Z.compress(b"".join(a)))/j)
                              for j in (1,19,1000)]))


def approximate():
    n=1000000
    a,_=c.generate("bytes",n)
    dct=e.local_dictionary()
    rows=[]
    ss,planted=e.synthetic()
    rng=random.Random(4)
    changed=bytearray(ss)
    for x in planted:
        if x["length"]>64:
            for pos in (x["length"]//3,2*x["length"]//3):
                changed[x["target_byte"]+pos]^=rng.randrange(1,256)
    inputs=[("artificial-2-exceptions",bytes(changed))]+[(p["name"],d) for p,d in pick("dev")]
    with index.Index(a,"bytes") as ix:
        for name,d in inputs:
            h,st=ix.query(d,min_len=8)
            exact=m.expanded_edges(h,"bytes",None)
            picked={}
            # Bounded seed-and-extend; never helps the prior exact experiment.
            for i,g,o,k in h[:20000]:
                if k>512: continue
                ref=a[g]
                mismatch=[]; pos=k; last_good=k
                lim=min(len(d)-i,len(ref)-o,k+128)
                while pos<lim:
                    if d[i+pos]!=ref[o+pos]:
                        if len(mismatch)==2: break
                        mismatch.append((pos,d[i+pos]))
                    else: last_good=pos+1
                    pos+=1
                if last_good-k<9: continue
                diff=[(j,x) for j,x in mismatch if j<last_good]
                b=b"".join(m.ints(j,v) for j,v in diff)
                edge=m.Edge(i,i+last_good,g,o,last_good,b"",b,len(diff))
                if not diff or edge.desc>=last_good: continue
                picked[(i,g,o)]=edge
            tried=exact+list(picked.values())
            h1=m.plan(m.guarded_edges(exact,d))
            h2=m.plan(m.guarded_edges(tried,d))
            rows_for={}
            for tag,ops in (("direct",e.base_ops(d)),
                            ("exact",m.definitions(d,h1)),
                            ("approx",m.definitions(d,h2))):
                blob,ms=m.archive(d,ops,"bytes","math",0,n,3)
                bank=m.Banks({("math","bytes",n,0,j):v for j,v in enumerate(a)})
                q=e.clock(d,blob,lambda b:m.decode(b,bank),3)
                rows_for[tag]=dict(**q,**ms)
            rows.append(dict(name=name,input_bytes=len(d),sha256=e.digest(d),
                             approx_candidates=len(picked),methods=rows_for,synthetic_only=name.startswith("artificial")))
    e.write("approximate",rows)


def source_ablation():
    total=1000000
    parts,_=c.generate("bytes",total)
    s,_=e.synthetic()
    ins=[("artificial-multi-source",s)]+[(meta["name"],d) for meta,d in pick("dev")]
    rows=[]
    with index.Index(parts,"bytes") as ix:
        for name,data in ins:
            r,_=ix.query(data)
            edges=m.expanded_edges(r,"bytes",None)
            es=m.guarded_edges(edges,data)
            opts=[]
            for i in (None,*sorted({x.gid for x in es})):
                plan=m.plan(es,gid=i)
                ops=m.definitions(data,plan)
                b,meta=m.archive(data,ops,"bytes","math",0,total,3)
                assert m.decode(b)==data
                opts.append(dict(gid=i,bytes=len(b),matched_bytes=meta["covered_bytes"],chosen=len(plan)))
            b,size=m.archive(data,e.base_ops(data),"bytes","math",0,total,3)
            rows.append(dict(name=name,source_options=opts,direct_bytes=len(b)))
    e.write("source-ablation",rows)


def same_splits():
    load=lambda name:json.loads((e.RESULT/(name+".json")).read_text(encoding="utf-8"))
    observed=[row for row in load("test")["rows"]
              if row["kind"]=="math" and row["summary"]["net_vs_direct"]>0]
    observed += [row for row in load("radix")["rows"] if row["kind"]=="math" and row["mode"]!="bytes"
                 and row["summary"]["net_vs_direct"]>=128]
    cases=[]
    for row in observed:
        cases.append((row["input"]["name"],Path(row["input"]["path"]).read_bytes(),row["mode"],
                      row["total"],row["summary"]["best_math"],row["rows"][row["summary"]["best_math"]]))
    end=load("scale")[-1]; best=end["stats"]["best_math"]
    cases.append(("enwik8",E.read_bytes(),"bytes",1000000,best,end["decode"][best]))
    out=[]
    for name,d,mode,lv,key,previous in cases:
        parts,_=c.generate(mode,lv)
        with index.Index(parts,mode) as ix:
            symbols,offset=rp.view(d,mode)
            hits,_=ix.query(symbols,30000 if len(d)>4<<20 else 80000)
        edge=m.expanded_edges(hits,mode,offset,allow_trim=len(d)<2_500_000)
        pool=m.guarded_edges(edge,d) if "guard" in key or "greedy" in key else edge
        sel=m.plan(pool,"greedy" if "greedy" in key else "dp")
        ops=m.definitions(d,sel,key.startswith("B"))
        bs,bsmeta=m.archive(d,ops,mode,"math",0,lv,3,key.endswith("d"))
        control=[(m.INLINE,a,b,None) if op==m.SLICE else (op,a,b,info) for op,a,b,info in ops]
        assert len(bs)==previous["bytes"]
        bc,bcmeta=m.archive(d,control,mode,"math",0,lv,3)
        z0,zmeta=m.archive(d,e.base_ops(d),mode,"math",0,lv,3)
        bnk=m.Banks()
        assert m.decode(bs,bnk)==m.decode(bc)==m.decode(z0)==d
        out.append(dict(name=name,mode=mode,input_bytes=len(d),archive_bytes=len(bs),inline_bytes=len(bc),
                        direct_bytes=len(z0),gain_math_vs_same_splits=len(bc)-len(bs),
                        reference_bytes=bsmeta["covered_bytes"],mosaic_cost=bsmeta,inline_cost=bcmeta,
                        excerpts=[dict(target=a,source=c.NODES[info.gid].name,offset=info.addr,
                                       length=b-a,prefix=d[a:min(b,a+32)].hex())
                                  for op,a,b,info in ops if op==m.SLICE][:40],exact=True))
    e.write("same-splits",out)


if __name__=="__main__":
    args=argparse.ArgumentParser()
    args.add_argument("mode",choices=["comparison","bbp_profile","profile","approximate","source_ablation","same_splits","worker"])
    args.add_argument("rest",nargs="*")
    a=args.parse_args()
    (decode_worker if a.mode=="worker" else globals()[a.mode])(*a.rest)
