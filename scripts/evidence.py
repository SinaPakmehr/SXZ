"""Produce SVG bar charts and a CSV directly from historical public JSON."""
from pathlib import Path
from collections import defaultdict
from html import escape
import csv
import json
from statistics import mean

R=Path(__file__).resolve().parents[1]
F=R/"figures";F.mkdir(exist_ok=True)

def load(phase,name):
    return json.loads((R/"lab"/phase/"results"/(name+".json")).read_text(encoding="utf-8"))

def chart(name,title,unit,rows):
    h=70+len(rows)*30
    vmax=max((abs(x[1]) for x in rows),default=0) or 1
    lines=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 840 {h}" role="img">',
           f'<title>{escape(title)}</title><rect width="840" height="{h}" fill="white"/>',
           f'<text x="20" y="25" font-family="sans-serif" font-size="17">{escape(title)} ({unit})</text>']
    for i,(label,val) in enumerate(rows):
        y=55+30*i
        lines.append(f'<text x="20" y="{y}" font-family="sans-serif" font-size="13">{escape(label)}</text>')
        lines.append(f'<rect x="275" y="{y-14}" width="{440*abs(val)/vmax:.4f}" height="17" fill="{"#0072B2" if val>=0 else "#D55E00"}"/>')
        lines.append(f'<text x="730" y="{y}" font-family="sans-serif" font-size="13">{val:,.2f}</text>')
    (F/(name+".svg")).write_text("\n".join(lines+["</svg>"])+"\n",encoding="utf-8")

ms=load("sxz-mathematical-mosaic","summary")
chart("msmc-coverage","MSMC: largest development bank, mean raw coverage","percent",
      [(k,ms["dev"]["10000000"][k]["raw_pct"]) for k in ("math","uniform","matched","shuffled")])
chart("msmc-match-length","MSMC: longest observed mathematical match","bytes",
      [(f"{int(n):,} bank symbols",v["math"]["max_symbols"]) for n,v in ms["dev"].items()])
chart("msmc-raw-vs-economic","MSMC: raw coverage versus economically useful coverage","percent",
      [(f"{int(n):,} bank symbols: raw",ms["dev"][n]["math"]["raw_pct"]) for n in ms["dev"]]+
      [(f"{int(n):,} bank symbols: economic",ms["dev"][n]["math"]["economic_pct"]) for n in ms["dev"]])
chart("msmc-bank-coverage","MSMC: mean raw coverage by reference-bank size","percent",
      [(f"{int(n):,} symbols: math",ms["dev"][n]["math"]["raw_pct"]) for n in ms["dev"]]+
      [(f"{int(n):,} symbols: uniform",ms["dev"][n]["uniform"]["raw_pct"]) for n in ms["dev"]])
asm=load("sxz-adaptive-stochastic-mosaic","dev")
q=defaultdict(list)
for x in asm:
    if x["family"]=="splitmix64":
        q[x["bits"]].append(x)
chart("asmc-seed-coverage","ASMC: SplitMix development coverage","percent",
      [(f"{b} bits / {v[0]['num_seeds']:,} seeds",mean(100*z["search"]["covered"]/z["file_bytes"] for z in v)) for b,v in sorted(q.items())])
chart("asmc-seed-net","ASMC: development gain against direct frame","bytes",
      [(f"{b} bits / {v[0]['num_seeds']:,} seeds",sum(z["net"] for z in v)) for b,v in sorted(q.items())])
controls={x["name"]:x["methods"] for x in load("sxz-adaptive-stochastic-mosaic","control")}
chart("asmc-sharing","ASMC shared-seed positive control (synthetic)","archive bytes",
      [(k,controls["shared"][k]["bytes"]) for k in ("direct","A","B","B-affine")])
with (F/"asmc-holdout.csv").open("w",newline="",encoding="utf-8") as f:
    w=csv.writer(f);w.writerow(["bank","files","coverage_fraction","net_with_fallback_bytes","gate_passes"])
    for k,x in load("sxz-adaptive-stochastic-mosaic","overview").items():
        w.writerow([k,x["files"],x["coverage"],x["net_fallback"],x["gate"]])

# SXZ4 and public-real panel totals, using historical method rows.
def panel_totals(phase, name, methods):
    rows=load(phase,name)
    groups=("synthetic","real","precompressed") if name=="sxz4_bench_full" else ("public-real",)
    out=[]
    for category in groups:
        data=[r for r in rows if name=="sxz5_bench" or r["category"]==category]
        denom=sum(r["bytes_in"] for r in data if r["method"]==methods[0])
        for method in methods:
            total=sum(r["bytes"] for r in data if r["method"]==method)
            out.append((f"{category}: {method}",100*total/denom if denom else 0))
    return out
chart("sxz4-panel","SXZ4 historical panel: archive / input","percent",
      panel_totals("zip-protocol","sxz4_bench_full",("deflate-6","zstd-19","xz-6","brotli-11","sxz4-tx","sxz4-on")))
chart("sxz5-panel","Public-real panel: archive / input (historical)","percent",
      panel_totals("zip-protocol","sxz5_bench",("deflate-6","zstd-19","xz-6","brotli-11","sxz4-tx","sxz4-on")))
dec=load("zip-protocol","sxz4_validation")
attrib=[r for r in dec if r["suite"]=="decompose"]
chart("sxz4-attribution","SXZ4 decomposition: backend, transform, exact model","archive bytes",
      [(f"{r['name']}: backend",r["backend-only"]["bytes"]) for r in attrib]+
      [(f"{r['name']}: +transform",r["backend+tx"]["bytes"]) for r in attrib]+
      [(f"{r['name']}: +model",r["backend+exact"]["bytes"]) for r in attrib])

