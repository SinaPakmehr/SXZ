"""Planted-span discrimination, scaling and profile-driven port experiments."""
import argparse
import cProfile
import ctypes
import functools
import hashlib
import io
import os
import pstats
import random
import statistics
import struct
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

import dsl
import bundle
import search
from accelerate import NATIVE, SIZES, output, rice_native, scan_native, scan_python
from bench import save, measure
from corpus import ROOT, DATA
import representation as rep

sys.path.insert(0,str(ROOT.parent/"zip-protocol"))
from experiments.sxz4 import program4, residual4, spans4
from experiments.sxz4.validate4 import _spans_of


def linear(k,n):
    seed,co,bias = ((3,6),(3,5),7) if k == 2 else ((5,11,28),(9,3,13),3)
    return dsl.evaluate(dsl.program([dsl.recurrence(4,n//4,1<<32,seed,co,bias)]))


def actual_fits(data, item, span):
    start,n = item["pos"],item["len"]
    if span is None or span["kind"] != 0:
        return None
    lo, hi = max(start,span["start"]),min(start+n,span["start"]+span["length"])
    if hi <= lo:
        return None
    pred = span["model"].predict_bytes(span["params"],hi-span["start"])[lo-span["start"]:]
    hits = sum(a == b for a,b in zip(pred,data[lo:hi]))
    return dict(overlap=(hi-lo)/n, predicted_fraction=hits/n, model=span["model"].name)


def score_native(target,hits):
    start,n = target["pos"],target["len"]
    end = start+n
    covered = sum(max(0,min(x+y,end)-max(x,start)) for x,y,*_ in hits)
    return covered/n


def old_fit_windows(data,row):
    start,n = row["pos"],row["len"]
    passed = []
    for w in SIZES:
        if start+w > len(data):
            continue
        model = program4.Order2Word()
        fits = model.fit_params(data[start:start+w])
        if fits:
            guess = model.predict_bytes(fits[0],n)
            passed.append((w,sum(a==b for a,b in zip(guess,data[start:start+n]))/n))
    return passed


def planted():
    rng = random.Random(77861)
    samples = {
        "random":rng.randbytes(262144),
        "text":(DATA/"plrabn12.txt").read_bytes()[:262144],
        "jpeg":(DATA/"raw/gull.jpg").read_bytes()[2048:2048+262144],
    }
    rows = []
    for name,base in samples.items():
        data = bytearray(base)
        targets = []
        specs = [(2,a) for a in (32,64,128,256,512,1024,4096,65536)]+[(3,a) for a in (128,512,4096)]
        # Reserve disjoint slots proportional to the test size; jitter both start
        # and length (including unaligned starts).
        at = 0
        for k, nominal in specs:
            n = nominal + 4*rng.randrange(0,min(nominal//16,128))
            start = at+rng.randrange(129,13000)
            data[start:start+n] = linear(k,n)
            targets.append(dict(pos=start,len=n,nominal=nominal,order=k))
            at += n+14000
        data = bytes(data)
        (blob,st),sec = measure(spans4.pack,data,chain=(0,),allow_program=True)
        if spans4.unpack(blob) != data:
            raise AssertionError("SXZ4")
        spans = _spans_of(blob)
        (native,total),ts = measure(scan_native,data)
        pure,totalpy = scan_python(data)
        assert (native,total) == (pure,totalpy)
        wire = search.bytes_graph(data,native) if native else None
        baseline = bundle.frame(bundle.recipe([rep.raw(data)])[0],data,3)
        new = bundle.program_archive(wire,data) if wire else baseline
        assert bundle.unpack(new) == data
        for row in targets:
            start,n = row["pos"],row["len"]
            subset = data[start:start+n]
            best = max((it for s in spans if (it:=actual_fits(data,row,s)) is not None),
                       key=lambda it:it["predicted_fraction"],default=None)
            old_at = spans4.try_at(data,start,True)
            old_nogate = spans4.try_at(data,start,True,gate=False)
            fit = search.fit_recurrence(subset)
            if fit:
                assert dsl.evaluate(dsl.program([fit[0]]),n) == subset
            row.update(sxz4_blind=best, sxz4_oracle=actual_fits(data,row,old_at),
                       sxz4_oracle_no_gate=actual_fits(data,row,old_nogate),
                       sxz4_order2_oracle_windows=old_fit_windows(data,row),
                       native_coverage=score_native(row,native),
                       recurrence_oracle=dict(program_bytes=len(dsl.program([fit[0]])),**fit[1]) if fit else None)
        rows.append(dict(name=name,sha256=hashlib.sha256(data).hexdigest(),base_scan_hits=scan_native(base)[1],
                         legacy=dict(bytes=len(blob),seconds=sec,probes=st.probes,spans=st.spans),
                         native=dict(seconds=ts,hits=native,count=total,
                                     max_scales=[max(w for w in SIZES if w <= h[1]) for h in native],
                                     forced_bytes=len(new),framed_base=len(baseline)),targets=targets))
        save("planted.json",rows)
        print("planted",name,"old bytes",len(blob),"new+zstd",len(new),"hits",total,flush=True)


def scale(legacy=True):
    p = Path(os.environ.get("SXZ_ENWIK8",
             str(ROOT.parent.parent/"datasets/enwik8")))
    data = p.read_bytes()
    rows = []
    for n in (10**6,10**7,10**8):
        d = data[:n]
        assert len(d) == n
        # Late under a uniform scan, unseen under a left-to-right time budget.
        start = n-78765
        target = dict(pos=start,len=512)
        mixed = d[:start]+linear(2,512)+d[start+512:]
        (hits,total), t = measure(scan_native,mixed)
        repeats = [t]+[measure(scan_native,mixed)[1] for _ in range(4)]
        native_base, bt = measure(scan_native,d)
        small = mixed[:131072]
        native_small, ns = measure(scan_native,small)
        py, pt = measure(scan_python,small)
        assert native_small == py
        row = dict(bytes=n,native_s=statistics.median(repeats), native_repeats_s=repeats,
                   throughput_MBps=n/1e6/statistics.median(repeats), target=target,
                   native_target=score_native(target,hits), clean_s=bt,clean_hits=native_base[1],
                   native_total_hits=total, max_anchor_positions=n-31,
                   reference_prefix_bytes=len(small), python_prefix_s=pt,native_prefix_s=ns)
        # One direct legacy comparison at 100 MB; same exact target/representation.
        if legacy and n == 10**8:
            (found,st), ls = measure(spans4.find_spans,mixed,True)
            row.update(sxz4_scan_s=ls,sxz4_scan_probes=st.probes,
                       sxz4_target=max((it["predicted_fraction"] for s in found
                                       if (it:=actual_fits(mixed,target,s)) is not None),default=0))
        rows.append(row)
        save("scale.json",rows)
        print("scale",row,flush=True)


def optimized_rice(values,max_k=32):
    n = len(values)
    lo,hi = 0,min(max_k,64)
    # Difference L(k+1)-L(k) = n-sum((u>>k)-(u>>(k+1))), monotone.
    while lo < hi:
        k = (lo+hi)//2
        if sum(((x>>k)+1)>>1 for x in values) <= n:
            hi = k
        else:
            lo = k+1
    size = (residual4.rice_size(values,lo)+7)//8
    return lo,rice_native(values,lo,size)


def optimized_prediction():
    old = program4.Order2Word.predict_bytes

    def pred(self,params,n):
        code,order,phase,_,a,b,c,x,y = params
        if program4.WIDTHS[code] == 4 and program4._order(order) == "little" and phase == 0:
            return output("rec2",n,a,b,c,x,y)
        return old(self,params,n)
    return pred


def profile():
    out_dir = ROOT/"results"
    out_dir.mkdir(exist_ok=True)
    data = (ROOT.parent/"sxz4-corpus/ecg-train.bin").read_bytes()
    variants = []
    p = (16,0xb400,0x1738)
    q = (0x12457834,1)
    v = [random.Random(17+i).randrange(1<<24) if i%23 else 1<<40 for i in range(16384)]
    compare = {
        "lfsr-262144":(lambda:program4.LfsrBytes().predict_bytes(p,262144),lambda:output("lfsr",262144,*p)),
        "xorshift-262144":(lambda:program4.XorShiftBytes().predict_bytes(q,262144),lambda:output("xorshift",262144,*q)),
        "rice-16384":(lambda:residual4._best_rice(v,64),lambda:optimized_rice(v,64)),
    }
    micro = {}
    for label,(slow,fast) in compare.items():
        assert slow() == fast()
        micro[label] = dict(python=[measure(slow)[1] for _ in range(5)],native=[measure(fast)[1] for _ in range(5)])
    for fast in (False,True):
        with ExitStack() as stack:
            if fast:
                stack.enter_context(patch.object(program4.LfsrBytes,"predict_bytes",lambda self,p,n:output("lfsr",n,*p)))
                stack.enter_context(patch.object(program4.XorShiftBytes,"predict_bytes",lambda self,p,n:output("xorshift",n,*p)))
                stack.enter_context(patch.object(program4.Order2Word,"predict_bytes",optimized_prediction()))
                stack.enter_context(patch.object(residual4,"_best_rice",optimized_rice))
            p = cProfile.Profile()
            fn = functools.partial(spans4.pack,chain=(6,1))
            (blob,st), wall = measure(p.runcall,fn,data)
            assert spans4.unpack(blob) == data
            unprofiled = []
            for _ in range(3):
                (other,stats), elapsed = measure(fn,data)
                assert other == blob
                unprofiled.append(elapsed)
        stream = io.StringIO()
        pstats.Stats(p,stream=stream).sort_stats("cumulative").print_stats(35)
        (out_dir/("profile-native.txt" if fast else "profile-python.txt")).write_text(stream.getvalue(),encoding="utf-8")
        variants.append(dict(native=fast,profile_seconds=wall,unprofiled_s=unprofiled,
                             archived=len(blob),probes=st.probes,sha256=hashlib.sha256(blob).hexdigest()))
    save("profile.json",dict(micro=micro,ecg=variants))
    print("profile",variants,flush=True)


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("suite",choices=["planted","scale","profile"])
    a.add_argument("--native-only", action="store_true")
    a = a.parse_args()
    if a.suite == "scale":
        scale(not a.native_only)
    else:
        globals()[a.suite]()
