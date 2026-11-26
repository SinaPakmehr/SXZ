"""Whole-file comparisons. Invoke with `python -B bench.py real` or `reference`."""
import argparse
import hashlib
import json
import lzma
import platform
import statistics
import sys
import time
import zlib

sys.dont_write_bytecode = True

import brotli
import zstandard

import bundle
import representation as rep
from corpus import FILES, ROOT


def measure(fn,*args,**kwargs):
    t = time.perf_counter()
    value = fn(*args,**kwargs)
    return value,time.perf_counter()-t


def timing(blob, enc, decode, data):
    # Warm up once; equality checks do not inflate the timed interval.
    if decode(blob) != data:
        raise AssertionError("warmup roundtrip mismatch")
    dt = []
    for _ in range(5):
        x, t = measure(decode,blob)
        if x != data:
            raise AssertionError("roundtrip mismatch")
        dt.append(t)
    dec = statistics.median(dt)
    return dict(bytes=len(blob), encode_s=enc, decode_s=dec, decode_repeats_s=dt,
                decode_MBps=len(data)/1e6/dec, exact=True)


def codecs(data):
    for v in (3,19):
        yield f"zstd-{v}", zstandard.ZstdCompressor(level=v,write_checksum=True).compress, zstandard.ZstdDecompressor().decompress
    yield "brotli-9", lambda d: brotli.compress(d,quality=9), brotli.decompress
    yield "xz-6", lambda d: lzma.compress(d,preset=6), lzma.decompress
    yield "deflate-6", lambda d: zlib.compress(d,6), zlib.decompress


def realism(data, fmt):
    methods = {}
    for label,codec,decoder in codecs(data):
        blob,enc = measure(codec,data)
        methods[label] = timing(blob,enc,decoder,data)
    (exposed,typed,info),tx = measure(rep.represent,data,fmt)
    selected = {"TXT":"grammar","PDF":"grammar","DOCX":"grammar","ONNX":"tensor",
                "PNG":"spatial-learned","EXE":"algebra","JPEG":"algebra"}[fmt]
    setups = [
        ("raw-framed",[rep.raw(data)],None,"local",0),
        ("exposed",exposed,None,"local",tx),
        ("typed",typed,None,"local",tx),
        ("math-forced",typed,selected,"all",tx),
        ("math-local",typed,selected,"local",tx),
    ]
    if fmt == "PNG":
        setups.extend([("spatial-fixed-forced",typed,"spatial-fixed","all",tx),
                       ("spatial-fixed-local",typed,"spatial-fixed","local",tx)])
    measurement_cache = {}
    for name, sections, option, policy, prep in setups:
        (s, stats, params),fit = measure(bundle.recipe,sections,option,policy)
        for v in (3,19):
            key = (hashlib.sha256(s).digest(),v)
            if key not in measurement_cache:
                blob, enc = measure(bundle.frame,s,data,v)
                measurement_cache[key] = timing(blob,enc,bundle.unpack,data)
            row = measurement_cache[key].copy()
            methods[f"{name}+zstd-{v}"] = {**row, "encode_s": row["encode_s"]+prep+fit,
                                          "rep_s":prep,"recipe_s":fit,"serialized_recipe_bytes":len(s),
                                          "stats":stats,"params":params}
    return methods,info


def reference(data,fmt):
    # Load the prior code read-only; no changes or global test settings.
    sys.path.insert(0,str(ROOT.parent/"zip-protocol"))
    from experiments.sxz4 import spans4, transforms4
    rank, tx = measure(transforms4.screen,data,sample=32768)
    chosen = rank[0][1] if rank else (0,)
    methods = {}
    for label,on in (("sxz4-tx",False),("sxz4-on",True)):
        (blob,st), enc = measure(spans4.pack,data,chain=chosen,spans_on=on)
        methods[label] = timing(blob,enc+tx,spans4.unpack,data)
        methods[label].update(dict(probes=st.probes, modelled=st.modelled_bytes, models=st.models,
                                   spans=st.spans,residual_bytes=st.residual_bytes,model_cost=st.model_cost))
    return methods,dict(chain=chosen)


def save(name,value):
    out = ROOT/"results"
    out.mkdir(exist_ok=True)
    dest = out/name
    tmp = dest.with_suffix(".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    tmp.replace(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=["real","reference"])
    parser.add_argument("--only")
    args = parser.parse_args()
    action = {"real":realism,"reference":reference}[args.suite]
    results = dict(environment=dict(python=sys.version,platform=platform.platform(),
                                    processor=platform.processor(), zstd=zstandard.__version__,
                                    brotli=brotli.__version__, reps=5), rows=[])
    name = args.suite + ("-"+args.only if args.only else "") + ".json"
    for split,fmt,p,source in FILES:
        if args.only is not None and args.only not in p.name:
            continue
        data = p.read_bytes()
        print("start",fmt,p.name,len(data),flush=True)
        methods,info = action(data,fmt)
        results["rows"].append(dict(split=split,fmt=fmt,name=p.name,path=str(p.relative_to(ROOT.parent)),
                                    source=source,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),
                                    details=info,methods=methods))
        save(name,results)
        print(p.name, {k:r["bytes"] for k,r in methods.items()}, flush=True)


if __name__ == "__main__":
    main()
