"""Benchmark SXZ4 against SXZ2/SXZ3, general codecs and numeric baselines.

All SXZ variants use the same Deflate-6 backend unless the method name says
otherwise, so the formula engine is the only difference.  zstd/xz/brotli appear
as external references.  Every output is decoded and compared byte for byte.
"""

from __future__ import annotations

import argparse
import io
import json
import lzma
import time
import zlib
from pathlib import Path

import zstandard

from sinuxz.stream import StreamOptions, pack_stream, unpack_stream
from experiments.sxz3 import engine as engine3
from experiments.sxz4 import numeric4, spans4, transforms4

METHODS = ["deflate-6", "deflate-9", "zstd-3", "zstd-19", "zstd-22", "xz-6", "xz-9",
           "brotli-11", "lzma2-bcj",
           "sxz2", "sxz2-scan", "sxz3-B",
           "sxz4-off", "sxz4-tx", "sxz4-on", "sxz4-sweep", "sxz4-prog",
           "sxz4-tx-zstd", "sxz4-on-zstd", "sxz4-tx-lzma", "sxz4-on-lzma",
           "gorilla", "fpc", "delta-deflate"]


def sxz2_pack(options, data):
    out = io.BytesIO()
    pack_stream(io.BytesIO(data), out, options)
    return out.getvalue()


def sxz2_unpack(blob):
    out = io.BytesIO()
    unpack_stream(io.BytesIO(blob), out)
    return out.getvalue()


SXZ2 = {
    "sxz2": StreamOptions(chunk_size=256 << 10, lookback=4, scan_budget=0, level=6),
    "sxz2-scan": StreamOptions(chunk_size=256 << 10, lookback=4, scan_budget=64, level=6),
}


def pack_best(data: bytes, chains, spans_on: bool, prog: bool, **kwargs):
    best = None
    for chain in chains:
        blob, st = spans4.pack(data, chain=chain, spans_on=spans_on,
                               allow_program=prog, **kwargs)
        if best is None or len(blob) < len(best[0]):
            best = (blob, st, chain)
    return best


def _xz_filtered(data: bytes) -> bytes:
    filters = [{"id": lzma.FILTER_X86}, {"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]
    return lzma.compress(data, format=lzma.FORMAT_XZ, filters=filters)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_bench.json"))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--methods", nargs="*", default=METHODS)
    parser.add_argument("--chains", default="screened", choices=["screened", "identity", "all"])
    args = parser.parse_args()
    rows = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else []
    done = {(r["name"], r["method"]) for r in rows}
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    if args.only:
        manifest = [m for m in manifest if m["name"] in args.only]

    cache: dict[str, list[tuple[int, ...]]] = {}
    for item in manifest:
        data = Path(item["path"]).read_bytes()
        if item["name"] not in cache:
            if args.chains == "identity":
                chains = [(0,)]
            else:
                ranked = transforms4.screen(data, sample=32768)
                chains = [chain for _, chain in ranked[: (1 if args.chains == "screened" else 12)]]
                if (0,) not in chains:
                    chains.append((0,))
            cache[item["name"]] = chains
        chains = cache[item["name"]]
        for method in args.methods:
            if (item["name"], method) in done:
                continue
            info: dict = {}
            holder: dict = {}

            backend = spans4.BACKEND_DEFLATE
            pack_kwargs: dict = {}
            if method == "deflate-6":
                packer, unpacker = (lambda d: zlib.compress(d, 6)), zlib.decompress
            elif method == "deflate-9":
                packer, unpacker = (lambda d: zlib.compress(d, 9)), zlib.decompress
            elif method in ("zstd-3", "zstd-19", "zstd-22"):
                level = {"zstd-3": 3, "zstd-19": 19, "zstd-22": 22}[method]
                packer = lambda d, level=level: zstandard.ZstdCompressor(level=level).compress(d)
                unpacker = lambda b: zstandard.ZstdDecompressor().decompress(b, max_output_size=1 << 31)
            elif method == "xz-6":
                packer = lambda d: lzma.compress(d, preset=6)
                unpacker = lzma.decompress
            elif method == "xz-9":
                packer = lambda d: lzma.compress(d, preset=9 | lzma.PRESET_EXTREME)
                unpacker = lzma.decompress
            elif method == "brotli-11":
                import brotli

                packer = lambda d: brotli.compress(d, quality=11)
                unpacker = brotli.decompress
            elif method == "lzma2-bcj":
                packer, unpacker = _xz_filtered, lzma.decompress
            elif method in SXZ2:
                packer = lambda d, m=method: sxz2_pack(SXZ2[m], d)
                unpacker = sxz2_unpack
            elif method == "sxz3-B":
                def packer(d, holder=holder):
                    blob, st = engine3.pack(d, arch=engine3.ARCH_B)
                    holder["stats"] = st
                    return blob
                unpacker = engine3.unpack
            elif method.startswith("sxz4"):
                if method.endswith("-zstd"):
                    backend = spans4.BACKEND_ZSTD
                elif method.endswith("-lzma"):
                    backend = spans4.BACKEND_LZMA
                base = method[:-5] if method.endswith(("-zstd", "-lzma")) else method
                prog = method == "sxz4-prog"
                spans_on = base in ("sxz4-on", "sxz4-sweep", "sxz4-prog")
                if base == "sxz4-sweep":
                    pack_kwargs["tolerance_sweep"] = (0.0, 0.12, 0.30)
                if base == "sxz4-off":
                    use = [(0,)]
                elif base == "sxz4-tx":
                    use = chains
                else:
                    use = list(dict.fromkeys(chains[:1] + [(0,)]))
                def packer(d, use=use, spans_on=spans_on, prog=prog, holder=holder,
                           backend=backend, pack_kwargs=pack_kwargs):
                    blob, st, chain = pack_best(d, use, spans_on, prog, backend=backend,
                                                **pack_kwargs)
                    holder["stats"] = st
                    holder["chain"] = chain
                    return blob
                unpacker = spans4.unpack
            elif method == "gorilla":
                packer, unpacker = numeric4.gorilla_pack, numeric4.gorilla_unpack
            elif method == "fpc":
                packer, unpacker = numeric4.fpc_pack, numeric4.fpc_unpack
            elif method == "delta-deflate":
                packer, unpacker = numeric4.delta_deflate_pack, numeric4.delta_deflate_unpack
            else:
                raise SystemExit(f"unknown method {method}")

            start = time.perf_counter()
            blob = packer(data)
            encode = time.perf_counter() - start
            start = time.perf_counter()
            restored = unpacker(blob)
            decode = time.perf_counter() - start
            if restored != data:
                raise RuntimeError(f"{item['name']}/{method} round trip mismatch")

            if method == "sxz3-B":
                st = holder["stats"]
                info = {"spans": st.modelled, "modelled": min(len(data), st.modelled * engine3.BLOCK),
                        "models": st.models, "modes": st.modes}
            elif method.startswith("sxz4"):
                st = holder["stats"]
                info = {"spans": st.spans, "modelled": st.modelled_bytes, "models": st.models,
                        "modes": st.modes, "chain": list(holder["chain"]), "probes": st.probes,
                        "backend": backend, "tolerance": st.tolerance}

            row = {"name": item["name"], "family": item["family"], "category": item["category"],
                   "law": item.get("law", ""), "heldout": item.get("heldout", False), "bytes_in": len(data),
                   "method": method, "bytes": len(blob), "ratio": len(blob) / max(1, len(data)),
                   "encode": encode, "decode": decode, **info}
            rows.append(row)
            done.add((item["name"], method))
            args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            print(f"{item['name']:<26} {method:<16} {len(blob):>9,} {row['ratio']:6.2%} "
                  f"enc={encode:6.2f}s dec={decode:5.2f}s", flush=True)
    print("saved", args.save)


if __name__ == "__main__":
    main()
