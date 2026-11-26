"""Run paired structural-relation measurements and record exact byte costs."""
import argparse
import hashlib
import json
import lzma
import os
import platform
import random
import statistics
import subprocess
import sys
import time
import zlib
from tempfile import TemporaryDirectory
from pathlib import Path

import brotli
import numpy as np
import zstandard

import inputs
from inputs import ROOT
import models
import wire
from memory import process_memory

RESULTS=ROOT/"results"
TEMP=Path(__file__).resolve().parents[2]/"datasets/tools"
LEVELS=(3,9)
BASE=("plain","dedup","diff","grammar-local","grammar-forced","diff-grammar-local","diff-grammar-forced")


def dump(name,rows):
    RESULTS.mkdir(exist_ok=True)
    f=RESULTS/(name+".json")
    tmp=f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    tmp.replace(f)


def measure(func,*args,**kwargs):
    t=time.perf_counter()
    val=func(*args,**kwargs)
    return val,time.perf_counter()-t


def timings(blob,original,unpack,enc,stage=False):
    assert (unpack(blob)[0] if stage else unpack(blob))==original
    ts, stages=[],[]
    for _ in range(5):
        val,t=measure(unpack,blob)
        if stage:
            val,st=val
            stages.append(st)
        assert val==original
        ts.append(t)
    d=statistics.median(ts)
    r=dict(bytes=len(blob),encode_s=enc,decode_s=d,decode_mb_s=len(original)/1e6/d,
           repetitions_s=ts,exact=True)
    if stages:
        r["decode_stage_medians_s"]={name:statistics.median(row[i] for row in stages)
             for i,name in enumerate(("zstd_parse","expand_records","restore_container_crc"))}
    return r


def worker(backend,path):
    c=Path(path).read_bytes()
    b=process_memory()
    d=wire.unpack(c) if backend=="srx" else zstandard.ZstdDecompressor().decompress(c)
    a=process_memory()
    print(json.dumps(dict(before=b,after=a,digest=hashlib.sha256(d).hexdigest())))


def memory(blobs,digest,names):
    out=[]
    with TemporaryDirectory() as td:
        p=Path(td)/"payload"
        for name in dict.fromkeys(names):
            p.write_bytes(blobs[name])
            kind="srx" if name.startswith("srx-") else "zstd"
            a=subprocess.run([sys.executable,"-B",str(ROOT/"study.py"),"worker",kind,str(p)],
                             check=True,capture_output=True,text=True,timeout=70)
            row=json.loads(a.stdout)
            assert row["digest"]==digest
            out.append(dict(method=name,**row))
    return out


def synthetic():
    # 32 separated tiles, derived from the same nontrivial random 16x16
    # prototype by a horizontal reflection and sparse exact byte exceptions.
    rng=random.Random(510192)
    rs=[]
    a=rng.randbytes(256)
    for i in range(33):
        if i%3==0:
            s=np.frombuffer(a,np.uint8).reshape(16,16).copy()
            if i:
                s=s[:,::-1].copy()
                s[i%16,(i*3)%16]^=16+i
            rs.append(inputs.Record(s.tobytes(),("image",0,16,16),1,(16,16),(0,i)))
        else:
            # Distractors have known valid boundaries but are different channels.
            rs.append(inputs.Record(rng.randbytes(256),("image",i+1,16,16),1,(16,16),(0,i)))
    b=b"".join(x.data for x in rs)
    return b,([inputs.Part(inputs.prev.RAW,len(b),b"",[inputs.Channel(rs)])],
              {"purpose":"non-adjacent horizontal mirror with one-byte exceptions"})


def ref_options(family):
    for v in (3,9,19):
        yield f"zstd-{v}",zstandard.ZstdCompressor(level=v,write_checksum=True).compress,zstandard.ZstdDecompressor().decompress
    yield "brotli-9",lambda d:brotli.compress(d,quality=9),brotli.decompress
    yield "xz-6",lambda d:lzma.compress(d,preset=6),lzma.decompress
    if family=="binary":
        yield "xz-bcj-6",lambda d:lzma.compress(d,filters=[{"id":lzma.FILTER_X86},{"id":lzma.FILTER_LZMA2,"preset":6}]),lzma.decompress


def case(family,data,digest,control=False,memory_on=True):
    methods={}
    blobs={}
    for label,compress,unpack in ref_options(family):
        blob,enc=measure(compress,data)
        methods[label]=timings(blob,data,unpack,enc)
        if label=="zstd-9":
            blobs[label]=blob
    if not control:
        (parts,detail),prep=measure(inputs.structure,data,family)
    else:
        _, (parts,detail)=synthetic()
        prep=0
    (layout,records),preplay=measure(wire.layout,parts)
    chosen,search_s=measure(models.choose,records)
    options,audit=chosen
    channels=dict()
    for name in ("plain","diff"):
        payload=b"".join(x.payload for x in options[name])
        (forced,local,stats),t=measure(wire.grammar_body,payload)
        for label,body in (("grammar-forced",forced),("grammar-local",local)):
            tag=("" if name=="plain" else "diff-")+label
            channels[tag]=(options[name],body,stats,t)
    for name,opt in options.items():
        channels[name]=(opt,None,None,0)
    cost=hashlib.sha256(layout).hexdigest()
    for level in LEVELS:
        layout_comp=zstandard.ZstdCompressor(level=level,write_checksum=True).compress(layout)
        crc=zlib.crc32(data)
        memo={}
        for label,(ops,body,gram,t) in channels.items():
            key=f"srx-{label}-{level}"
            (blob,info),et=measure(wire.encode,data,layout,ops,level,body,layout_comp,crc)
            hash_c=hashlib.sha256(blob).hexdigest()
            if hash_c not in memo:
                memo[hash_c]=timings(blob,data,lambda b:wire.unpack(b,True),et,True)
            r=dict(memo[hash_c])
            r["encode_s"]=et+preplay+prep+t
            r["layout_prep_s"]=prep+preplay
            r["grammar_s"]=t
            r["induction_shared_s"]=search_s
            r.update(dict(cost=info,grammar=gram,sha256=hash_c))
            methods[key]=r
            if level==9 and (label in BASE or label.startswith("math")):
                blobs[key]=blob
    base=min((f"srx-{b}-9" for b in BASE),key=lambda key:methods[key]["bytes"])
    params=min(("srx-math-9","srx-math-margin-9"),key=lambda key:methods[key]["bytes"])
    rss=memory(blobs,digest,["zstd-9",base,params]) if memory_on and not control else []
    grouped=[x for x in records if x.group]
    typ=dict(detail, common_layout_sha256=cost, record_count=len(records), structured_count=len(grouped),
             structured_bytes=sum(len(x.data) for x in grouped), exposed_bytes=sum(len(x.data) for x in records),
             correction_and_section_aux_raw=sum(len(x.aux) for x in parts),
             groups=len({x.group for x in grouped}),
             records_with_candidates=sum(bool(x["pool"]) for x in audit),candidate_parents=sum(len(x["pool"]) for x in audit),
             models_evaluated=sum(x["trial_count"] for x in audit),shared_induction_s=search_s,
             best_conventional_at_9=base,best_param_policy_at_9=params)
    return methods,typ,audit,rss


def main(args):
    rows=[]; audits={}
    for fam,split,p,src in inputs.ENTRY:
        if args.only and args.only not in (fam,p.name):
            continue
        if not p.is_file():
            raise FileNotFoundError(p)
        d=p.read_bytes()
        dig=hashlib.sha256(d).hexdigest()
        print("start",fam,p.name,len(d),flush=True)
        methods,detail,audit,rss=case(fam,d,dig,memory_on=not args.no_memory)
        audits[p.name]=audit
        rows.append(dict(family=fam,split=split,name=p.name,source=src,sha256=dig,file_bytes=len(d),
                         layout=detail,methods=methods,memory=rss))
        name="real"+("-"+args.only if args.only else "")
        dump(name,dict(environment=dict(os=platform.platform(),python=sys.version,
                  cpu=platform.processor(),numpy=np.__version__,zstd=zstandard.__version__,
                  brotli=brotli.__version__,repeats=5),rows=rows))
        dump("oracle"+("-"+args.only if args.only else ""),audits)
        b,m=(methods[detail[x]] for x in ("best_conventional_at_9","best_param_policy_at_9"))
        print(p.name,"baseline",b["bytes"],"math",m["bytes"],"param_records",m["cost"]["parametric_count"],flush=True)
    if not args.only:
        assert len(rows)==len(inputs.ENTRY)


def ctrl():
    d,_=synthetic()
    m,s,a,r=case("control",d,hashlib.sha256(d).hexdigest(),True)
    dump("control",dict(methods=m,layout=s,audit=a))
    print({k:x["bytes"] for k,x in m.items()},flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["real","control","worker"])
    parser.add_argument("extra",nargs="*")
    parser.add_argument("--only")
    parser.add_argument("--no-memory",action="store_true")
    args=parser.parse_args()
    if args.mode=="worker":
        worker(*args.extra)
    elif args.mode=="control":
        ctrl()
    else:
        main(args)
