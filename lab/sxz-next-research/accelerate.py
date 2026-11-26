"""Optional native hot loops. Python remains the wire reference."""
from ctypes import CDLL, Structure, c_char_p, c_size_t, c_uint32, c_uint64, c_void_p, create_string_buffer
from pathlib import Path
from struct import unpack_from

ROOT = Path(__file__).resolve().parent
SIZES = tuple(2**k for k in range(5, 17))
MASK = (1 << 32) - 1


class Hit(Structure):
    _fields_ = [(s, c_uint32) for s in ("pos", "len", "a", "b", "c", "x", "y")]


def load(path, defs):
    if not path.is_file():
        return None
    lib = CDLL(str(path))
    for name, (result, args) in defs.items():
        f = getattr(lib, name)
        f.restype, f.argtypes = result, args
    return lib


NATIVE = load(ROOT / ("sxzscan_next.dll" if __import__("os").name == "nt" else "libsxzscan_next.dylib" if __import__("sys").platform == "darwin" else "libsxzscan_next.so"), {
    "scan": (c_size_t, [c_char_p, c_size_t, c_void_p, c_size_t, c_size_t, c_size_t]),
    "rec2": (None, [c_void_p, c_size_t] + [c_uint32] * 5),
    "lfsr": (None, [c_void_p, c_size_t, c_uint32, c_uint64, c_uint64]),
    "xorshift": (None, [c_void_p, c_size_t, c_uint32, c_uint32]),
    "rice": (c_size_t, [c_void_p, c_size_t, c_uint32, c_void_p, c_size_t]),
    "png_filter": (c_uint32, [c_char_p, c_void_p, c_char_p] + [c_size_t] * 4),
    "spatial": (None, [c_char_p, c_void_p, c_size_t, c_size_t] + [c_uint32] * 4 + [c_size_t]),
})


def output(name, n, *args):
    out = create_string_buffer(n)
    getattr(NATIVE, name)(out, n, *args)
    return out.raw


def scan_native(data, step=1, minimum=32, cap=8192):
    if not NATIVE:
        raise RuntimeError("build sxzscan_next.dll")
    hits = (Hit * cap)()
    n = NATIVE.scan(data, len(data), hits, cap, step, minimum)
    return [tuple(getattr(h, f) for f, _ in Hit._fields_) for h in hits[:min(n, cap)]], n


def scan_python(data, step=1, minimum=32, cap=8192):
    pos = n = 0
    hits = []
    while pos + minimum <= len(data):
        x, y, z, t, u = unpack_from("<5I", data, pos)
        d0, d1, d2, d3 = y-x, z-y, t-z, u-t
        det = d1*d1 - d2*d0
        if det & 1:
            inv = pow(det, -1, 1 << 32)
            a, b = (d2*d1-d3*d0)*inv & MASK, (d1*d3-d2*d2)*inv & MASK
            c = (z-a*y-b*x) & MASK
            prev, last = t, u
            end = pos + 20
            while end + 4 <= min(len(data), pos + 65536):
                v = (a*last+b*prev+c) & MASK
                if unpack_from("<I", data, end)[0] != v:
                    break
                prev, last = last, v
                end += 4
            if end - pos >= minimum:
                if n < cap:
                    hits.append((pos, end-pos, a, b, c, x, y))
                n += 1
                pos = end
                continue
        pos += step
    return hits, n


def rice_native(vals, k, nbytes):
    if nbytes > 8 << 20:
        raise ValueError("rice output limit")
    data = (c_uint64 * len(vals))(*vals)
    out = create_string_buffer(nbytes)
    size = NATIVE.rice(data, len(vals), k, out, nbytes)
    if size != nbytes:
        raise ValueError("rice size")
    return out.raw
