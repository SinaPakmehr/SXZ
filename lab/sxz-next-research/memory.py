"""Process-level Windows peak working set on fresh decoders (includes Python/imports)."""
import ctypes
import hashlib
import json
import lzma
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import brotli
import zstandard

import bundle
import representation
from bench import save
from corpus import FILES, ROOT


class Counters(ctypes.Structure):
    _fields_ = [("size",ctypes.c_ulong),("faults",ctypes.c_ulong)]+[(k,ctypes.c_size_t)
                for k in ("peak","working","peak_paged","paged","peak_nonpaged","nonpaged","page","peak_page")]


def process_memory():
    if __import__('os').name != 'nt':
        import resource, sys
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
        return dict(peak_ws_bytes=peak,current_ws_bytes=None)
    api = ctypes.windll.psapi.GetProcessMemoryInfo
    api.argtypes = [ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    api.restype = ctypes.c_int
    me = ctypes.windll.kernel32.GetCurrentProcess
    me.restype = ctypes.c_void_p
    s = Counters(ctypes.sizeof(Counters))
    if not api(me(),ctypes.byref(s),ctypes.sizeof(s)):
        raise OSError("GetProcessMemoryInfo")
    return dict(peak_ws_bytes=s.peak,current_ws_bytes=s.working)


def measure_worker(method,path):
    c = Path(path).read_bytes()
    first = process_memory()
    decoder = {"zstd-19":zstandard.ZstdDecompressor().decompress, "brotli-9":brotli.decompress,
               "xz-6":lzma.decompress, "xnb1":bundle.unpack}[method]
    d = decoder(c)
    second = process_memory()
    print(json.dumps(dict(method=method,before=first,after=second,sha256=hashlib.sha256(d).hexdigest())))


def main():
    rows = []
    temp = Path(__file__).resolve().parents[2]/"datasets/tools"
    with TemporaryDirectory() as root:
        blob = Path(root)/"archive"
        for _,fmt,p,_ in FILES:
            if p.name not in ("bert.pdf","squeezenet1.1-7.onnx","hopper.png"):
                continue
            d = p.read_bytes()
            _,tx,_ = representation.represent(d,fmt)
            rec = bundle.recipe(tx,"spatial-fixed" if fmt=="PNG" else None)[0]
            options = {"zstd-19":zstandard.ZstdCompressor(level=19,write_checksum=True).compress(d),
                       "brotli-9":brotli.compress(d,quality=9),"xz-6":lzma.compress(d,preset=6),
                       "xnb1":bundle.frame(rec,d,19)}
            for name,c in options.items():
                blob.write_bytes(c)
                out = subprocess.run([sys.executable,"-B",str(ROOT/"memory.py"),name,str(blob)],
                                     capture_output=True,text=True,check=True,timeout=30)
                statistics = json.loads(out.stdout)
                assert statistics["sha256"] == hashlib.sha256(d).hexdigest()
                rows.append(dict(name=p.name,archive_bytes=len(c),**statistics))
    save("decode-memory.json",rows)


if __name__ == "__main__":
    if len(sys.argv) == 3:
        measure_worker(*sys.argv[1:])
    else:
        main()
