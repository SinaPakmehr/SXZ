"""Pre-registered narrow spatial follow-up and optional JPEG XL control."""
import hashlib
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

import bundle
import representation as rep
from bench import timing,measure,save
from corpus import ROOT, FILES


def png():
    panel = [(s,p,u) for s,f,p,u in FILES if f == "PNG"]
    panel.extend(("test-followup",ROOT.parents[1]/"datasets/corpus"/n,"https://raw.githubusercontent.com/python-pillow/Pillow/main/Tests/images/"+n)
                 for n in ("flower_thumbnail.png","exif.png"))
    rows = []
    for split,p,source in panel:
        data = p.read_bytes()
        (fmt,typed,info), tx = measure(rep.png,data)
        methods = {}
        for opt in (None,"spatial-fixed","spatial-learned","tree-fixed","tree-learned"):
            (body,stat,params),fit = measure(bundle.recipe,typed,opt)
            for level in (3,19):
                blob, enc = measure(bundle.frame,body,data,level)
                methods[f"{opt or 'typed'}+zstd-{level}"] = {
                    **timing(blob,tx+fit+enc,bundle.unpack,data), "stats":stat,"params":params}
        rows.append(dict(name=p.name,split=split,source=source,bytes=len(data),
                         sha256=hashlib.sha256(data).hexdigest(),details=info,methods=methods))
        save("png-followup.json",rows)
        print(p.name,info,{k:v["bytes"] for k,v in methods.items()},flush=True)


def jpeg():
    root = Path(os.environ.get("SXZ_JXL", str(ROOT.parent.parent/"datasets/tools")))
    enc,dec = root/"cjxl.exe",root/"djxl.exe"
    rows = []
    for split,fmt,p,source in FILES:
        if fmt != "JPEG":
            continue
        d = p.read_bytes()
        with TemporaryDirectory(dir=root) as work:
            path = Path(work)
            c = path/"sample.jxl"
            r = path/"sample.jpg"
            t = perf_counter()
            opts = ["--num_threads=1","--effort=7","--lossless_jpeg=1"]
            a = subprocess.run([enc,p,c,*opts],capture_output=True,check=True,timeout=100)
            et = perf_counter()-t
            ts = []
            for i in range(5):
                t = perf_counter()
                b = subprocess.run([dec,c,r,"--num_threads=1"],capture_output=True,check=True,timeout=100)
                ts.append(perf_counter()-t)
                assert r.read_bytes() == d
                r.unlink()
            ts.sort()
            rows.append(dict(name=p.name,bytes=len(d),source=source,method="JPEG XL v0.13.0",
                             compressed=c.stat().st_size,encode_options=opts,encode_s=et,
                             decode_median_s=ts[2],decode_MBps=len(d)/1e6/ts[2],
                             decode_seconds=ts,exact=True,tools_stdout=(a.stdout+b.stdout).decode("utf-8","replace"),
                             tools_stderr=(a.stderr+b.stderr).decode("utf-8","replace")))
    save("jpeg-xl.json",rows)


if __name__ == "__main__":
    import sys
    {"png":png,"jpeg":jpeg}[sys.argv[1]]()
