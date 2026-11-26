"""Frozen full-file panel. No format parsing in the experimental path."""
from hashlib import sha256
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parent
P=ROOT.parent
S=P.parent/"datasets/sxz5-data"
R=S/"raw"
O=P/"sxz-next-research"
E=Path(os.environ.get("MSMC_ENWIK8",P.parent/"datasets/enwik8"))
CANT="https://corpus.canterbury.ac.nz/descriptions/"
SIL="https://mattmahoney.net/dc/silesia.zip"
WIK="https://upload.wikimedia.org/wikipedia/commons/"
DOC="https://github.com/python-openxml/python-docx"
ONNX="https://github.com/onnx/models/tree/main/validated/vision/classification"
PIL="https://github.com/python-pillow/Pillow/tree/main/Tests/images"
ENTRIES=[
    ("dev","TXT",S/"alice29.txt",CANT),
    ("dev","PDF",R/"irs1040.pdf","https://www.irs.gov/pub/irs-pdf/f1040.pdf"),
    ("dev","JPEG",R/"gull.jpg",WIK+"9/9a/Gull_portrait_ca_usa.jpg"),
    ("dev","XML",R/"bbc.rss.xml","https://feeds.bbci.co.uk/news/rss.xml"),
    ("dev","PNG",ROOT.parents[1]/"datasets/corpus/python-logo.png","https://www.python.org/static/community_logos/python-logo.png"),
    ("test","TXT",S/"plrabn12.txt",CANT),
    ("test","TXT",S/"book2","https://corpus.canterbury.ac.nz/resources/calgary.tar.gz"),
    ("test","PDF",R/"bert.pdf","https://arxiv.org/pdf/1810.04805"),
    ("test","DOCX",R/"docx-table.docx",DOC),
    ("test","XLSX",R/"tree-test.xlsx","https://api.github.com/repos/torvalds/linux/git/trees/master?recursive=1"),
    ("test","PPTX",R/"pptx-fill.pptx","https://github.com/scanny/python-pptx"),
    ("test","HTML",R/"wiki.html","https://en.wikipedia.org/api/rest_v1/page/html/Data_compression"),
    ("test","JSON",R/"linux-tree.json","https://api.github.com/repos/torvalds/linux/git/trees/master?recursive=1"),
    ("test","XML",S/"silesia/xml",SIL),
    ("test","JPEG",R/"banana.jpg",WIK+"8/8a/Banana-Single.jpg"),
    ("test","PNG",ROOT.parents[1]/"datasets/corpus/hopper.png",PIL),
    ("test","BMP",ROOT.parents[1]/"datasets/corpus/hopper.bmp",PIL),
    ("test","MP4",R/"sample5.mp4","https://download.samplelib.com/mp4/sample-5s.mp4"),
    ("test","MP3",R/"sample15.mp3","https://download.samplelib.com/mp3/sample-15s.mp3"),
    ("test","WAV",R/"audio-slice.wav","local complete WAV fixture from prior SXZ public audio"),
    ("test","EXE",P.parent/"datasets/audit-assets/7zr.exe","https://www.7-zip.org/download.html"),
    ("test","DLL",P.parent/"datasets/tools/zstd-release/zstd-v1.6.0-win64/lib/libzstd.dll",
      "https://github.com/meta/zstd/releases/download/v1.6.0/zstd-v1.6.0-win64.zip"),
    ("test","ZIP",R/"silesia.zip",SIL),
    ("test","ONNX",ROOT.parents[1]/"datasets/corpus/squeezenet1.1-7.onnx",ONNX),
]

DEV={"alice29.txt","irs1040.pdf","gull.jpg","bbc.rss.xml","python-logo.png"}
RADIX={"alice29.txt","irs1040.pdf","python-logo.png","docx-table.docx","hopper.bmp","sample15.mp3"}
REFERENCE={"alice29.txt","irs1040.pdf","plrabn12.txt","bert.pdf","docx-table.docx","hopper.bmp","7zr.exe","squeezenet1.1-7.onnx"}
TRAIN=[S/n for n in ("asyoulik.txt","lcet10.txt","cp.html","fields.c","paper1","paper2","book1","progc","progl")]


def pick(which):
    out=[]
    for part,f,p,s in ENTRIES:
        if which=="dev" and p.name not in DEV: continue
        if which=="radix" and p.name not in RADIX: continue
        if which=="reference" and p.name not in REFERENCE: continue
        if which=="test" and part!="test": continue
        if f=="DLL" and not p.exists():
            p=next((P.parent/"datasets/tools/zstd-release").rglob("*.dll"))
        d=p.read_bytes()
        out.append((dict(name=p.name,split=part,format=f,source=s,path=str(p),
                         input_bytes=len(d),sha256=sha256(d).hexdigest()),d))
    return out
