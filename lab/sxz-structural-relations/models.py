"""Matched nonlocal reference, differential and parametric predictors."""
import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np
import zstandard

from dsl import Reader, seq, v

LIT, REF, XOR, SUB, EDIT, PXOR, PSUB, PEDIT = range(8)
AFF, NUM, TILE, FEXP, LANES = range(5)
TOKEN = re.compile(rb"[A-Za-z0-9_]+|[ \t\r\n]+|[^ A-Za-z0-9_\t\r\n]")
NUMERIC = re.compile(rb"(?<![0-9])[0-9]{1,9}(?![0-9])")
Z = zstandard.ZstdCompressor(level=3,write_checksum=True)
CAP = 2 << 20


def plane(d,w,inv=False):
    if w==1 or not d:
        return d
    if w==5 and len(d)%4==0:  # conventional FP32 field alignment comparator only
        if not inv:
            a=np.frombuffer(d,"<u4")
            return b"".join(x.astype(np.uint8).tobytes() for x in
               (a, a>>8, ((a>>16)&127)|((a>>24)&128), a>>23))
        b,c,ms,e = np.frombuffer(d,np.uint8).reshape(4,-1).astype("<u4")
        return (b | (c<<8) | ((ms&127)<<16) | (e<<23) | ((ms&128)<<24)).astype("<u4").tobytes()
    if w not in (2,4,8) or len(d)%w:
        raise ValueError("plane width")
    a = np.frombuffer(d,np.uint8)
    return (a.reshape(w,-1) if inv else a.reshape(-1,w)).T.tobytes()


def delta(a,b,mode,inv=False):
    if len(a)!=len(b):
        raise ValueError("delta length")
    x = np.frombuffer(a,np.uint8)
    y = np.frombuffer(b,np.uint8)
    if mode==XOR:
        return (x^y).tobytes()
    return (y+x if inv else y-x).tobytes()


def zs(d):
    return len(Z.compress(d)) if d else 0


def vs(k):
    return (-k*2-1) if k<0 else k*2


def sv(k):
    return -((k+1)//2) if k&1 else k//2


def decimal(d,k):
    def repl(m):
        n = int(m[0])+k
        return (f"{n:0{len(m[0])}d}".encode() if 0<=n<10**9 else m[0])
    if len(d)>CAP:
        raise ValueError("decimal limit")
    return NUMERIC.sub(repl,d)


def predict(base,args):
    r = Reader(args)
    op = r.get()
    if op==AFF:
        a,b = r.get(),r.get()
        if a not in (1,3,5,255) or b>255:
            raise ValueError("affine domain")
        d = (np.frombuffer(base,np.uint8)*a+b).tobytes()
    elif op==NUM:
        k = sv(r.get())
        if not -10**8 <= k <= 10**8:
            raise ValueError("decimal shift")
        d = decimal(base,k)
    elif op==TILE:
        h,w,m,x,y = (r.get() for _ in range(5))
        x,y = sv(x),sv(y)
        if not (1<=h<=16 and 1<=w<=16 and len(base)==h*w and m<=7 and abs(x)<=1 and abs(y)<=1):
            raise ValueError("tile map")
        mat = np.frombuffer(base,np.uint8).reshape(h,w)
        if m&4:
            if h!=w:
                raise ValueError("transpose requires square tile")
            mat = mat.T
        if m&1:
            mat = mat[:,::-1]
        if m&2:
            mat = mat[::-1,:]
        if x or y:
            mat = np.roll(mat,(y,x),axis=(0,1))
        d = mat.tobytes()
    elif op==FEXP:
        k,s = sv(r.get()),r.get()
        if abs(k)>7 or s>1 or len(base)%4:
            raise ValueError("float field map")
        x = np.frombuffer(base,"<u4")
        e = ((x>>23)+(k+256)) & 255
        d = (((x & 0x807fffff)^(s<<31)) | (e<<23)).astype("<u4").tobytes()
    elif op==LANES:
        c = tuple(r.get() for _ in range(3))
        if len(base)%12 or any(k>=1<<32 for k in c):
            raise ValueError("lane offsets")
        d = (np.frombuffer(base,"<u4").reshape(-1,3)+np.array(c,dtype="<u4")).tobytes()
    else:
        raise ValueError("unknown transform")
    r.finish()
    return d


def toks(x,text):
    return TOKEN.findall(x) if text else [x[i:i+4] for i in range(0,len(x),4)]


def copy_delta(x,y,text):
    if max(len(x),len(y))>8192:
        return None
    u,w = toks(x,text),toks(y,text)
    if max(len(u),len(w))>1024:
        return None
    off=[0]
    new=[0]
    for a in u:
        off.append(off[-1]+len(a))
    for a in w:
        new.append(new[-1]+len(a))
    blocks=difflib.SequenceMatcher(None,u,w,autojunk=True).get_matching_blocks()
    result=bytearray()
    pos=0
    for a,b,n in blocks:
        s,t = new[b],new[b+n]
        if n and t-s<6:
            continue
        if s>pos:
            result += seq(0,s-pos)+y[pos:s]
        if n:
            result += seq(1,off[a],t-s)
        pos=t
    return bytes(result) if len(result)<len(y) else None


def apply_copy(x,residue,n):
    r = Reader(residue)
    out = bytearray()
    while r.at<len(residue):
        op = r.get()
        if op==0:
            size = r.get()
            if size>n-len(out):
                raise ValueError("insertion size")
            out += r.take(size)
        elif op==1:
            a,size = r.get(),r.get()
            if a+size>len(x) or size>n-len(out):
                raise ValueError("copy bounds")
            out += x[a:a+size]
        else:
            raise ValueError("copy opcode")
    if len(out)!=n:
        raise ValueError("copy size")
    return bytes(out)


@dataclass
class Model:
    op: int
    width: int
    raw_length: int
    payload: bytes
    back: int = 0
    params: bytes = b""
    est: int = 0

    def description(self):
        return seq(self.op,self.width,self.raw_length,len(self.payload),self.back,len(self.params))+self.params

    def price(self):
        return len(self.description())+zs(self.payload)


def signature(r):
    d = r.data
    if r.group[0] in ("xml","pdf-dict","pdf-text"):
        sample = toks(d[:2048],True)
        return set(zip(sample,sample[1:]))
    if r.hw:
        a = np.frombuffer(d,np.uint8)
        h = np.bincount(a>>4,minlength=16).astype(np.int32)
        return h
    n = max(1,len(d)//128)
    return np.frombuffer(d[::n][:128],np.uint8)


def distance(r,s,raw,ref):
    if isinstance(r,set):
        return -len(r&s)/max(1,len(r|s))+0.12*abs(len(raw)-len(ref))/max(len(raw),len(ref))
    n = min(len(r),len(s))
    a,b = r[:n],s[:n]
    if r.dtype==np.int32:
        return int(np.sum(np.abs(a-b)))
    return -int(np.count_nonzero(a==b))


def top_parents(history,rec,sig,records):
    # Keep coverage of non-neighbours: candidates may come from both ends and
    # regular sample of the whole prior bucket, not a byte-distance window.
    if len(history)>96:
        stride=max(1,len(history)//64)
        # Sampling the entire bucket and adding the tail can overlap; do not
        # spend two shortlist slots on the same parent.
        history = list(dict(history[::stride]+history[-16:]).items())
    pool = [(distance(sig,s,rec.data,records[j].data),j) for j,s in history
            if max(len(rec.data),len(records[j].data))<=CAP
            and (min(len(rec.data),len(records[j].data))*2>=max(len(rec.data),len(records[j].data)))]
    pool.sort(key=lambda x:(x[0],-x[1]))
    answer = [j for _,j in pool[:4]]
    if pool and pool[-1][0]!=pool[0][0]:
        recent = max(j for _,j in pool)
        if recent not in answer:
            answer.append(recent)
    return answer


def transforms(base,target,rec):
    res = []
    if rec.group[0] in ("xml","pdf-dict","pdf-text"):
        ax = [int(m[0]) for m in NUMERIC.finditer(base[:4096])][:96]
        ay = [int(m[0]) for m in NUMERIC.finditer(target[:4096])][:96]
        counts = Counter(y-x for x,y in zip(ax,ay) if 0<abs(y-x)<=10**8)
        for k,n in counts.most_common(2):
            if n>=2:
                res.append(seq(NUM,vs(k)))
    if len(base)!=len(target):
        return res
    if rec.hw or rec.group[0]=="tensor":
        step = max(1,len(base)//256)
        ax = np.frombuffer(base[::step],np.uint8)
        ay = np.frombuffer(target[::step],np.uint8)
        for c in (1,255,3,5):
            h = np.bincount(ay-ax*c,minlength=256)
            k = int(h.argmax())
            if int(h[k])*6>=len(ax) and (c!=1 or k):
                res.append(seq(AFF,c,k))
    if rec.hw:
        h,w = rec.hw
        res += [seq(TILE,h,w,k,0,0) for k in range(1,8 if h==w else 4)]
        res += [seq(TILE,h,w,0,vs(x),vs(y)) for x,y in ((-1,0),(1,0),(0,-1),(0,1))]
    if rec.group[:2]==("tensor",1):
        a = np.frombuffer(base,"<u4")
        b = np.frombuffer(target,"<u4")
        p = max(1,len(a)//256)
        a,b=a[::p],b[::p]
        e = (((b>>23)&255).astype(np.int16)-((a>>23)&255).astype(np.int16))
        k,count = Counter(map(int,e)).most_common(1)[0]
        t = int(np.count_nonzero((a^b)&0x80000000)*2>len(a))
        if abs(k)<=7 and (k or t):
            res.append(seq(FEXP,vs(k),t))
    if rec.group[0]=="pe-pdata":
        a = np.frombuffer(base,"<u4").reshape(-1,3)
        b = np.frombuffer(target,"<u4").reshape(-1,3)
        dif = (b-a).T
        ds = tuple(Counter(map(int,x)).most_common(1)[0][0] for x in dif)
        if any(ds):
            res.append(seq(LANES,*ds))
    return res


def choose(records,only_baseline=False):
    """One search pass; apart from parametric candidates, exactly the same parent pool."""
    hist = defaultdict(list)
    earlier_exact={}
    choices={k:[] for k in ("plain","dedup","diff","math","math-margin")}
    audit=[]
    for i,r in enumerate(records):
        value = r.data
        plain = Model(LIT,r.width,len(value),plane(value,r.width))
        p0 = pd = pm = plain
        prices = {}
        capable = bool(r.group) and 16<=len(value)<=CAP
        pool=[]
        legal=0
        if capable:
            k = (r.group,value)
            if (e:=earlier_exact.get(k)) is not None:
                p0 = Model(REF,r.width,len(value),b"",i-e)
                pd = pm = p0
            earlier_exact[k] = i
            sig = signature(r)
            pool=top_parents(hist[r.group],r,sig,records)
            hist[r.group].append((i,sig))

        def cost(obj):
            idx=id(obj)
            if idx not in prices:
                prices[idx]=(obj,obj.price())
            return prices[idx][1]

        def register(op,d,j,param=b""):
            nonlocal pd,pm,legal
            if d is None:
                return
            legal+=1
            use_w=r.width if op in (XOR,SUB,PXOR,PSUB) else 1
            q=Model(op,use_w,len(value),plane(d,use_w),i-j,param)
            if op in (XOR,SUB,EDIT) and cost(q)<cost(pd):
                pd=q
            if cost(q)<cost(pm):
                pm=q

        if p0 is plain:
            text=bool(r.group and r.group[0] in ("xml","pdf-text","pdf-dict"))
            for j in pool:
                base=records[j].data
                if len(base)==len(value):
                    for mode in (XOR,SUB):
                        register(mode,delta(base,value,mode),j)
                if text or (r.group and r.group[0]=="pe-func"):
                    register(EDIT,copy_delta(base,value,text),j)
            if not only_baseline:
                # Rank the transforms by an exact near-local compressed
                # residual for each parent; the global paired test follows.
                for j in pool:
                    base=records[j].data
                    for params in transforms(base,value,r):
                        b=predict(base,params)
                        if b==base:
                            continue
                        if len(b)==len(value):
                            register(PXOR,delta(b,value,XOR),j,params)
                            register(PSUB,delta(b,value,SUB),j,params)
                        if params[0]==NUM:
                            register(PEDIT,copy_delta(b,value,True),j,params)
        for name,q in (("plain",plain),("dedup",p0),("diff",pd),("math",pm)):
            choices[name].append(q)
        gain = cost(pd)-cost(pm) if pm is not pd else 0
        choices["math-margin"].append(pm if gain>=8 else pd)
        if capable:
            a=dict(record=i,group=list(map(str,r.group)),position=r.position,n=len(value),pool=pool,
                   conventional=pd.op,selected=pm.op,trial_count=legal)
            if pm.op in (PXOR,PSUB,PEDIT):
                a.update(back=pm.back,parameters_hex=pm.params.hex(),residual_raw=len(pm.payload),
                         local_gain=gain,description_raw=len(pm.description()))
            audit.append(a)
    return choices,audit
