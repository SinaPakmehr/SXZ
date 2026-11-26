"""Build paired summaries directly from measured JSON."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import median

from study import BASE, LEVELS, RESULTS, dump, ROOT


def read(n):
    return json.loads((RESULTS/(n+".json")).read_text(encoding="utf-8"))


def best(m,names,level):
    return min((f"srx-{x}-{level}" for x in names),key=lambda k:m[k]["bytes"])


def all_tables(rows,oracle,special):
    out = [
        "# Structural-relations — complete file comparisons",
        "",
        "Savings = strongest matched conventional archive minus the smaller of the two measured parametric policies.",
        "No positive savings are credited to any exposed representation, deduplication, copy/insert, grammar or specialist.",
        "Only the lab header, Zstd-compressed layout, descriptor stream and payload stream sum to archive bytes.",
        "",
    ]
    aggregate={}
    for v in LEVELS:
        # Largest first-order effect or improvement can be seen per source,
        # even when aggregate masking by the largest ONNX file would be misleading.
        out.extend([
            f"## Zstd-{v} / bytes", "",
            "| File | Family | Input | Raw Zstd | Plain exposed | Exact dedup | Diff | Best grammar* | Best conventional | Parametric | Savings |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
        ])
        buckets=defaultdict(list)
        for r in rows:
            m=r["methods"]
            b,p=best(m,BASE,v),best(m,("math","math-margin"),v)
            g=best(m,tuple(k for k in BASE if "grammar" in k),v)
            conv,para=m[b]["bytes"],m[p]["bytes"]
            values=[r["file_bytes"],m[f"zstd-{v}"]["bytes"],
                    *[m[f"srx-{k}-{v}"]["bytes"] for k in ("plain","dedup","diff")],
                    m[g]["bytes"],conv,para,conv-para]
            out.append("| "+r["name"]+" | "+r["family"]+" | "+" | ".join(f"{x:,}" for x in values)+" |")
            buckets[r["family"]].append(dict(file=r["name"],baseline=conv,math=para,
               oracle_saved=max(0,conv-para),gain=conv-para,
               params=m[p]["cost"]["parametric_count"],baseline_method=b,math_method=p,
               trials=r["layout"]["models_evaluated"],
               eligible=sum(bool(x["pool"]) and x["conventional"]!=1 for x in oracle[r["name"]]),
               manual_audit_file=r["name"]))
        out+=["","* Includes grammar alone and grammar after conventional differential.","",
            "| Family | Files | Net over matched baseline (bytes) | Max fallback saving | ≥1% and ≥256 B wins |",
            "|---|---:|---:|---:|---:|"]
        for fam,rs in buckets.items():
            out.append(f"| {fam} | {len(rs)} | {sum(x['gain'] for x in rs):,} | "
                       f"{sum(x['oracle_saved'] for x in rs):,} | "
                       f"{sum(x['gain']>=256 and x['gain']*100>=x['baseline'] for x in rs)} |")
        aggregate[str(v)]=dict(buckets)
    out+=["","## Zstd-9 decoding, checksum and original framing included","",
          "| File | Relational distinct records with a proposed parent | Conventional ref. count | Params chosen | Raw MB/s | Conventional MB/s | Parametric MB/s | Reconstruction ms | Special bytes |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        m=r["methods"]
        b,p=[m[r["layout"][x]] for x in ("best_conventional_at_9","best_param_policy_at_9")]
        s=special.get(r["name"])
        if r["family"]=="binary":
            s=m.get("xz-bcj-6")
        num=f"{s['bytes']:,}" if s else "—"
        distinct=sum(bool(x["pool"]) and x["conventional"]!=1 for x in oracle[r["name"]])
        out.append(f"| {r['name']} | {distinct} | {b['cost']['references']} | "
             f"{p['cost']['parametric_count']} | {m['zstd-9']['decode_mb_s']:.1f} | {b['decode_mb_s']:.1f} | "
             f"{p['decode_mb_s']:.1f} | {p['decode_stage_medians_s']['restore_container_crc']*1000:.2f} | {num} |")
    out+=["","## Memory (Windows fresh child processes, absolute peak working set)","",
          "| File | Method | Peak before decode MiB | Peak after decode MiB |",
          "|---|---|---:|---:|"]
    for r in rows:
        for x in r["memory"]:
            out.append(f"| {r['name']} | {x['method']} | {x['before']['peak_ws_bytes']/2**20:.2f} | "
                       f"{x['after']['peak_ws_bytes']/2**20:.2f} |")
    (RESULTS/"tables.md").write_text("\n".join(out)+"\n",encoding="utf-8")
    dump("summary",aggregate)


if __name__=="__main__":
    args=read("real")
    rows=args["rows"]
    a=read("oracle")
    s={row["file"]:row for row in read("specialized")}
    assert len(rows)==17 and len(a)==len(rows)
    for x in rows:
        for k,y in x["methods"].items():
            assert y["exact"]
            if "cost" in y:
                u=y["cost"]
                assert y["bytes"]==sum(u[n] for n in ("header_bytes","layout_stored","descriptor_stored","payload_stored"))
    for x in s.values():
        assert x["exact"] and x["sha256"]==next(r["sha256"] for r in rows if r["name"]==x["file"])
    ref=json.loads((ROOT/"prior-hashes.json").read_text(encoding="utf-8"))
    now={name:hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest() for name in ref}
    assert ref==now
    dump("preservation",now)
    all_tables(rows,a,s)
