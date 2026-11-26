"""Frozen ASMC experiment runner; no writes to older projects."""
import argparse
from collections import Counter,defaultdict
import hashlib
import itertools
import json
import math
import platform
import random
from statistics import median
from time import perf_counter
import zlib

import numpy as np

import asm as a
from inputs import pick,TRAIN
from measure import ws,references,local_dictionary

ROOT=a.ROOT
OUT=ROOT/"results"


def save(name,value):
    OUT.mkdir(exist_ok=True)
    p=OUT/(name+".json");tmp=p.with_suffix(".tmp")
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(p)


def run(f,*args,**kwargs):
    t=perf_counter();x=f(*args,**kwargs);return x,perf_counter()-t


def sha(d):return hashlib.sha256(d).hexdigest()


def trial(raw,edges,mode="bytes",table=b"",more=False):
    t0=perf_counter()
    crc=zlib.crc32(raw)
    out={}
    def grade(name,h,group,addr="abs",custom=False):
        ops=h if custom else a.sequences(raw,h)
        b,s=a.arch(raw,ops,mode,group,addr,table,crc)
        profile={}
        v,t=run(a.decode,b,None,profile)
        assert v==raw
        d=dict(bytes=len(b),cold_s=t,cold_mbps=len(raw)/1e6/max(t,1e-10),rebuild=profile,exact=True,**s)
        if more:
            cache={};v=a.decode(b,cache)
            tm=[]
            for _ in range(3):
                u,tr=run(a.decode,b,cache);assert u==v;tm.append(tr)
            d.update(warm_s=median(tm),warm_mbps=len(raw)/1e6/max(median(tm),1e-10),
                     warm_repetitions_s=tm,cache_entries=len(cache))
        out[name]=d
        return len(b)
    baseline=grade("direct",[],False)
    if more:
        grade("internal-blocks",a.repeat_route(raw),False,custom=True)
    _,ind=a.dp(edges)
    _,gd=a.dp(edges,guard=True,data=raw)
    groups=a.group_candidates(edges)
    proposed=[]
    combined=[]
    for _,seed,rs in groups[:16]:
        shadow=proposed+rs
        _,zz=a.dp(shadow,True)
        if zz!=combined:
            proposed=shadow;combined=zz
        if len({e.source for e in combined})>=4:break
    cand={"A":(ind,False),"A-guard":(gd,False),"B":(groups[0][2] if groups else [],True),
          "C":(combined,True)}
    if more:
        for policy,(s,g) in list(cand.items()):
            if policy in ("C","B") and s:
                cand[policy+"-delta"]=(s,g)
                cand[policy+"-affine"]=(s,g)
    for n,(h,g) in cand.items():
        styles="affine" if n.endswith("-affine") else "delta" if n.endswith("-delta") else "abs"
        grade(n,h,g if h else False,styles)
    best=min(cand,key=lambda name:out[name]["bytes"])
    # Isolate any positive variant before it can be credited to seed search.
    for nam,(h,g) in cand.items():
        if out[nam]["bytes"]<baseline:
            xx=grade(nam+"-same-splits",a.sequences(raw,h,True),False,custom=True)
            out[nam]["net_vs_same_splits"]=xx-out[nam]["bytes"]
    k=out[best]
    return dict(methods=out,best=best,net=baseline-k["bytes"],
                isolated=k.get("net_vs_same_splits",0),selected_coverage=k["covered"]/max(1,len(raw)),
                total_candidate_seeds=len({x.source for x in edges}),
                groups_profitable_proxy=len(groups),
                groups_exact_disjoint_at_least_two=sum(len(rs)>=2 for _,_,rs in groups),
                candidate_recipes_s=perf_counter()-t0)


def plant(kind):
    rng=random.Random(8172233)
    entries=[];out=bytearray()
    def add(s,addr,n,noise=0):
        out.extend(rng.randbytes(39+rng.randrange(72)))
        t=len(out);x=bytearray(a.generate(s,addr,n))
        for j in rng.sample(range(n),noise):x[j]^=rng.randrange(1,256)
        out.extend(x)
        entries.append(dict(offset=t,length=n,address=addr,noise=noise,**s.describe()))
    if kind=="single-known":
        add(a.Source(0,751),11,80)
    elif kind in ("shared","multi","noisy"):
        for i in range(10):
            s=a.Source(0,751 if kind!="multi" or i%2==0 else 137)
            add(s,64+i*137,109,2 if kind=="noisy" else 0)
    elif kind=="outside":
        for i in range(6):add(a.Source(6,751),64+i*137,99)
    elif kind=="distribution":
        out+=bytes(rng.choice(b"aaaabbc") for _ in range(8192))
    elif kind=="random":
        out+=rng.randbytes(8192)
    return bytes(out)+rng.randbytes(59),entries


def old_test():
    p=a.MS/"results"
    r=json.loads((p/"test.json").read_text(encoding="utf-8"))["rows"]
    return {v["input"]["name"]:dict(sha256=v["input"]["sha256"],input_bytes=v["input"]["input_bytes"],
             net=v["summary"]["net_vs_direct"],fallback=v["summary"]["fallback_bytes"],
             raw_cover=v["stats"]["raw_coverage"],bank=v["total"])
            for v in r if v["kind"]=="math"}


def load():
    rows=pick("test")
    for path,url in ((ROOT.parents[1]/"datasets/corpus/rfc1951.txt","https://www.rfc-editor.org/rfc/rfc1951.txt"),
                    (ROOT.parents[1]/"datasets/corpus/peps-index.html","https://peps.python.org/"),
                    (ROOT.parents[1]/"datasets/corpus/flower.png","https://github.com/python-pillow/Pillow/blob/main/Tests/images/flower_thumbnail.png")):
        d=path.read_bytes()
        rows.append((dict(name=path.name,source=url,split="new-test",input_bytes=len(d),sha256=sha(d)),d))
    return rows


def test():
    files=load()
    train=b"".join(p.read_bytes() for p in TRAIN)
    lut=a.lookup(a.train_counts(train),256)
    mk=a.lookup(a.train_counts(train,True),16)
    seed=a.seeds(12)
    specs=[("adaptive-splitmix",[(0,0,seed)],96,b""),
           ("fixed-seeds",[(0,0,np.array([0x789ac331+i*7919 for i in range(32)],np.uint32))],12288,b""),
           ("independent-uniform",[(1,0,seed)],96,b""),
           ("trained-hist",[(10,0,seed)],96,lut),
           ("trained-markov",[(11,0,seed)],96,mk),
           ("variable-families",[(f,p,a.seeds(12,1024,salt)) for f,p,salt in
                      ((2,0,1),(3,0,8),(4,1,14),(5,0,20))],96,b"")]
    old=old_test()
    oldref=json.loads((a.MS/"results/reference-test.json").read_text(encoding="utf-8"))["rows"]
    outputs=[]
    dct=local_dictionary()
    bases={}
    for meta,d in files:
        name=meta["name"]
        if name in old:
            assert old[name]["sha256"]==meta["sha256"]
            bases[name]=oldref[name]
        else:bases[name]=references(d,dct)
    for name,spec,length,table in specs+[("file-fitted-hist",None,96,None)]:
        if spec is not None:
            oldmem=ws();bank=a.Bank(spec,length,table=table); buildmem=ws()
        for meta,d in files:
            lut=table
            if spec is None:
                lut=a.lookup(a.train_counts(d),256)
                oldmem=ws();bank=a.Bank([(10,0,seed)],96,table=lut);buildmem=ws()
            h,stats=bank.search(d,cap=8000 if len(d)>4<<20 else 25000)
            q=trial(d,h,table=lut,more=name=="adaptive-splitmix" and len(d)<6<<20)
            outputs.append(dict(input=meta,bank=name,generation_s=bank.gen_s,index_s=bank.index_s,
                                building_memory=buildmem,memory_before=oldmem,search=stats,**q))
            if spec is None:bank.close()
        if spec is not None:bank.close()
        save("heldout",dict(rows=outputs,msmc=old,references=bases,
             environment=dict(platform=platform.platform(),python=platform.python_version())))
        print(name,[(x["input"]["name"],x["net"],x["isolated"]) for x in outputs if x["bank"]==name and x["net"]>0],flush=True)


def dev():
    inputs=pick("dev")
    files=[(p["name"],d) for p,d in inputs if p["name"] in ("alice29.txt","irs1040.pdf","python-logo.png")]
    out=[]
    for width in (8,12,16,20,24,32):
        for f in (0,1):
            se=a.seeds(width)
            mem0=ws()
            with a.Bank([(f,0,se)]) as b:
                mem1=ws()
                for name,data in files:
                    h,stats=b.search(data)
                    v=trial(data,h)
                    out.append(dict(name=name,bits=width,exhaustive=len(se)==1<<width,family=a.FAMILIES[f],
                                    file_bytes=len(data),num_seeds=len(se),generation_s=b.gen_s,
                                    index_s=b.index_s,memory_before=mem0,build_memory=mem1,
                                    search=stats,**v))
        save("dev",out)
        print("width",width,len(se),flush=True)


def control():
    res=[]
    for name in ("single-known","shared","multi","outside","random","distribution","noisy"):
        d,planted=plant(name)
        step=96 if name=="single-known" else 1536
        se=a.seeds(12,1024) if step==1536 else a.seeds(12)
        # Both planted seeds are legal and predeclared; make this long-access
        # fixture use a known bounded low-seed cohort by construction.
        if step==1536:se=np.arange(1024,dtype=np.uint32)
        with a.Bank([(0,0,se)],step) as ix:
            h,s=ix.search(d)
            q=trial(d,h,more=True)
            res.append(dict(name=name,file_bytes=len(d),planted=planted,sha256=sha(d),search=s,
                            generation_s=ix.gen_s,index_s=ix.index_s,**q))
    save("control",res)


def radix():
    rows=[]
    d=[(p["name"],x) for p,x in pick("dev") if p["name"] in ("alice29.txt","python-logo.png")]
    d.append(("artificial-shared",plant("single-known")[0]))
    for mo in a.MODES:
        with a.Bank([(0,0,a.seeds(12))],96,mo) as b:
            for n,x in d:
                h,s=b.search(x)
                rows.append(dict(name=n,mode=mo,input_bytes=len(x),search=s,**trial(x,h,mo,more=True)))
    save("radix",rows)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("suite",choices=["dev","test","control","radix"])
    globals()[p.parse_args().suite]()
