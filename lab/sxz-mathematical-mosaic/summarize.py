"""Regenerate numerical tables and SVG plots; no manually authored data points."""
from collections import defaultdict
from pathlib import Path
from statistics import mean
import hashlib
import json
import math
import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from inputs import ROOT

R=ROOT/"results"
MODE=("bytes","b2","b4","b8","b16","dec3","dec20","decvar")
C=("math","uniform","matched","shuffled")


def get(name): return json.loads((R/(name+".json")).read_text(encoding="utf-8"))
def put(name,data): (R/name).write_text(data,encoding="utf-8")
def fmt(x): return f"{x:,}"


def combined(rows):
    size=sum(r["input"]["input_bytes"] for r in rows)
    st=[r["stats"] for r in rows]
    q=[r["summary"] for r in rows]
    return dict(archives=len(rows),input_bytes=size,count=sum(s["count"] for s in st),
                max_symbols=max(s["best"] for s in st),
                mean_symbols=sum(s["sum"] for s in st)/max(1,sum(s["count"] for s in st)),
                anchor_rate=sum(s["count"] for s in st)/sum(s["target_symbols"] for s in st),
                raw_pct=100*mean(s["raw_coverage"] for s in st),
                economic_pct=100*mean(x["economic_coverage"] for x in q),
                wins=sum(x["net_vs_direct"]>0 for x in q),
                pure_wins=sum(x["net_A_vs_direct"]>0 for x in q),
                criteria_wins=sum(x["net_vs_direct"]>=128 and 100*x["net_vs_direct"]>=r["rows"]["direct-3"]["bytes"]
                                  for x,r in zip(q,rows)),
                fallback_saving=sum(max(0,x["net_vs_direct"]) for x in q),
                forced_net=sum(x["net_vs_direct"] for x in q),
                capped=sum(s["dropped"] for s in st),
                raw_economic_paths=sum(x["selected_raw"] for x in q),
                strong_local_candidates=sum(x["local_backend_candidates"] for x in q))


def aggregate(dev,radix,test):
    a,b,g={}, {}, {}
    for n in sorted({r["total"] for r in dev}):
        a[n]={k:combined([x for x in dev if x["total"]==n and x["kind"]==k]) for k in C}
    for m in MODE:
        b[m]={k:combined([x for x in radix if x["mode"]==m and x["kind"]==k]) for k in C}
    for k in C:
        g[k]=combined([x for x in test if x["kind"]==k])
    return dict(dev=a,radix=b,test=g)


def plots(data,held):
    f=R/"figures"; f.mkdir(exist_ok=True)
    a=data["dev"]; ns=sorted(a)
    fig,ax=plt.subplots(figsize=(7.6,4.2))
    for k in C:
        ax.plot(ns,[a[x][k]["max_symbols"] for x in ns],"o-",label=k)
    ax.set(xscale="log",xlabel="Total searched reference symbols",ylabel="Longest exact match (bytes)",
           title="Bank growth / development panel, byte view")
    ax.grid(linestyle=":",alpha=.5);ax.legend()
    fig.tight_layout();fig.savefig(f/"bank-vs-match.svg");plt.close(fig)
    fig,ax=plt.subplots(figsize=(7.6,4.2))
    for k in C:
        ax.plot(ns,[a[x][k]["raw_pct"] for x in ns],"o-",label=k+" raw")
    ax.plot(ns,[a[x]["math"]["economic_pct"] for x in ns],"s--",color="black",label="math net economic")
    ax.set(xscale="log",xlabel="Total searched reference symbols",ylabel="Mean per-file coverage (%)",
           title="Raw hit union is not compressed coverage")
    ax.grid(linestyle=":",alpha=.5);ax.legend()
    fig.tight_layout();fig.savefig(f/"coverage.svg");plt.close(fig)
    fig,ax=plt.subplots(figsize=(12,5))
    xs=list(range(len(held)))
    ax.scatter(xs,[100*r["zstd"]/r["input"] for r in held],marker="o",label="raw Zstd-3")
    ax.scatter(xs,[100*r["selected"]/r["input"] for r in held],marker="+",label="mosaic hybrid with fallback")
    ax.scatter(xs,[100*r["external"]/r["input"] for r in held],marker="_",label="best measured external (incl dictionary)")
    ax.set(ylabel="Compressed archive / original bytes (%)",title="Held-out complete files (1M-symbol math bank)")
    ax.set_xticks(xs,[r["name"] for r in held],rotation=55,ha="right")
    ax.legend();ax.grid(linestyle=":",alpha=.5);fig.tight_layout()
    fig.savefig(f/"ratios.svg");plt.close(fig)


def main():
    d,rv,t=[get(k) for k in ("dev","radix","test")]
    stats=aggregate(d["rows"],rv["rows"],t["rows"])
    base=get("reference-test")["rows"]
    refs= {x["meta"]["name"]:x["bytes"] for x in get("previous")}
    lines=["# Mathematical-mosaic measured results","",
           "`A` = independent slices. `B` = local fragment reuse. Net is relative to the same framed hybrid, not raw size.",
           "A candidate's raw coverage is union of exact hits; the economic column counts only mathematical bytes in a smaller final hybrid.",
           "Dictionary-reference price includes a paid-once dictionary amortized across 19 test files in `external`.",
           "",
           "## Held-out byte view, one million reference symbols","",
           "| Whole file | Input | Hit starts | Max | Raw union % | Selected hybrid | Direct hybrid | Net | Zstd-3 | Best external | SXZ4 |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    held=[]
    for x in t["rows"]:
        if x["kind"]!="math":continue
        name=x["input"]["name"]; n=x["input"]["input_bytes"]
        m=x["rows"];b=base[name];k=x["summary"]["best_math"];s=x["stats"]
        fb=x["summary"]["fallback_bytes"]
        ext=min(x.get("shared_at_19_bytes",x["bytes"]) for x in b.values())
        lines.append(f"| {name} | {n:,} | {s['count']:,} | {s['best']} | {s['raw_coverage']*100:.3f} | "
                     f"{m[k]['bytes']:,} | {m['direct-3']['bytes']:,} | {x['summary']['net_vs_direct']:,} | "
                     f"{b['zstd-3']['bytes']:,} | {ext:,.0f} | {fmt(refs[name]) if name in refs else '—'} |")
        held.append(dict(name=name,input=n,selected=fb,forced=m[k]["bytes"],zstd=b["zstd-3"]["bytes"],
                         raw_hybrid=m["direct-3"]["bytes"],external=ext))
    lines+=["","## Growth / math versus controls","",
            "| Symbols | Library | File–seed rows | Mean length | Max | Mean raw % | Mean economic % | Fallback total gain |",
            "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for n,a in stats["dev"].items():
        for k,u in a.items():
            lines.append(f"| {n:,} | {k} | {u['archives']} | {u['mean_symbols']:.4f} | {u['max_symbols']} | "
                         f"{u['raw_pct']:.3f} | {u['economic_pct']:.6f} | {u['fallback_saving']:,} |")
    lines+=["","## Whole-file radix panel at 100k reference symbols","",
            "| Representation | Library | Mean raw union % (symbols) | Max symbols | Fallback gain | Criterion passes |",
            "|---|---|---:|---:|---:|---:|"]
    for mo,kinds in stats["radix"].items():
        for k,u in kinds.items():
            lines.append(f"| {mo} | {k} | {u['raw_pct']:.4f} | {u['max_symbols']} | {u['fallback_saving']} | {u['criteria_wins']} |")
    lines+=["","## Held-out bank comparison","",
            "| Library | File–seed rows | Mean raw % | Max | Net positive files/seeds | Economic % | Net forced | Fallback gain |",
            "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k,u in stats["test"].items():
        lines.append(f"| {k} | {u['archives']} | {u['raw_pct']:.4f} | {u['max_symbols']} | "
                     f"{u['wins']} | {u['economic_pct']:.6f} | {u['forced_net']:,} | {u['fallback_saving']:,} |")
    lines+=["","## Runtime per held-out full file",
            "For selected exact branch, measured decode is emitted when input is ≤6 MiB. "
            "`candidate campaign` includes building multiple experimental variants, not just one encoder.",
            "",
            "| File | Search (s) | Candidate campaign (s) | Best math warm MB/s | Cold MB/s | Zstd-3 MB/s |",
            "|---|---:|---:|---:|---:|---:|"]
    for x in t["rows"]:
        if x["kind"]!="math": continue
        q=x["rows"][x["summary"]["best_math"]]
        n=x["input"]["name"]; b=base[n]["zstd-3"]
        w=f"{q['decode_MBs']:.2f}" if "decode_MBs" in q else "—"
        cold=f"{q['cold_decode_MBs']:.2f}" if "cold_decode_MBs" in q else "—"
        lines.append(f"| {n} | {x['index_query_s']:.4f} | {x['plan_and_measure_s']:.3f} | "
                     f"{w} | {cold} | {b['decode_MBs']:.2f} |")
    put("tables.md","\n".join(lines)+"\n")
    put("summary.json",json.dumps(dict(**stats,heldout=held),indent=2)+"\n")
    plots(stats,held)
    h=json.loads((ROOT/"prior-hashes.json").read_text(encoding="utf-8"))
    v={p:hashlib.sha256((ROOT.parent/p).read_bytes()).hexdigest() for p in h}
    assert v==h
    put("preservation.json",json.dumps(v,indent=2)+"\n")
    for case in (d,rv,t,get("control")):
        assert all(a["exact"] and a["bytes"]==a["header_bytes"]+a["metadata_bytes"]+a["literals_bytes"]
                   for x in case["rows"] for a in x["rows"].values())


if __name__=="__main__": main()
