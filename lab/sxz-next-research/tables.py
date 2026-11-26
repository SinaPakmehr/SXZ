"""Generate audit tables from measured JSON; no hand-entered timing or sizes."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent/"results"


def load(name):
    return json.loads((OUT/(name+".json")).read_text(encoding="utf-8"))


def pct(n,d):
    return f"{n/d:.3%}"


def main():
    rows = load("real")["rows"]
    legacy = {r["name"]:r["methods"]["sxz4-on"] for r in load("reference")["rows"]}
    lines = [
        "# SXZ-NEXT whole files / full metadata counted",
        "",
        "External = best of raw zstd-3/19, Brotli-9 and xz-6 **per file**. JPEG XL is a separate format control.",
        "Conventional = minimum of framed raw, exposed, typed and optional fixed spatial modes, same zstd level.",
        "Math = same typed representation, with locally selected proposals (and the forced candidate, for audit).",
        "The selected column is an empirical minimum over tested XNB1 recipes; it is not a separately timed run.",
    ]
    for level in (3,19):
        s = f"+zstd-{level}"
        lines.extend(["",f"## zstd-{level}: bytes", "",
            "| Input | Original | SXZ4 | External | Raw-framed | Exposed | Typed | Conventional | Math-local | Math-forced | Selected |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"])
        sums = [0]*10
        for r in rows:
            m = r["methods"]
            best_regular = min(m[k+s]["bytes"] for k in
                ("raw-framed","exposed","typed","spatial-fixed-local","spatial-fixed-forced") if k+s in m)
            best_ext = min(m[k]["bytes"] for k in ("zstd-3","zstd-19","brotli-9","xz-6"))
            local,forced = m["math-local"+s]["bytes"],m["math-forced"+s]["bytes"]
            values = [r["bytes"],legacy[r["name"]]["bytes"],best_ext,*[m[k+s]["bytes"]
                      for k in ("raw-framed","exposed","typed")],best_regular,local,forced,min(best_regular,local,forced)]
            lines.append("| "+r["name"]+" | "+" | ".join(f"{x:,}" for x in values)+" |")
            sums = [a+b for a,b in zip(sums,values)]
        lines.append("| **Total** | "+" | ".join(f"{x:,}" for x in sums)+" |")
        lines.append("| **Ratio** | "+" | ".join(pct(x,sums[0]) for x in sums)+" |")
    lines.extend(["","## Absolute decode throughput (decimal MB/s), median of five in memory","",
                  "| Input | zstd-3 | zstd-19 | Brotli-9 | xz-6 | SXZ4 | Best conventional XNB1-zstd19 | Math-local XNB1-zstd19 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for r in rows:
        m = r["methods"]
        best_regular = min((m[k+"+zstd-19"] for k in
                            ("raw-framed","exposed","typed","spatial-fixed-local","spatial-fixed-forced") if k+"+zstd-19" in m),
                            key=lambda v: v["bytes"])
        v = [m[k]["decode_MBps"] for k in ("zstd-3","zstd-19","brotli-9","xz-6")] + [
            legacy[r["name"]]["decode_MBps"],best_regular["decode_MBps"],m["math-local+zstd-19"]["decode_MBps"]]
        lines.append("| "+r["name"]+" | "+" | ".join(f"{x:.2f}" for x in v)+" |")
    (OUT/"whole-files.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def audit_jpeg():
    from accelerate import scan_native
    from corpus import FILES
    from representation import jpeg
    hits = []
    for _,fmt,p,_ in FILES:
        if fmt != "JPEG":
            continue
        sections,_ = jpeg(p.read_bytes())
        start = 0
        for sec in sections:
            ch = sec.channels[0].data
            candidates,_ = scan_native(ch)
            for off,n,a,b,c,x,y in candidates:
                prefix = ch[off:off+n]
                hits.append(dict(file=p.name, section_kind=sec.kind, source_section_start=start,
                                 offset_in_exposed_channel=off, length=n, coeff=[a,b,c], seed=[x,y],
                                 prefix_hex=prefix[:48].hex(), repeated_final_byte_run=
                                 n-len(prefix.rstrip(prefix[-1:]))))
            start += sec.length
    (OUT/"jpeg-algebra-audit.json").write_text(json.dumps(hits,indent=2)+"\n",encoding="utf-8")


if __name__ == "__main__":
    main()
    audit_jpeg()
