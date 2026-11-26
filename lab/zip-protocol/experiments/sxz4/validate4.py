"""SXZ4 validation suites: noise, planted spans, unknown laws, decomposition.

Every row is a real measurement: the archive is decoded and compared with the
input byte for byte.  The suites are deliberately small and deterministic so
they can be re-run and audited.
"""

from __future__ import annotations

import argparse
import json
import lzma
import random
import struct
import time
import zlib
from pathlib import Path

import zstandard

from experiments.sxz4 import spans4, transforms4

SIZE = 256 * 1024


def order2(n: int, a=3, b=5, c=7, x0=12345, x1=67890, width=4, order="little") -> bytes:
    mask = (1 << (8 * width)) - 1
    values = [x0 & mask, x1 & mask]
    while len(values) < n // width:
        values.append((a * values[-1] + b * values[-2] + c) & mask)
    return b"".join(v.to_bytes(width, order) for v in values)[:n]


def affine(n: int, a=7, b=17, width=2, order="little") -> bytes:
    mask = (1 << (8 * width)) - 1
    return b"".join(((b + a * i) & mask).to_bytes(width, order)
                    for i in range(n // width))[:n]


def quadratic(n: int, width=2) -> bytes:
    mask = (1 << (8 * width)) - 1
    return b"".join(((3 * i * i + 5 * i + 7) & mask).to_bytes(width, "little")
                    for i in range(n // width))[:n]


def float32_ramp(n: int) -> bytes:
    value, out = 1.0, bytearray()
    while len(out) < n:
        out += struct.pack("<f", value)
        value *= 1.00001
    return bytes(out[:n])


def add_byte_noise(data: bytes, rate: float, seed: int) -> bytes:
    rng = random.Random(seed)
    out = bytearray(data)
    for i in range(len(out)):
        if rng.random() < rate:
            out[i] ^= 1 << rng.randrange(8)
    return bytes(out)


def add_value_noise(data: bytes, rate: float, sigma: float, seed: int, width: int) -> bytes:
    """Replace a fraction of words by ``word + round(gauss(0, sigma))``."""
    rng = random.Random(seed)
    out = bytearray(data)
    mask = (1 << (8 * width)) - 1
    for i in range(0, len(out) - width + 1, width):
        if rng.random() < rate:
            value = (int.from_bytes(out[i : i + width], "little") + round(rng.gauss(0, sigma))) & mask
            out[i : i + width] = value.to_bytes(width, "little")
    return bytes(out)


def pack_sxz4(data: bytes, chain, **kwargs):
    start = time.perf_counter()
    blob, stats = spans4.pack(data, chain=chain, **kwargs)
    elapsed = time.perf_counter() - start
    assert spans4.unpack(blob) == data
    return blob, stats, elapsed


def best_chain(data: bytes) -> tuple[int, ...]:
    ranked = transforms4.screen(data, sample=32768)
    return ranked[0][1] if ranked else (0,)


def suite_noise(out: list[dict]) -> None:
    bases = {
        "order2-u32": (order2(SIZE), 4, 1.0),
        "affine-u16": (affine(SIZE), 2, 3.0),
        "quadratic-u16": (quadratic(SIZE), 2, 3.0),
        "float32-ramp": (float32_ramp(SIZE), 4, 0.0),
    }
    rates = (0.0, 0.001, 0.01, 0.03, 0.05, 0.10, 0.20)
    for name, (base, width, sigma) in bases.items():
        for rate in rates:
            if rate == 0.0:
                data = base
            elif sigma:
                data = add_value_noise(base, rate, sigma, 101 + int(rate * 1000), width)
            else:
                data = add_byte_noise(base, rate, 101 + int(rate * 1000))
            chain = best_chain(data)
            chains = list(dict.fromkeys([chain, (0,)]))
            rows = {}
            for method in ("deflate-6", "zstd-19", "xz-6", "sxz4-off", "sxz4-tx", "sxz4-on"):
                if method == "deflate-6":
                    size, enc, dec = _codec(zlib.compress, zlib.decompress, data, 6)
                elif method == "zstd-19":
                    size, enc, dec = _codec(lambda d: zstandard.ZstdCompressor(level=19).compress(d),
                                            lambda b: zstandard.ZstdDecompressor().decompress(b, max_output_size=1 << 31),
                                            data)
                elif method == "xz-6":
                    size, enc, dec = _codec(lambda d: lzma.compress(d, preset=6), lzma.decompress, data)
                elif method == "sxz4-off":
                    blob, st, enc = pack_sxz4(data, (0,), spans_on=False)
                    size, dec = len(blob), 0.0
                else:
                    spans_on = method == "sxz4-on"
                    options = chains if spans_on else [(0,)]
                    best = None
                    for option in options:
                        blob, stats, seconds = pack_sxz4(data, option, spans_on=spans_on)
                        if best is None or len(blob) < len(best[0]):
                            best = (blob, stats, seconds, option)
                    blob, st, enc, chosen = best
                    size, dec = len(blob), 0.0
                rows[method] = {"bytes": size, "encode": enc, "decode": dec}
                if method.startswith("sxz4") and method != "sxz4-off":
                    rows[method].update({"spans": st.spans, "modelled": st.modelled_bytes,
                                         "modes": st.modes, "models": st.models,
                                         "chain": list(chosen)})
            out.append({"suite": "noise", "name": name, "rate": rate,
                        "chain": list(chain), "rows": rows})
            print(f"noise {name:<14} rate={rate:<6} deflate={rows['deflate-6']['bytes']:>7} "
                  f"on={rows['sxz4-on']['bytes']:>7} spans={rows['sxz4-on'].get('spans', 0)}", flush=True)


def _codec(pack, unpack, data, *args):
    start = time.perf_counter()
    blob = pack(data, *args)
    enc = time.perf_counter() - start
    start = time.perf_counter()
    assert unpack(blob) == data
    dec = time.perf_counter() - start
    return len(blob), enc, dec


# ---------------------------------------------------------------------------
# Planted spans
# ---------------------------------------------------------------------------
def suite_spans(out: list[dict]) -> None:
    rng = random.Random(2026)
    base = bytes(rng.randbytes(SIZE))
    for length in (512, 1024, 4096, 16384, 65536):
        for count in (1, 3):
            data = bytearray(base)
            planted = []
            slot = SIZE // count
            for index in range(count):
                room = slot - length
                start = index * slot + (rng.randrange(0, room) if room > 0 else 0)
                start -= start % 3  # deliberately not word aligned for some
                data[start : start + length] = order2(length + 8)[:length]
                planted.append((start, length))
            payload = bytes(data)
            modes = [("grid1024", {}),
                     ("grid256", {"probe_step": 256}),
                     ("grid1024-refine", {"refine": (64, 192, 512, 768)})]
            for label, kwargs in modes:
                blob, st, enc = pack_sxz4(payload, (0,), max_probes=2000, **kwargs)
                found = []
                decoded = _spans_of(blob)
                for start, length in planted:
                    best = None
                    for span in decoded:
                        overlap = (min(start + length, span["start"] + span["length"])
                                   - max(start, span["start"]))
                        if overlap <= 0:
                            continue
                        hit = (span["start"] - start, round(overlap / length, 3), span["length"])
                        if best is None or hit[1] > best[1]:
                            best = hit
                    found.append(best)
                out.append({"suite": "spans", "length": length, "count": count,
                            "mode": label, "planted": planted, "found": found,
                            "bytes": len(blob), "spans": st.spans,
                            "modelled": st.modelled_bytes, "encode": enc})
                print(f"spans len={length:<6} n={count} {label:<16} "
                      f"spans={st.spans:<2} modelled={st.modelled_bytes:>7} found={found}", flush=True)
            # Oracle probe: does detection work at all when the grid is right?
            oracle = []
            for start, length in planted:
                span = spans4.try_at(payload, start, False)
                oracle.append(None if span is None else
                              (0, round(min(span["length"], length) / length, 3), span["length"]))
            out.append({"suite": "spans", "length": length, "count": count,
                        "mode": "oracle", "planted": planted, "found": oracle,
                        "bytes": None, "spans": sum(1 for f in oracle if f is not None),
                        "modelled": None, "encode": 0.0})
            print(f"spans len={length:<6} n={count} oracle           found={oracle}", flush=True)


def _spans_of(blob: bytes) -> list[dict]:
    """Decode just the position map of an SXZ4 archive (test helper)."""
    (_, _, flags, _, _, chain_len, _, _, map_raw, map_comp, _) = spans4.HEADER.unpack_from(blob, 0)
    if flags != spans4.FLAG_SPANS:
        return []
    pos = spans4.HEADER.size + chain_len
    map_blob = spans4._decompress(blob[pos : pos + map_comp], spans4.BACKEND_DEFLATE, map_raw)
    spans, _ = spans4.parse_map(map_blob)
    return spans


# ---------------------------------------------------------------------------
# Laws outside the fixed bank
# ---------------------------------------------------------------------------
def unknown_families() -> dict[str, bytes]:
    n = SIZE // 4
    out = {}
    # order-3 additive recurrence: x[n] = x[n-1] + x[n-3] + 1
    values = [7, 11, 13]
    while len(values) < n:
        values.append((values[-1] + values[-3] + 1) & 0xFFFFFFFF)
    out["order3-add"] = b"".join(v.to_bytes(4, "little") for v in values)
    # Park-Miller LCG modulo the prime 2**31-1
    value, chunk = 12345, bytearray()
    while len(chunk) < SIZE:
        value = (48271 * value) % 2147483647
        chunk += value.to_bytes(4, "little")
    out["prime-lcg"] = bytes(chunk[:SIZE])
    # byte permutation automaton
    perm = list(range(256))
    random.Random(7).shuffle(perm)
    state, chunk = 3, bytearray()
    while len(chunk) < SIZE:
        state = perm[state]
        chunk.append(state)
    out["perm-map"] = bytes(chunk[:SIZE])
    # mul-xor: inside the depth-2 program grammar
    value, chunk = 0x0BADF00D, bytearray()
    while len(chunk) < SIZE:
        chunk += value.to_bytes(4, "little")
        value = ((value * 5) & 0xFFFFFFFF) ^ 0x1234
    out["mul-xor"] = bytes(chunk[:SIZE])
    # rotate-add: inside the grammar too
    value, chunk = 0xDEADBEEF, bytearray()
    while len(chunk) < SIZE:
        chunk += value.to_bytes(4, "little")
        value = (((value >> 5) | ((value << 27) & 0xFFFFFFFF)) + 3) & 0xFFFFFFFF
    out["rot-add"] = bytes(chunk[:SIZE])
    return out


def suite_unknown(out: list[dict]) -> None:
    for name, data in unknown_families().items():
        for gate in (True, False):
            probes = 64 if gate else 32
            blob, st, enc = pack_sxz4(data, (0,), gate=gate, max_probes=probes,
                                      allow_program=True)
            out.append({"suite": "unknown", "name": name, "gate": gate,
                        "bytes": len(blob), "deflate": len(zlib.compress(data, 6)),
                        "xz": len(lzma.compress(data, preset=6)),
                        "spans": st.spans, "modelled": st.modelled_bytes,
                        "models": st.models, "modes": st.modes,
                        "has_law": spans4.has_law(data[:2048]), "encode": enc})
            print(f"unknown {name:<12} gate={gate!s:<5} law={spans4.has_law(data[:2048])!s:<5} "
                  f"bytes={len(blob):>7} spans={st.spans} models={st.models}", flush=True)


# ---------------------------------------------------------------------------
# Component decomposition
# ---------------------------------------------------------------------------
DECOMPOSE = [
    ("datasets/sxz4-corpus/order2-u32.bin", "order2-u32"),
    ("datasets/sxz4-corpus/cross-3x-u16.bin", "cross-3x-u16"),
    ("datasets/sxz4-corpus/ecg-train.bin", "ecg-train"),
    ("datasets/sxz4-corpus/eeg-train.bin", "eeg-train"),
    ("datasets/sxz4-corpus/text-train.bin", "text-train"),
    ("datasets/sxz4-corpus/weights-train.bin", "weights-train"),
]


def suite_decompose(out: list[dict]) -> None:
    for path, name in DECOMPOSE:
        data = Path(path).read_bytes()
        chain = best_chain(data)
        row = {"suite": "decompose", "name": name, "chain": list(chain), "input": len(data)}

        def both(**kwargs):
            best = None
            for option in dict.fromkeys([chain, (0,)]):
                blob, st, seconds = pack_sxz4(data, chain=option, **kwargs)
                if best is None or len(blob) < len(best[0]):
                    best = (blob, st, seconds, option)
            return best

        variants = {
            "backend-only": lambda: pack_sxz4(data, chain=(0,), spans_on=False) + ((0,),),
            "backend+tx": lambda: both(spans_on=False),
            "backend+exact": lambda: both(spans_on=True, exact_only=True),
            "backend+model+residual": lambda: pack_sxz4(data, chain=(0,), spans_on=True) + ((0,),),
            "program": lambda: pack_sxz4(data, chain=(0,), spans_on=True, allow_program=True) + ((0,),),
            "full": lambda: both(spans_on=True),
        }
        for label, make in variants.items():
            blob, st, enc, used = make()
            row[label] = {"bytes": len(blob), "encode": enc, "spans": st.spans,
                          "modelled": st.modelled_bytes, "modes": st.modes,
                          "models": st.models, "chain": list(used)}
            print(f"decompose {name:<18} {label:<24} {len(blob):>8} enc={enc:6.2f}s "
                  f"chain={used} spans={st.spans}", flush=True)
        out.append(row)


# ---------------------------------------------------------------------------
# Backend comparison for the formula engine
# ---------------------------------------------------------------------------
def suite_backends(out: list[dict]) -> None:
    for path, name in DECOMPOSE[:5]:
        data = Path(path).read_bytes()
        chain = best_chain(data)
        row = {"suite": "backends", "name": name, "chain": list(chain)}
        for label, backend in (("deflate", 0), ("zstd", 1), ("lzma", 2)):
            for mode in ("tx", "on"):
                spans_on = mode == "on"
                options = list(dict.fromkeys([chain, (0,)])) if spans_on else [chain]
                best = None
                for option in options:
                    blob, st, enc = pack_sxz4(data, option, spans_on=spans_on,
                                              backend=backend)
                    if best is None or len(blob) < len(best[0]):
                        best = (blob, st, enc, option)
                blob, st, enc, used = best
                row[f"{mode}-{label}"] = {"bytes": len(blob), "encode": enc,
                                          "spans": st.spans, "modelled": st.modelled_bytes,
                                          "chain": list(used)}
                print(f"backend {name:<14} {mode}-{label:<8} {len(blob):>8} enc={enc:6.2f}s "
                      f"chain={used}", flush=True)
        out.append(row)


SUITES = {"noise": suite_noise, "spans": suite_spans, "unknown": suite_unknown,
          "decompose": suite_decompose, "backends": suite_backends}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=sorted(SUITES))
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_validation.json"))
    args = parser.parse_args()
    rows = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else []
    rows = [r for r in rows if r.get("suite") != args.suite]
    SUITES[args.suite](rows)
    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print("saved", args.save, "rows", len(rows))


if __name__ == "__main__":
    main()
