"""Format-specific controls, with reconstruction side information counted."""
import hashlib
import re
import subprocess
import time
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import zstandard

import inputs
from inputs import prev
from dsl import Reader, seq
import models
import wire
from study import TEMP,dump,measure,timings,memory
import bundle as prior_bundle


HDR=re.compile(rb"P6\s+(\d+)\s+(\d+)\s+255(?:\r\n|[\x09-\x0d ])")


def jxl_unpack(blob,root):
    t=time.perf_counter()
    r=Reader(blob)
    n,crc,metasize=r.get(),r.get(),r.get()
    meta=Reader(wire.decode_frame_bytes(r.take(metasize)))
    nsec=meta.get()
    c=Path(root)/"restore.jxl"
    raw=Path(root)/"restore.ppm"
    c.write_bytes(r.take(len(blob)-r.at))
    tt=time.perf_counter()
    subprocess.run([inputs.TEMP/"djxl.exe",c,raw,"--num_threads=1"],check=True,capture_output=True,timeout=35)
    pp=raw.read_bytes()
    raw.unlink()
    a=time.perf_counter()
    g=HDR.match(pp)
    if not g:
        raise ValueError("PPM frame")
    w,h=int(g[1]),int(g[2])
    pix=np.frombuffer(pp[g.end():],np.uint8).reshape(h*w,3).copy()
    pix[:,0]-=pix[:,1]
    pix[:,2]-=pix[:,1]
    ch=[pix[:,i].tobytes() for i in range(3)]
    out=bytearray()
    for _ in range(nsec):
        kind,l,s=meta.get(),meta.get(),meta.get()
        aux=bytes(meta.take(s))
        if kind==prev.PIXEL:
            rr=Reader(aux)
            assert (rr.get(),rr.get(),rr.get())==(w,h,3)
            out+=prev.inverse(kind,l,aux,ch)
        else:
            out+=prev.inverse(kind,l,aux,[bytes(meta.take(meta.get()))])
    meta.finish()
    out=bytes(out)
    assert len(out)==n and zlib.crc32(out)==crc
    e=time.perf_counter()
    return out,[tt-t,a-tt,e-a]


def image_jxl(data):
    def prep():
        _,parts,detail=prev.png(data)
        if not detail["pixels"] or detail["channels"]!=3:
            raise ValueError("panel must be a three-channel PNG")
        w,h=detail["width"],detail["height"]
        meta=bytearray(seq(len(parts)))
        ppm=None
        for p in parts:
            meta+=seq(p.kind,p.length,len(p.aux))+p.aux
            if p.kind==prev.PIXEL:
                rgb=np.column_stack([np.frombuffer(c.data,np.uint8) for c in p.channels])
                rgb[:,0]+=rgb[:,1]
                rgb[:,2]+=rgb[:,1]
                ppm=f"P6\n{w} {h}\n255\n".encode()+rgb.tobytes()
            else:
                assert len(p.channels)==1
                d=p.channels[0].data
                meta+=seq(len(d))+d
        return ppm,bytes(meta)
    (ppm,meta),prep_s=measure(prep)
    with TemporaryDirectory() as root:
        a=Path(root)/"orig.ppm"
        b=Path(root)/"recomp.jxl"
        a.write_bytes(ppm)
        cmd=[inputs.TEMP/"cjxl.exe",a,b,"--num_threads=1","--effort=7","--distance=0"]
        _,es=measure(subprocess.run,cmd,check=True,capture_output=True,timeout=60)
        jxl=b.read_bytes()
        mz=zstandard.ZstdCompressor(level=9,write_checksum=True).compress(meta)
        head=seq(len(data),zlib.crc32(data),len(mz))
        blob=head+mz+jxl
        r=timings(blob,data,lambda c:jxl_unpack(c,root),es+prep_s,True)
        r["decode_stage_medians_s"]={
            {"zstd_parse":"extract_metadata_and_write_jxl",
             "expand_records":"djxl_process_and_io",
             "restore_container_crc":"png_reconstruction_crc"}[k]:v
            for k,v in r["decode_stage_medians_s"].items()}
        r.update(dict(method="JPEG XL 0.13.0 pixels + exact PNG replay",header=len(head),jxl=len(jxl),
                      reconstruction_meta=len(mz),reconstruction_meta_raw=len(meta),
                      rss_note="CLI subprocess RSS not measured; decode includes temp file I/O and process startup"))
        return r


def tensor(data):
    (parts,_),prep=measure(inputs.tensors,data)
    s,records=wire.layout(parts)
    ops=[]
    for a in records:
        width=5 if a.group[:2]==("tensor",1) else a.width
        ops.append(models.Model(models.LIT,width,len(a.data),models.plane(a.data,width)))
    (c,meta),tc=measure(wire.encode,data,s,ops,9)
    r=timings(c,data,lambda b:wire.unpack(b,True),prep+tc,True)
    r.update(method="FP32 exponent alignment + byte planes + Zstd-9 (own conventional control, not ZipNN)",cost=meta)
    return r


def documents(data,family):
    (s,note),pt=measure(prev.deflates,data,"PDF" if family=="pdf" else "DOCX")
    (body,stats,_),et=measure(prior_bundle.recipe,s)
    c,tc=measure(prior_bundle.frame,body,data,9)
    r=timings(c,data,prior_bundle.unpack,pt+et+tc)
    r.update(method="Preflate-RS 0.7.6 + whole exposed stream + Zstd-9 (no record cuts)",
             exposure=note,reconstruction_aux_raw=stats["aux_bytes"],frame_recipe_bytes=len(body))
    return r


if __name__=="__main__":
    results=[]
    for fam,split,p,src in inputs.ENTRY:
        if fam not in ("image","tensor","pdf","xml"):
            continue
        d=p.read_bytes()
        r=(image_jxl(d) if fam=="image" else tensor(d) if fam=="tensor" else documents(d,fam))
        results.append(dict(file=p.name,family=fam,source=src,input_bytes=len(d),
                            sha256=hashlib.sha256(d).hexdigest(),**r))
        dump("specialized",results)
        print(fam,p.name,r["bytes"],flush=True)
