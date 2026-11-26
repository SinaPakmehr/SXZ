"""Reversible digit views. Unrepresented short tails stay byte literals."""
import numpy as np

MODES=("bytes","b2","b4","b8","b16","dec3","dec20","decvar")
BASE={"bytes":256,"b2":2,"b4":4,"b8":8,"b16":16,"dec3":10,"dec20":10,"decvar":10}
K={2:24,4:12,8:8,10:8,16:6,256:3}
# Input bytes and output symbols per complete unit.
UNITS={"bytes":(1,1),"b2":(1,8),"b4":(1,4),"b8":(3,8),"b16":(1,2),
       "dec3":(1,3),"dec20":(8,20),"decvar":(8,0)}


def view(data,mode):
    if mode=="bytes":
        return data,None
    a=np.frombuffer(data,np.uint8)
    if mode=="b2":
        return np.unpackbits(a).tobytes(),None
    if mode in ("b4","b16"):
        k=2 if mode=="b4" else 4
        return ((a[:,None]>>np.arange(8-k,-1,-k,dtype=np.uint8))&((1<<k)-1)).tobytes(),None
    if mode=="b8":
        b=a[:len(a)//3*3].astype(np.uint32).reshape(-1,3)
        x=b[:,0]*65536+b[:,1]*256+b[:,2]
        return ((x[:,None]>>np.arange(21,-1,-3,dtype=np.uint32))&7).astype(np.uint8).tobytes(),None
    if mode=="dec3":
        return np.column_stack((a//100,(a//10)%10,a%10)).astype(np.uint8).tobytes(),None
    x=np.frombuffer(data[:len(data)//8*8],">u8").astype(np.uint64)
    n=len(x)
    out=np.empty((n,20),np.uint8)
    for j in range(19,-1,-1):
        out[:,j]=x%10
        x//=10
    if mode=="dec20":
        return out.tobytes(),None
    if mode!="decvar":
        raise ValueError("representation")
    mask=np.maximum.accumulate(out!=0,axis=1)
    mask[:,-1]=True
    offsets=np.empty(n+1,np.int64); offsets[0]=0
    np.cumsum(mask.sum(axis=1),out=offsets[1:])
    return out[mask].tobytes(),offsets


def project(mode,offsets,a,length):
    """Return byte start/end, number of symbols dropped front, kept, widths."""
    b=a+length
    nb,ns=UNITS[mode]
    if ns:
        lo=(a+ns-1)//ns
        hi=b//ns
        if hi<=lo:
            return None
        return lo*nb,hi*nb,lo*ns-a,(hi-lo)*ns,b""
    lo=int(offsets.searchsorted(a,"left"))
    hi=int(offsets.searchsorted(b,"right"))-1
    if hi<=lo:
        return None
    widths=np.diff(offsets[lo:hi+1]).astype(np.uint8).tobytes()
    return lo*nb,hi*nb,int(offsets[lo])-a,int(offsets[hi]-offsets[lo]),widths


def revert(symbols,mode,widths=b""):
    if mode=="bytes":
        return symbols
    a=np.frombuffer(symbols,np.uint8)
    if mode=="b2":
        if len(a)%8 or (a>1).any(): raise ValueError("bits")
        return np.packbits(a).tobytes()
    if mode in ("b4","b8","b16"):
        k={"b4":2,"b8":3,"b16":4}[mode]
        w=UNITS[mode][1]
        if len(a)%w or (a>=1<<k).any(): raise ValueError("digit")
        value=np.sum(a.reshape(-1,w).astype(np.uint32)<<np.arange(k*(w-1),-1,-k,dtype=np.uint32),
                     axis=1,dtype=np.uint32)
        if mode=="b8":
            return np.column_stack((value>>16,value>>8,value)).astype(np.uint8).tobytes()
        return value.astype(np.uint8).tobytes()
    if (a>9).any(): raise ValueError("decimal digit")
    if mode=="dec3":
        p=a.astype(np.uint16).reshape(-1,3)
        v=p[:,0]*100+p[:,1]*10+p[:,2]
        if (v>255).any(): raise ValueError("decimal byte range")
        return v.astype(np.uint8).tobytes()
    widths=widths or (b"\x14"*(len(a)//20) if mode=="dec20" else b"")
    if sum(widths)!=len(a) or any(not 1<=w<=20 for w in widths):
        raise ValueError("decimal block widths")
    d=(a+48).tobytes()
    out=bytearray()
    p=0
    for w in widths:
        x=int(d[p:p+w])
        if x>=1<<64: raise ValueError("decimal block range")
        out+=x.to_bytes(8,"big")
        p+=w
    return bytes(out)
