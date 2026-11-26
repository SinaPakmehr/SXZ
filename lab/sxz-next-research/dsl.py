"""Bounded, topological byte-program wire format; no executable input."""
import math
import struct

import numpy as np

from accelerate import NATIVE, create_string_buffer, output

LIMIT = 16 << 20
WORK = 64 << 20
NODES = 65536
LIT, CAT, REP, SLICE, MAP, PERM, REC, PATCH, EXPR, PRIME, CONST, LFSR, XORSHIFT = range(13)
SPATIAL = 13
ADD, MUL, XOR, SHL, SHR, ROL, MOD, GFMUL = range(8)


def v(n):
    if not 0 <= n < 1 << 65:
        raise ValueError("integer outside wire domain")
    out = bytearray()
    while n >= 128:
        out.append((n & 127) | 128)
        n >>= 7
    out.append(n)
    return bytes(out)


def seq(*n):
    return b"".join(map(v, n))


def lit(s):
    return seq(LIT, len(s)) + s


def program(nodes):
    return v(len(nodes)) + b"".join(nodes)


def recurrence(width, n, mod, seed, coefficients, bias):
    return seq(REC, width, n, mod, len(seed), *seed, *coefficients, bias)


def xor_bytes(x, y):
    if len(x) != len(y):
        raise ValueError("residual length")
    return np.bitwise_xor(np.frombuffer(x, np.uint8), np.frombuffer(y, np.uint8)).tobytes()


def spatial(data, w, h, a, b, c, d, invert):
    if not w or not h or w*h != len(data) or max(a,b,c,d) > 255:
        raise ValueError("spatial domain")
    if NATIVE:
        buf = create_string_buffer(len(data))
        NATIVE.spatial(data, buf, w,h,a,b,c,d,invert)
        return buf.raw
    out = bytearray(len(data))
    hist = out if invert else data
    for i, x in enumerate(data):
        left = hist[i-1] if i % w else 0
        up = hist[i-w] if i >= w else 0
        corner = hist[i-w-1] if i >= w and i % w else 0
        pred = a*left+b*up+c*corner+d
        out[i] = (x+pred if invert else x-pred) & 255
    return bytes(out)


class Reader:
    def __init__(self, data):
        self.data = memoryview(data)
        self.at = 0

    def get(self):
        value = 0
        for shift in range(0, 65, 7):
            if self.at >= len(self.data):
                raise ValueError("truncated integer")
            b = self.data[self.at]
            self.at += 1
            value |= (b & 127) << shift
            if b < 128 and value < 1 << 65:
                return value
        raise ValueError("overlong integer")

    def take(self, n):
        end = self.at + n
        if end > len(self.data):
            raise ValueError("truncated bytes")
        b = self.data[self.at:end]
        self.at = end
        return b

    def finish(self):
        if self.at != len(self.data):
            raise ValueError("trailing bytes")


def gf_mul(x, y):
    z = 0
    while y:
        if y & 1:
            z ^= x
        y >>= 1
        x <<= 1
        if x & 256:
            x ^= 0x11b
    return z


def operation(x, y, op, bits):
    mask = (1 << bits)-1
    if op == ADD:
        return (x+y) & mask
    if op == MUL:
        return (x*y) & mask
    if op == XOR:
        return x ^ y
    if op == SHL:
        return (x << (y % bits)) & mask
    if op == SHR:
        return x >> (y % bits)
    if op == ROL:
        r = y % bits
        return ((x << r) | (x >> (bits-r))) & mask
    if op == MOD and y:
        return x % y
    if op == GFMUL and bits == 8:
        return gf_mul(x, y)
    raise ValueError("invalid arithmetic")


def prime_data(start, count, gaps):
    if start + count > 80000:
        raise ValueError("prime index cap")
    if count == 0:
        return b""
    n = start + count + bool(gaps)
    hi = max(16, int(n * (math.log(max(n, 2)) + math.log(math.log(max(n, 3))))) + 16)
    sieve = bytearray(b"\1")*(hi+1)
    sieve[:2] = b"\0\0"
    for p in range(2, math.isqrt(hi)+1):
        if sieve[p]:
            sieve[p*p::p] = b"\0" * ((hi-p*p)//p+1)
    primes = [i for i, mark in enumerate(sieve) if mark][start:n]
    if gaps:
        primes = [b-a for a,b in zip(primes, primes[1:])]
    if len(primes) != count:
        raise ValueError("prime bound")
    return struct.pack(f"<{count}I", *primes)


def constant_data(which, start, count):
    if start + count > 8192 or which > 2:
        raise ValueError("constant digit cap")
    from mpmath import mp
    ctx = mp.clone()
    ctx.dps = start + count + 32
    text = ctx.nstr((ctx.pi, ctx.e, ctx.phi)[which], ctx.dps-2).split(".")[1]
    return text[start:start+count].encode("ascii")


def evaluate(wire, expected=None, shared=None):
    if len(wire) > LIMIT:
        raise ValueError("program too long")
    r = Reader(wire)
    count = r.get()
    if not 1 <= count <= NODES:
        raise ValueError("node limit")
    built = []
    budget = WORK

    def charge(n):
        nonlocal budget
        if n > LIMIT or n > budget:
            raise ValueError("program resource limit")
        budget -= n
        if shared is not None:
            shared[0] -= n
            if shared[0] < 0:
                raise ValueError("archive work limit")

    def ref():
        index = r.get()
        if index >= len(built):
            raise ValueError("reference not backward")
        return built[index]

    for _ in range(count):
        charge(16)
        code = r.get()
        if code == LIT:
            n = r.get()
            charge(n)
            data = r.take(n).tobytes()
        elif code == CAT:
            n = r.get()
            if not 1 <= n <= NODES:
                raise ValueError("concat arity")
            parts = [ref() for _ in range(n)]
            charge(sum(map(len, parts)))
            data = b"".join(parts)
        elif code == REP:
            x, n = ref(), r.get()
            charge(len(x)*n)
            data = x*n if x else b""
        elif code == SLICE:
            x, off, n = ref(), r.get(), r.get()
            if off+n > len(x):
                raise ValueError("slice domain")
            charge(n)
            data = x[off:off+n]
        elif code == PATCH:
            x, y = ref(), ref()
            charge(len(x))
            data = xor_bytes(x, y)
        elif code == MAP:
            x, width, op, y = ref(), r.get(), r.get(), r.get()
            if width not in (1, 2, 4) or len(x) % width or y >= 1 << (8*width):
                raise ValueError("map domain")
            charge(len(x))
            data = b"".join(operation(int.from_bytes(x[i:i+width], "little"), y, op, 8*width)
                            .to_bytes(width, "little") for i in range(0, len(x), width))
        elif code == PERM:
            x, rows, cols, width = ref(), r.get(), r.get(), r.get()
            if width not in (1, 2, 4, 8) or not rows or not cols or rows*cols*width != len(x):
                raise ValueError("transpose shape")
            charge(len(x))
            data = np.frombuffer(x, np.uint8).reshape(rows, cols, width).transpose(1,0,2).tobytes()
        elif code == SPATIAL:
            residual = ref()
            w,h,a,b,c,d = (r.get() for _ in range(6))
            charge(len(residual))
            data = spatial(residual,w,h,a,b,c,d,True)
        elif code in (REC, EXPR):
            width, n, mod, k = (r.get() for _ in range(4))
            if width not in (1,2,4,8) or not 1 <= k <= 8 or not 2 <= mod <= 1 << (8*width) or n < k:
                raise ValueError("recurrence domain")
            charge(n*width)
            hist = [r.get() for _ in range(k)]
            if any(x >= mod for x in hist):
                raise ValueError("seed domain")
            if code == REC:
                co = [r.get() for _ in range(k)]
                bias = r.get()
                if max(*co, bias) >= mod:
                    raise ValueError("coefficient domain")
                if width == 4 and mod == 1 << 32 and k == 2 and NATIVE:
                    data = output("rec2", n*4, *co, bias, *hist)
                else:
                    a = bytearray(b"".join(x.to_bytes(width, "little") for x in hist))
                    for _ in range(k, n):
                        x = (bias+sum(c*h for c,h in zip(co, reversed(hist)))) % mod
                        hist = hist[1:]+[x]
                        a += x.to_bytes(width, "little")
                    data = bytes(a)
            else:
                terms = r.get()
                if not 1 <= terms <= 16 or (n-k)*terms > 2_000_000:
                    raise ValueError("expression budget")
                instructions = [(r.get(), r.get()) for _ in range(terms)]
                depth = 0
                for op, p in instructions:
                    if op == 8 and p < k or op == 9 and p < 1 << (8*width):
                        depth += 1
                    elif op < 8 and p == 0 and depth >= 2:
                        depth -= 1
                    else:
                        raise ValueError("expression stack")
                if depth != 1:
                    raise ValueError("expression result")
                a = bytearray(b"".join(x.to_bytes(width, "little") for x in hist))
                for _ in range(k,n):
                    stack = []
                    for op,p in instructions:
                        if op == 8:
                            stack.append(hist[-1-p])
                        elif op == 9:
                            stack.append(p)
                        else:
                            y = stack.pop()
                            stack[-1] = operation(stack[-1], y, op, 8*width)
                    x = stack[0] % mod
                    hist = hist[1:]+[x]
                    a += x.to_bytes(width,"little")
                data = bytes(a)
        elif code in (PRIME, CONST):
            kind, start, n = r.get(), r.get(), r.get()
            if kind > (1 if code == PRIME else 2):
                raise ValueError("generator id")
            charge(n*(4 if code == PRIME else 1))
            charge(16*(start+n))
            data = prime_data(start, n, kind) if code == PRIME else constant_data(kind, start, n)
        elif code == LFSR:
            n, degree, taps, seed = (r.get() for _ in range(4))
            if not 2 <= degree <= 48 or max(taps,seed) >= 1 << degree:
                raise ValueError("LFSR domain")
            charge(n)
            if NATIVE:
                data = output("lfsr", n, degree, taps, seed)
            else:
                reg, mask = seed, (1 << degree)-1
                out = bytearray()
                for i in range(n*8):
                    if i < degree:
                        bit = (seed >> (degree-1-i)) & 1
                    else:
                        bit = (reg & taps).bit_count() & 1
                        reg = ((reg << 1) | bit) & mask
                    if i % 8 == 0:
                        out.append(0)
                    out[-1] = (out[-1] << 1) | bit
                data = bytes(out)
        elif code == XORSHIFT:
            n, seed, little = r.get(), r.get(), r.get()
            if seed >= 1 << 32 or little > 1:
                raise ValueError("Xorshift domain")
            charge(n)
            if NATIVE:
                data = output("xorshift", n, seed, little)
            else:
                a, x = bytearray(), seed
                for _ in range((n+3)//4):
                    x ^= (x << 13) & 0xffffffff
                    x ^= x >> 17
                    x ^= (x << 5) & 0xffffffff
                    a += x.to_bytes(4, "little" if little else "big")
                data = bytes(a[:n])
        else:
            raise ValueError("unknown opcode")
        built.append(data)
    r.finish()
    if expected is not None and len(built[-1]) != expected:
        raise ValueError("program output size mismatch")
    return built[-1]
