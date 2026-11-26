"""Finite structure induction; all complete candidates have an actual wire."""
import heapq
import itertools
import math
import re
import struct
from collections import Counter

import numpy as np
import zstandard

import dsl
from dsl import (ADD, CAT, EXPR, GFMUL, MUL, PATCH, ROL, SLICE, SPATIAL, XOR, lit,
                 operation, program, recurrence, seq, spatial, xor_bytes)

Z = zstandard.ZstdCompressor(level=3)
TOK = re.compile(rb"[A-Za-z_0-9]+|[ \t\r\n]+|[^A-Za-z_0-9 \t\r\n]")
FIXED_SPATIAL = ((1,0,0,0),(0,1,0,0),(1,1,255,0))


def local_size(wire):
    return len(Z.compress(wire))


def grammar_nodes(data, rounds=24, offset=0):
    """Bounded Re-Pair-like induction over byte-preserving lexical tokens."""
    if len(data) < 512 or len(data) > 800000:
        return None
    words = TOK.findall(data)
    if len(words) < 64 or len(words) > 200000:
        return None
    tokens = {}
    ids = [tokens.setdefault(token,len(tokens)) for token in words]
    text = list(tokens)
    sizes = list(map(len,text))
    rules = {}
    for _ in range(rounds):
        freq = Counter(zip(ids,ids[1:]))
        viable = [(pair,count) for pair,count in freq.items()
                  if count >= 4 and 6 <= sizes[pair[0]]+sizes[pair[1]] <= 65536]
        if not viable:
            break
        pair, _ = max(viable,key=lambda item: ((sizes[item[0][0]]+sizes[item[0][1]]-3)*(item[1]-1),item[1]))
        a,b = pair
        k = len(sizes)
        out, i, count = [], 0, 0
        while i < len(ids):
            if i+1 < len(ids) and ids[i] == a and ids[i+1] == b:
                out.append(k)
                i += 2
                count += 1
            else:
                out.append(ids[i])
                i += 1
        if count < 4:
            break
        sizes.append(sizes[a]+sizes[b])
        rules[k] = pair
        ids = out
    if not rules:
        return None
    nodes, memo = [], {}

    def add(key):
        if key not in memo:
            body = seq(CAT,2,*(add(k) for k in rules[key])) if key in rules else lit(text[key])
            memo[key] = offset+len(nodes)
            nodes.append(body)
        return memo[key]

    pending, order = bytearray(), []
    for key in ids:
        if key not in rules:
            pending += text[key]
            continue
        if pending:
            order.append(offset+len(nodes))
            nodes.append(lit(bytes(pending)))
            pending.clear()
        order.append(add(key))
    if pending:
        order.append(offset+len(nodes))
        nodes.append(lit(bytes(pending)))
    if len(nodes) >= dsl.NODES or len(order) > dsl.NODES:
        return None
    nodes.append(seq(CAT,len(order),*order))
    return nodes,len(rules)


def grammar(data, rounds=24):
    ans = grammar_nodes(data,rounds)
    if ans is not None:
        return program(ans[0]),ans[1]
    if not 131072 < len(data) <= 800000:
        return None
    nodes,roots,rules = [],[],0
    for i in range(0,len(data),131072):
        s = data[i:i+131072]
        p = grammar_nodes(s,rounds,len(nodes))
        if p is None:
            nodes.append(lit(s))
        else:
            nodes.extend(p[0])
            rules += p[1]
        roots.append(len(nodes)-1)
    if not rules or len(nodes) >= dsl.NODES:
        return None
    nodes.append(seq(CAT,len(roots),*roots))
    return program(nodes),rules


def bytes_graph(data,hits):
    nodes, cursor = [], 0
    for pos,n,a,b,c,x,y in hits:
        if pos < cursor:
            raise ValueError("overlapping hits")
        if pos > cursor:
            nodes.append(lit(data[cursor:pos]))
        nodes.append(recurrence(4,n//4,1<<32,(x,y),(a,b),c))
        cursor = pos+n
    if cursor < len(data):
        nodes.append(lit(data[cursor:]))
    refs = list(range(len(nodes)))
    if len(refs) > 1:
        nodes.append(seq(CAT,len(refs),*refs))
    return program(nodes)


def tensor(data, block=4096):
    """Within a byte-plane, try previous one/two physical blocks + XOR."""
    if not 2*block <= len(data) <= 2 << 20:
        return None
    nodes, roots, selected = [], [], 0
    chunks = [data[i:i+block] for i in range(0,len(data),block)]
    for i, chunk in enumerate(chunks):
        original = lit(chunk)
        best = (local_size(original),None,None)
        for prev in range(max(0,i-2),i):
            if len(chunks[prev]) != len(chunk):
                continue
            residue = lit(xor_bytes(chunk,chunks[prev]))
            size = local_size(residue)+len(seq(PATCH,roots[prev],len(nodes)))
            if size < best[0]:
                best = size,prev,residue
        _,prev,residue = best
        if prev is not None:
            a = len(nodes)
            nodes.extend((residue,seq(PATCH,roots[prev],a)))
            selected += 1
        else:
            nodes.append(original)
        roots.append(len(nodes)-1)
    if not selected:
        return None
    nodes.append(seq(CAT,len(roots),*roots))
    return program(nodes), selected


def spatial_candidate(data,w,h,coef):
    residue = spatial(data,w,h,*coef,False)
    return program([lit(residue),seq(SPATIAL,0,w,h,*coef)])


def spatial_search(data,w,h,learn):
    if min(w,h) < 4 or len(data) > 2 << 20:
        return None
    params = list(FIXED_SPATIAL)
    if learn:
        # Fit on a strided sample; validate whole-plane serialized cost.
        mat = np.frombuffer(data,np.uint8).reshape(h,w).astype(np.int32)
        x = mat[1:,1:].ravel()[::17]
        left,up,corner = (a.ravel()[::17] for a in (mat[1:,:-1],mat[:-1,1:],mat[:-1,:-1]))
        rank = []
        for a,b,c in itertools.product((-1,0,1,2),repeat=3):
            e = (x-a*left-b*up-c*corner) & 255
            hist = np.bincount(e,minlength=256)
            d = int(np.argmax(hist))
            freq = hist[hist>0] / len(x)
            cost = float(-np.sum(freq*np.log2(freq)))
            rank.append((cost,(a & 255,b & 255,c & 255,d)))
        params.extend(p for _,p in sorted(rank)[:6])
    candidates = [(spatial_candidate(data,w,h,coef),coef) for coef in dict.fromkeys(params)]
    return min(candidates,key=lambda q: local_size(q[0]))


def spatial_tree(data,w,h,learn):
    """Balanced region grammar: stop, or split into two independently fitted bands."""
    if min(w,h) < 8 or len(data) > 2 << 20:
        return None

    def emission(tree,nodes):
        if len(tree) == 4:
            residual,a,b,p = tree
            j = len(nodes)
            nodes.append(lit(residual))
            if p is not None:
                nodes.append(seq(SPATIAL,j,a,b,*p))
        else:
            j = emission(tree[0],nodes)
            k = emission(tree[1],nodes)
            nodes.append(seq(CAT,2,j,k))
        return len(nodes)-1

    def encode(tree):
        nodes = []
        emission(tree,nodes)
        return program(nodes)

    def visit(chunk,n,depth):
        best = (chunk,w,n,None)
        cost = local_size(encode(best))
        model,co = spatial_search(chunk,w,n,learn)
        if local_size(model) < cost:
            best = (spatial(chunk,w,n,*co,False),w,n,co)
            cost = local_size(model)
        if depth and n >= 24:
            m = n//2
            split = (visit(chunk[:m*w],m,depth-1),visit(chunk[m*w:],n-m,depth-1))
            if local_size(encode(split)) < cost:
                return split
        return best

    tree = visit(data,h,3)
    params = []

    def records(t):
        if len(t) == 4:
            params.append([t[2],t[3]])
        else:
            for f in t:
                records(f)
    records(tree)
    return encode(tree),params


def solve(rows, n, modulus):
    """Unit-pivot elimination: complete over primes, partial over rings."""
    a = [[x%modulus for x in row] for row in rows]
    for j in range(n):
        idx = next((idx for idx in range(j,len(a)) if math.gcd(a[idx][j],modulus)==1),None)
        if idx is None:
            return None
        a[j],a[idx] = a[idx],a[j]
        inv = pow(a[j][j],-1,modulus)
        a[j] = [x*inv%modulus for x in a[j]]
        for k,row in enumerate(a):
            if k != j:
                a[k] = [(x-row[j]*y)%modulus for x,y in zip(row,a[j])]
    if any(row[-1] for row in a[n:]):
        return None
    return tuple(row[-1] for row in a[:n])


def fit_recurrence(data, width=4, moduli=None, orders=(1,2,3,4)):
    if width not in (1,2,4,8) or len(data)%width:
        return None
    code = {1:"B",2:"H",4:"I",8:"Q"}[width]
    words = tuple(x[0] for x in struct.iter_unpack("<"+code,data))
    head = words[:64]
    if not head:
        return None
    if moduli is None:
        d = [y-x for x,y in zip(head,head[1:])]
        g = math.gcd(*(a*c-b*b for a,b,c in zip(d,d[1:],d[2:])))
        moduli = dict.fromkeys([1 << (8*width)]+[g//i for i in range(1,33) if g % i == 0])
    for k in orders:
        if len(head) < 2*k+4:
            continue
        for mod in moduli:
            if not max(head) < mod <= 1 << (8*width) or not mod > 1:
                continue
            rows = [(*reversed(head[i-k:i]),1,head[i]) for i in range(k,min(len(head),2*k+5))]
            s = solve(rows,k+1,mod)
            if s is None:
                continue
            co,bias = s[:-1],s[-1]
            if all((bias+sum(c*words[i-1-j] for j,c in enumerate(co))) % mod == words[i]
                   for i in range(k,len(words))):
                return recurrence(width,len(words),mod,words[:k],co,bias), dict(order=k,mod=mod,coeff=co,bias=bias)
    return None


def symbolic(data,width,method,limit=1600,beam_width=8):
    """Best-first (A* h=0) vs beam over prefix operators + an inferred last op.

    Queue cost lower-bounds the wire bytes of any completion of the prefix.
    Both stop at a hard expansion cap; exactness is tested over every word.
    """
    exprs = [(MUL,p) for p in (3,5,17,31,0x9e3779b1) if p < 1 << (8*width)]
    exprs += [(ROL,p) for p in (1,3,5,7,9,11,13,17) if p < 8*width]
    if width == 1:
        exprs += [(GFMUL,p) for p in (2,3,7,13,29)]
    words = [int.from_bytes(data[i:i+width],"little") for i in range(0,len(data),width)]
    if len(words) < 17 or len(data)%width:
        return None,0
    xs, ys = words[:16], words[1:17]
    bits = 8*width

    def inferred(pred):
        mask = (1 << bits)-1
        a = Counter((y-x)&mask for x,y in zip(pred,ys)).most_common(1)[0]
        b = Counter(y^x for x,y in zip(pred,ys)).most_common(1)[0]
        return [(a[1],ADD,a[0]),(b[1],XOR,b[0])]

    def wire(ops):
        instructions = [8,0]
        for op,p in ops:
            instructions.extend((9,p,op,0))
        return seq(EXPR,width,len(words),1 << bits,1,words[0],len(instructions)//2,*instructions)

    agenda = [(0,(),xs)]
    expansions = 0
    solution = None
    while agenda and expansions < limit:
        score,ops,pred = heapq.heappop(agenda)
        if method == "astar" and solution is not None and score > len(solution):
            break
        expansions += 1
        for hits,op,p in inferred(pred):
            if hits == len(xs):
                cand = wire((*ops,(op,p)))
                if (solution is None or len(cand) < len(solution)) and dsl.evaluate(program([cand]),len(data)) == data:
                    solution = cand
        if len(ops) < 2:
            for op,p in exprs:
                next_ops = (*ops,(op,p))
                values = [operation(x,p,op,bits) for x in pred]
                key = (len(wire((*next_ops,(ADD,0)))) if method == "astar"
                       else -max(x[0] for x in inferred(values)))
                heapq.heappush(agenda,(key,next_ops,values))
        if method == "beam" and len(agenda) > beam_width:
            agenda = heapq.nsmallest(beam_width,agenda)
            heapq.heapify(agenda)
    return solution,expansions
