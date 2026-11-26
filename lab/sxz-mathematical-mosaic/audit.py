"""Emit one JSONL row per retained address alternative for a given complete file.

For seed-only matches extrapolate costs only when a complete original unit fits.
Generation measurement is warm bank lookup and inverse representation. Cold
bank production is reported as the single shared prelude, not charged per hit.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter

import catalog as c
import index
import mosaic as m
import represent as rp


def audit(path,output,mode,total,kind,seed,cap,seed_only):
    data=path.read_bytes()
    parts,prof=c.generate(mode,total,kind,seed)
    x,off=rp.view(data,mode)
    with index.Index(parts,mode) as ix:
        hits,stats=ix.query(x,cap,ix.k if seed_only else None)
    cache=m.Banks({(kind,mode,total,seed,g):v for g,v in enumerate(parts)})
    with output.open("w",encoding="utf-8") as out:
        def emit(x): out.write(json.dumps(x,ensure_ascii=False)+"\n")
        emit(dict(type="prelude",mode=mode,symbols=total,kind=kind,seed=seed,
                  stats=stats,generation=prof,byte_length=len(data),reported=len(hits)))
        for p,g,f,n in hits:
            rr=rp.project(mode,off,p,n)
            record=dict(type="match",target_symbol=p,source_symbol=f,gid=g,generator=c.NODES[g].name,
                        fixed_params=c.NODES[g].params,length_symbols=n,mode=mode)
            if rr:
                a,b,t,q,ww=rr
                edge=m.Edge(a,b,g,f+t,q,ww)
                start=perf_counter()
                seq=cache.get(kind,mode,total,seed,g,f+t,q)
                raw=rp.revert(seq,mode,ww)
                elapsed=perf_counter()-start
                assert data[a:b]==raw
                record.update(edge.dict(),original_source_symbol=f,charged_raw_desc=edge.desc,
                              decode_warm_s=elapsed,raw_profitable=edge.desc<b-a)
            emit(record)


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("input",type=Path)
    a.add_argument("output",type=Path)
    a.add_argument("--mode",choices=rp.MODES,default="bytes")
    a.add_argument("--total",choices=c.LEVELS,type=int,default=1000000)
    a.add_argument("--kind",choices=c.KINDS,default="math")
    a.add_argument("--seed",choices=range(len(c.SEEDS)),type=int,default=0)
    a.add_argument("--cap",type=int,default=80000)
    a.add_argument("--include-anchors",action="store_true")
    x=a.parse_args()
    if not 0<=x.cap<=180000: a.error("cap must be 0..180000")
    audit(x.input,x.output,x.mode,x.total,x.kind,x.seed,x.cap,x.include_anchors)
