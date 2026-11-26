"""Small known-origin and blind-search controls with fully serialized costs."""
import hashlib
import random
import struct

import dsl
import bundle
import representation as rep
import search
from bench import codecs, measure, save, timing
from controls import program4


def generate_rec(n,width,mod,seed,coefficients,bias):
    return dsl.evaluate(dsl.program([dsl.recurrence(width,n,mod,seed,coefficients,bias)]))


def word_expr(n,width,init,ops):
    words = [init]
    for _ in range(1,n):
        x = words[-1]
        for op,p in ops:
            x = dsl.operation(x,p,op,8*width)
        words.append(x)
    return b"".join(x.to_bytes(width,"little") for x in words)


def refs(d, op):
    if op == dsl.PRIME and len(d) % 4 != 0:
        return None
    n = len(d)//4 if op == dsl.PRIME else len(d)
    if not n or n > 4100:
        return None
    cap = 2048
    for kind in range(2 if op == dsl.PRIME else 3):
        lookup = dsl.prime_data(0,n+cap,kind) if op == dsl.PRIME else dsl.constant_data(kind,0,n+cap)
        off = lookup.find(d)
        unit = 4 if op == dsl.PRIME else 1
        if off >= 0 and off % unit == 0:
            return dsl.program([dsl.seq(op,kind,off//unit,n)])
    return None


def narrow_composition(data):
    for n in (256,512,1024,2048,4096,8192):
        if not 2*n < len(data) <= 3*n:
            continue
        a,b,c = data[:n],data[n:2*n],data[2*n:]
        p = search.fit_recurrence(a)
        if p is None or not a.endswith(c):
            continue
        mask = a[0] ^ b[0]
        if not all((x ^ mask) == y for x,y in zip(a,b)):
            continue
        return dsl.program([p[0],dsl.seq(dsl.MAP,0,1,dsl.XOR,mask),
                           dsl.seq(dsl.SLICE,0,len(a)-len(c),len(c)),
                           dsl.seq(dsl.CAT,3,0,1,2)])
    return None


def main():
    rng = random.Random(86174)
    exact = generate_rec(4096,4,1<<32,(3,6),(3,5),7)
    contaminated = bytearray(exact)
    for _ in range(175):
        contaminated[rng.randrange(128,len(exact))] ^= 1 << rng.randrange(8)
    def recurrent(d,width=4):
        out = search.fit_recurrence(d,width)
        if out:
            return dsl.program([out[0]]),out[1]
        return None,{}
    rows = []
    inputs = [
        ("fib-mod-2^32", generate_rec(4096,4,1<<32,(0,1),(1,1),0), "fit"),
        ("order3", generate_rec(4096,4,1<<32,(5,11,28),(9,3,13),3), "fit"),
        ("lcg-prime-unknown",generate_rec(4096,4,2147483647,(186617,),(48271,),401), "fit"),
        ("lcg-composite-unknown",generate_rec(4096,4,1000000000,(191165,),(16721,),6729), "fit"),
        ("prime-index-1297",dsl.prime_data(1297,4096,False),"prime"),
        ("gap-index-733",dsl.prime_data(733,4096,True),"prime"),
        ("gap-beyond-budget",dsl.prime_data(2501,4096,True),"prime"),
        *((f"constant-{name}-index-{offset}",dsl.constant_data(which,offset,4096),"constant")
          for which,(name,offset) in enumerate((("pi",481),("e",1337),("phi",2047)))),
        ("GF256-affine",word_expr(4096,1,113,((dsl.GFMUL,13),(dsl.XOR,231))),"symbol8"),
        ("mul-rotate-xor",word_expr(4096,4,1899744,((dsl.MUL,0x9e3779b1),(dsl.ROL,7),(dsl.XOR,0x1a5bc1))),"symbol32"),
        ("xor-add-unlisted-mul",word_expr(4096,4,318997,((dsl.MUL,0x12adf43),(dsl.ROL,7),(dsl.ADD,0x1a5bc1))),"symbol32"),
        ("xorshift32",dsl.evaluate(dsl.program([dsl.seq(dsl.XORSHIFT,16384,891783,1)])),"xorshift"),
        ("LFSR",dsl.evaluate(dsl.program([dsl.seq(dsl.LFSR,16384,16,0xb400,0x1738)])),"lfsr"),
        ("recurrence-with-exceptions",bytes(contaminated),"patch"),
        ("recurrence-map-slice",exact[:4096]+bytes(x^107 for x in exact[:4096])+exact[3072:4096],"compose"),
        ("random-negative",rng.randbytes(16384),"negative"),
    ]
    for name,data,tag in inputs:
        base,enc = measure(bundle.frame,bundle.recipe([rep.raw(data)])[0],data,3)
        baseline = timing(base,enc,bundle.unpack,data)
        methods = {"raw-framed+zstd-3":baseline}
        for label,codec,decoder in codecs(data):
            blob,t = measure(codec,data)
            methods[label] = timing(blob,t,decoder,data)
        choices = {}

        def check(label,fn):
            (wire,metadata), dt = measure(fn)
            stats = dict(search_s=dt,found=wire is not None,meta=metadata)
            if wire is not None:
                assert dsl.evaluate(wire,len(data)) == data
                blob,enc = measure(bundle.program_archive,wire,data,3)
                stats.update(wire_bytes=len(wire), net_save=len(base)-len(blob),
                             **timing(blob,enc+dt,bundle.unpack,data))
            choices[label] = stats

        if tag in ("fit","negative"):
            check("algebra",lambda:recurrent(data))
        if tag in ("prime","constant","negative"):
            check("known-generators",lambda:(refs(data,dsl.PRIME if tag == "prime" else dsl.CONST),{"offset_cap":2048}))
        if tag.startswith("symbol") or tag == "negative":
            w = 1 if tag == "symbol8" else 4
            for alg in ("beam","astar"):
                def run():
                    node,ex = search.symbolic(data,w,alg)
                    return (dsl.program([node]) if node is not None else None),dict(expanded=ex,cap=1600)
                check(alg,run)
        if tag in ("xorshift","lfsr"):
            def run():
                model = (program4.XorShiftBytes if tag == "xorshift" else program4.LfsrBytes)()
                for params in model.fit_params(data[:512]):
                    op = dsl.XORSHIFT if tag == "xorshift" else dsl.LFSR
                    wire = dsl.program([dsl.seq(op,len(data),*params)])
                    if dsl.evaluate(wire,len(data)) == data:
                        return wire,dict(parameters=params)
                return None,{}
            check("fit-generative-state",run)
        if tag == "compose":
            check("narrow-composition",lambda:(narrow_composition(data),{}))
        if tag == "patch":
            def run():
                out = search.fit_recurrence(data[:128])
                if not out:
                    return None,{}
                info = out[1]
                node = dsl.recurrence(4,len(data)//4,info["mod"],struct.unpack_from("<2I",data),info["coeff"],info["bias"])
                pred = dsl.evaluate(dsl.program([node]),len(data))
                delta = dsl.xor_bytes(pred,data)
                return dsl.program([node,dsl.lit(delta),dsl.seq(dsl.PATCH,0,1)]),dict(residual_nonzero=sum(x!=0 for x in delta))
            check("short-fit+residual",run)
        rows.append(dict(name=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),reference=methods,
                         candidates=choices,selected=min([baseline["bytes"]]+[r["bytes"] for r in choices.values() if r["found"]])))
        save("families.json",rows)
        print(name,{k: (r.get("bytes"),r.get("meta")) for k,r in choices.items()},flush=True)


if __name__ == "__main__":
    main()
