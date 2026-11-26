"""Rust k-mer index front end; main search does not require a cached decoder bank."""
from ctypes import (CDLL,Structure,c_char_p,c_size_t,c_uint32,c_uint64,c_void_p,byref,
                    POINTER)
from itertools import accumulate
from pathlib import Path

from represent import BASE,K,UNITS

ROOT=Path(__file__).resolve().parent
DLL=ROOT/("msm_index.dll" if __import__("os").name == "nt" else "libmsm_index.dylib" if __import__("sys").platform == "darwin" else "libmsm_index.so")


class Hit(Structure):
    _fields_=[(k,c_uint32) for k in ("target","start","len","gid")]


class Stats(Structure):
    _fields_=[(k,c_uint64) for k in
      ("count","sum","covered","best","repeated_key","candidates","dropped","nentries")]+[
      ("pos",c_uint64*10),("source",c_uint64*64),("hist",c_uint64*16)]


LIB=None


def ffi():
    global LIB
    if LIB is None:
        LIB=CDLL(str(DLL))
        lib=LIB
        lib.make.argtypes=[c_char_p,c_size_t,POINTER(c_uint32),c_size_t,c_uint32,c_size_t]
        lib.free.argtypes=[c_void_p]; lib.free.restype=None
        lib.make.restype=c_void_p
        lib.search.argtypes=[c_void_p,c_char_p,c_size_t,POINTER(Hit),c_size_t,c_size_t,c_uint32,POINTER(Stats)]
        lib.search.restype=c_size_t
    return LIB


class Index:
    def __init__(self,parts,mode,k=None):
        self.lib=ffi()
        self.mode=mode
        self.k=k if k is not None else K[BASE[mode]]
        self.parts=parts
        offsets=[0,*accumulate(map(len,parts))]
        self.addr=self.lib.make(b"".join(parts),offsets[-1],(c_uint32*len(offsets))(*offsets),
                                 len(offsets),BASE[mode],self.k)
        if not self.addr: raise ValueError("native index constraints")

    def close(self):
        if self.addr:
            self.lib.free(self.addr)
            self.addr=None

    def __enter__(self): return self
    def __exit__(self,*exc): self.close()

    def query(self,d,cap=180000,min_len=None):
        nb,ns=UNITS[self.mode]
        span=ns or 20
        if min_len is None:
            min_len=max(self.k,(7*span+nb-1)//nb)
        slots=(Hit*cap)()
        st=Stats()
        n=self.lib.search(self.addr,d,len(d),slots,cap,min_len,max(1,span//nb),byref(st))
        found=[(s.target,s.gid,s.start,s.len) for s in slots[:n]]
        stat={k:(int(getattr(st,k)) if k not in ("pos","source","hist") else list(getattr(st,k)))
              for k,_ in Stats._fields_}
        stat["source"]=stat["source"][:len(self.parts)]
        stat.update(seed_symbols=self.k,min_suggested_symbols=min_len,target_symbols=len(d),
                    raw_coverage=(stat["covered"]/len(d) if d else 0),
                    mean_longest=(stat["sum"]/stat["count"] if stat["count"] else 0))
        return found,stat
