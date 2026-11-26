"""Fixed catalog independent of all test files. Arb enclosures, no float digits."""
from dataclasses import dataclass,asdict
from functools import lru_cache
from math import isqrt
from pathlib import Path
import sys
import time

import numpy as np

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/".deps"))
from represent import view,BASE

sys.set_int_max_str_digits(0)
LEVELS=(8192,100000,1000000,10000000)
SEEDS=(730109,2765617,8891131)
KINDS=("math","uniform","matched","shuffled")
MAX_SEQ=10_000_000
MASK=(1<<64)-1


@dataclass(frozen=True)
class Generator:
    name: str
    family: str
    enc: str
    params: tuple = ()
    access: str = "prefix"


NODES=(
    *(Generator(name,"constant","radix",par) for name,par in
      (("pi",()),("e",()),("phi",()),("sqrt2",(2,)),("sqrt3",(3,)),("sqrt5",(5,)),
       ("gamma",()),("zeta3",()),("ln2",()))),
    Generator("pi-text","constant","ascii"),
    Generator("prime-le32","number","u4",("prime",)),
    Generator("prime-gap-mod","number","u1",("gap",)),
    Generator("prime-digits","number","digits",("prime",)),
    Generator("composite-le16","number","u2",("composite",)),
    Generator("square-le32","number","u4",("square",),"direct formula; cached in this encoder"),
    Generator("cube-mod","number","u1",("cube",),"direct formula; cached"),
    Generator("triangular-le16","number","u2",("tri",),"direct formula; cached"),
    Generator("choose-n-3","number","u2",("binomial",),"direct formula; cached"),
    Generator("fib-le16","number","u2",(0,1)),
    Generator("lucas-le16","number","u2",(2,1)),
    Generator("totient-le16","number","u2",("phi",)),
    Generator("mobius-offset","number","u1",("mu",)),
    Generator("divisor-count","number","u1",("tau",)),
    Generator("pow3-mod65521","algorithm","u2",(65521,3,0,1),"LCG jump"),
    Generator("lcg32","algorithm","u4",(1<<32,1664525,1013904223,0x9317),"LCG jump"),
    Generator("lcg-prime","algorithm","u4",(2147483647,48271,101,41217),"LCG jump"),
    Generator("xorshift32","algorithm","u4",(0x1f125bb5,)),
    Generator("lfsr16","algorithm","u2",(0xace1,0xb400)),
    Generator("splitmix64-counter","algorithm","u8",(0x9351b267959d3041,),"direct indexed"),
    Generator("gf256-power","number","u1",(3,0x11b)),
    Generator("thue-morse","algorithm","u1",(),"direct parity"),
    Generator("fibonacci-word","algorithm","u1"),
    Generator("debruijn-16","algorithm","u1",(16,)),
    Generator("rule30-center","algorithm","u1",(30,8192)),
    Generator("rudin-shapiro","algorithm","u1",(),"direct parity; cached"),
    Generator("bit-composition","algorithm","u4",(0xaf13ca7,7,0x9e3779b1,0x33ace34f)),
)


def sizes(total):
    if total not in LEVELS: raise ValueError("unknown bank size")
    lengths=[total//len(NODES)+int(i<total%len(NODES)) for i in range(len(NODES))]
    # The gamma, zeta and cellular sources have bounded expensive prefixes.
    count=0
    for i,s in enumerate(NODES):
        cap=16384 if s.name=="rule30-center" else 65536 if s.name in ("gamma","zeta3") else total
        if lengths[i]>cap:
            count+=lengths[i]-cap
            lengths[i]=cap
    choices=[i for i,s in enumerate(NODES) if s.name not in ("gamma","zeta3","rule30-center")]
    for j,i in enumerate(choices):
        lengths[i]+=count//len(choices)+int(j<count%len(choices))
    assert sum(lengths)==total
    return lengths


def decimal_or_power(z,n,base):
    if base==256: return int(z).to_bytes(n,"big")
    if base==10: return str(z).zfill(n).encode().translate(bytes((i-48)&255 for i in range(256)))
    k={2:1,4:2,8:3,16:4}[base]
    d=int(z).to_bytes((n*k+7)//8,"big")
    bits=np.unpackbits(np.frombuffer(d,np.uint8))[-n*k:].reshape(n,k)
    return (bits @ (1<<np.arange(k-1,-1,-1,dtype=np.uint8))).astype(np.uint8).tobytes()


def constant(name,par,n,base):
    """Take a floor only once Arb certifies a unique integer in the enclosure."""
    from flint import arb, ctx, fmpz
    if not 0<n<=MAX_SEQ: raise ValueError("constant range")
    scale=fmpz(base)**n
    bpi=(base-1).bit_length()
    for guard in (96,384,1536,6144):
        with ctx.workprec(n*bpi+guard):
            x=(arb.pi() if name in ("pi","pi-text") else arb(1).exp() if name=="e"
               else (arb(5).sqrt()+1)/2 if name=="phi" else arb(par[0]).sqrt() if par
               else arb.const_euler() if name=="gamma" else arb(3).zeta() if name=="zeta3"
               else arb(2).log())
            val=(x*arb(scale)).floor().unique_fmpz()
        if val is not None:
            return decimal_or_power(val%scale,n,base)
    raise ArithmeticError("constant digit enclosure too wide")


def bbp(start,n):
    """Certified hexadecimal window. Every term is bounded in fixed point."""
    if not 0<=start<=1_000_000 or not 1<=n<=64: raise ValueError("BBP work")
    shift=4*n+96
    q=1<<shift
    low=high=0
    for j,c in ((1,4),(4,-2),(5,-1),(6,-1)):
        l=sum(q*pow(16,start-k,8*k+j)//(8*k+j) for k in range(start+1))
        tail_steps=(shift+3)//4+1
        l+=sum((q>>(4*k))//(8*(start+k)+j) for k in range(1,tail_steps+1))
        h=l+start+1+tail_steps+1
        low+=c*(l if c>0 else h)
        high+=c*(h if c>0 else l)
    a,b=low>>(shift-4*n),high>>(shift-4*n)
    if a!=b: raise ArithmeticError("BBP digit enclosure ambiguous")
    return decimal_or_power(a%(16**n),n,16)


def lcg_jump(seed,steps,m,a,c):
    m0,b=1,0
    while steps:
        if steps&1:
            m0,b=m0*a%m,(b*a+c)%m
        a,c=a*a%m,(a*c+c)%m
        steps>>=1
    return (seed*m0+b)%m


def splitmix_words(seed,start,n):
    x=np.arange(start,start+n,dtype=np.uint64)*np.uint64(0x9e3779b97f4a7c15)+np.uint64(seed)
    x=(x^(x>>30))*np.uint64(0xbf58476d1ce4e5b9)
    x=(x^(x>>27))*np.uint64(0x94d049bb133111eb)
    return x^(x>>31)


def parity(x,shapiro=False):
    if shapiro: x=x&(x>>1)
    for s in (32,16,8,4,2,1): x=x^(x>>s)
    return x&1


@lru_cache(maxsize=5)
def primes_at_least(n):
    # Over-allocation is deliberate; exact sieve and then length check.
    high=max(128,n*(n.bit_length()+6))
    s=np.ones(high+1,dtype=np.bool_); s[:2]=False
    for p in range(2,isqrt(high)+1):
        if s[p]: s[p*p::p]=False
    ps=np.flatnonzero(s)
    if len(ps)<n+1: raise ArithmeticError("prime bound")
    return ps,s


def arith(name,count):
    x=np.arange(count,dtype=np.uint64)
    if name=="square": return x*x
    if name=="cube": return x*x*x
    if name=="tri": return x*(x+1)//2
    if name=="binomial": return x*np.maximum(x,2).__sub__(1)*np.maximum(x,2).__sub__(2)//6
    if name in ("prime","gap","composite"):
        if name=="composite":
            n=2*count+16; c=np.ones(n,dtype=np.bool_); c[:4]=False
            # A convenient direct primality sieve for this finite range.
            t=np.ones(n,dtype=np.bool_); t[:2]=False
            for p in range(2,isqrt(n-1)+1):
                if t[p]: t[p*p::p]=False
            c[t]=False
            return np.flatnonzero(c)[:count]
        ps,_=primes_at_least(count+1)
        return np.diff(ps[:count+1]) if name=="gap" else ps[:count]
    if name=="tau":
        out=np.zeros(count+1,np.uint64)
        for i in range(1,count+1): out[i::i]+=1
        return out[1:]
    if name in ("phi","mu"):
        out=(np.arange(count+1,dtype=np.int64) if name=="phi" else np.ones(count+1,dtype=np.int64))
        sieve=np.ones(count+1,np.bool_)
        for p in range(2,count+1):
            if sieve[p]:
                sieve[p::p]=False
                if name=="phi": out[p::p]-=out[p::p]//p
                else:
                    out[p::p]*=-1
                    if p*p<=count: out[p*p::p]=0
        return out[1:]+int(name=="mu")
    raise ValueError("number family")


@lru_cache(maxsize=1)
def debruijn():
    n=16; a=[0]*(n+1); seq=bytearray()
    def rec(t,p):
        if t>n:
            if n%p==0: seq.extend(a[1:p+1])
            return
        a[t]=a[t-p]; rec(t+1,p)
        for j in range(a[t-p]+1,2):
            a[t]=j; rec(t+1,t)
    rec(1,1)
    return bytes(seq)


def gf(a,b,pol):
    c=0
    while b:
        if b&1: c^=a
        a<<=1
        if a&256: a^=pol
        b>>=1
    return c


def words(spec,n):
    name,p=spec.name,spec.params
    if name in ("thue-morse","rudin-shapiro"):
        return parity(np.arange(n,dtype=np.uint64),name=="rudin-shapiro")
    if name=="splitmix64-counter": return splitmix_words(p[0],0,n)
    if name=="fibonacci-word":
        a,b=b"\0",b"\0\1"
        while len(b)<n: a,b=b,b+a
        return np.frombuffer(b[:n],np.uint8)
    if name=="debruijn-16":
        d=debruijn()
        return np.frombuffer((d*((n+len(d)-1)//len(d)))[:n],np.uint8)
    if name=="rule30-center":
        state=1<<8192
        out=bytearray()
        for _ in range(n):
            out.append((state>>8192)&1)
            state=(state<<1)^(state|(state>>1))
        return np.frombuffer(out,np.uint8)
    if name in ("fib-le16","lucas-le16"):
        a,b=p; out=[]
        for _ in range(n): out.append(a); a,b=b,(a+b)&65535
        return np.asarray(out,np.uint64)
    if spec.family=="number" and name!="gf256-power": return arith(p[0],n)
    if name=="gf256-power":
        out=[]; state=1
        for _ in range(n): out.append(state); state=gf(state,*p)
        return np.asarray(out,np.uint64)
    if name in ("pow3-mod65521","lcg32","lcg-prime"):
        m,a,c,state=p
        out=[]
        for _ in range(n): out.append(state); state=(a*state+c)%m
        return np.asarray(out,np.uint64)
    state=p[0]; out=[]
    for _ in range(n):
        out.append(state)
        if name=="lfsr16": state=(state>>1)^(p[1] if state&1 else 0)
        elif name=="xorshift32":
            state^=(state<<13)&0xffffffff; state^=state>>17; state^=(state<<5)&0xffffffff
        elif name=="bit-composition":
            state=(state*p[2])&0xffffffff
            state=(((state<<p[1])|(state>>(32-p[1])))^p[3])&0xffffffff
        else: raise ValueError("generator")
    return np.asarray(out,np.uint64)


def stream(gid,mode,n):
    if not 0<n<=MAX_SEQ: raise ValueError("stream length")
    s=NODES[gid]; b=BASE[mode]
    if s.family=="constant" and s.enc=="radix": return constant(s.name,s.params,n,b)
    if s.enc in ("ascii","digits"):
        if s.enc=="ascii":
            d=constant(s.name,s.params,n,10)
            d=(np.frombuffer(d,np.uint8)+48).tobytes()
        else:
            x=words(s,n//2+256)
            d="".join(map(str,x)).encode()
        if len(d)<n: raise ValueError("digit prefix")
        if b==10: return (np.frombuffer(d[:n],np.uint8)-48).tobytes()
        ans,_=view(d,mode)
        return ans[:n]
    w=int(s.enc[1])
    # All digit encodings except base256 yield at least one symbol per byte.
    count=n//w+32
    x=words(s,count)
    if len(x)<count: raise ValueError("word prefix")
    raw=x.astype("<u"+str(w)).tobytes()
    ans,_=view(raw,mode)
    if len(ans)<n: raise ValueError("representation prefix")
    return ans[:n]


def direct(gid,mode,start,n,banklen):
    if not 0<=start or n<1 or start+n>banklen: raise ValueError("reference bounds")
    s=NODES[gid]; p=s.params
    if mode=="bytes" and s.name=="splitmix64-counter":
        return splitmix_words(p[0],start//8,(start%8+n+7)//8).astype("<u8").tobytes()[start%8:start%8+n]
    if mode=="bytes" and s.access=="LCG jump":
        m,a,c,seed=p
        w=int(s.enc[1])
        begin=start//w
        state=lcg_jump(seed,begin,m,a,c)
        out=bytearray()
        for _ in range((start%w+n+w-1)//w):
            out+=(state%(1<<(8*w))).to_bytes(w,"little")
            state=(a*state+c)%m
        return bytes(out[start%w:start%w+n])
    if mode=="bytes" and s.name=="thue-morse":
        return parity(np.arange(start,start+n,dtype=np.uint64)).astype(np.uint8).tobytes()
    # BBP deliberately kept separate: cheaper for sparse nearby hex windows,
    # not a universal high-throughput decoder for deep addresses.
    return None


def generate(mode,total,kind="math",seed=0,base_series=None):
    lengths=sizes(total)
    start=time.perf_counter()
    all_data=[]
    profile=[]
    for i,(g,n) in enumerate(zip(NODES,lengths)):
        t=time.perf_counter()
        if kind=="math":
            d=stream(i,mode,n)
        else:
            rng=np.random.Generator(np.random.PCG64(SEEDS[seed]+100003*i))
            if kind=="uniform":
                d=rng.integers(0,BASE[mode],n,dtype=np.uint8).tobytes()
            else:
                raw=(base_series[i] if base_series is not None else stream(i,mode,n))
                a=np.frombuffer(raw,np.uint8)
                if kind=="shuffled":
                    d=rng.permutation(a).tobytes()
                elif kind=="matched":
                    c=np.bincount(a,minlength=BASE[mode]).cumsum()
                    d=c.searchsorted(rng.integers(0,n,n,dtype=np.int64),"right").astype(np.uint8).tobytes()
                else: raise ValueError("bank kind")
        if len(d)!=n: raise ValueError("catalog quota")
        all_data.append(d)
        profile.append(dict(gid=i,name=g.name,symbols=n,seconds=time.perf_counter()-t))
    return all_data,dict(seconds=time.perf_counter()-start,sources=profile,stored_bytes=total)


def manifest():
    return [dict(gid=i,**asdict(g),description="deterministic prefix; parameters fixed, not fitted")
            for i,g in enumerate(NODES)]
