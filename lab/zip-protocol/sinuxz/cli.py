"""Command line interface for SINUXZ."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from . import __version__
from .analysis import analyze, format_report
from .bench import format_markdown, run_dir
from .container import Packer, _parse_header, inspect, unpack
from .folder import pack_folder, restore_folder
from .samples import build_samples
from .stream import MAGIC as STREAM_MAGIC
from .stream import StreamOptions, inspect_stream, pack_stream, unpack_stream


def _common_pack_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-window", type=int, default=512, help="bytes inspected per search window (512)")
    p.add_argument("--min-formula", type=int, default=16, help="minimum bytes a formula must cover (16)")
    p.add_argument("--extend", type=int, default=16384, help="max bytes a verified formula may extend to (16384)")
    p.add_argument("--step", type=int, default=None, help="raw scan stride; default adapts to input size")
    p.add_argument(
        "--scan-budget", type=int, default=None,
        help="maximum whole-bank probes across the file; 0 disables formula scan, not WAV/PNM predictors",
    )
    p.add_argument("--level", type=int, default=9, help="zlib level for raw pools (9)")
    _experimental_arg(p)


def _experimental_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--experimental-models", action="store_true",
        help="try quadratic and pi/e/phi slices; pack also tries PCM WAV and PGM/PPM prediction",
    )


def _packer_from_args(args: argparse.Namespace) -> Packer:
    return Packer(
        max_window=args.max_window,
        min_formula_bytes=args.min_formula,
        extend_bytes=args.extend,
        step=args.step,
        level=args.level,
        experimental_models=args.experimental_models,
        scan_budget=args.scan_budget,
    )


def cmd_pack(args: argparse.Namespace) -> int:
    with open(args.input, "rb") as fh:
        data = fh.read()
    packer = _packer_from_args(args)
    blob = packer.pack(data)
    with open(args.output, "wb") as fh:
        fh.write(blob)
    info = inspect(blob)
    print(
        f"{args.input}: {len(data)} -> {len(blob)} bytes "
        f"({info.get('ratio', 0):.3f}, formula {info['formula_ratio_percent']:.1f}%, "
        f"residual {info['residual_bytes']} B of input)"
    )
    print(f"formula scan: {packer.probe_count} bank probes in {packer.scan_seconds:.3f} s")
    return 0


@contextmanager
def _atomic_output(input_path: str, output_path: str):
    dest = Path(output_path)
    if dest.exists() and dest.samefile(input_path):
        raise ValueError("input and output must be different files")
    work = tempfile.NamedTemporaryFile(mode="wb", dir=dest.parent, prefix=".sxz-", suffix=".tmp", delete=False)
    tmp = Path(work.name)
    try:
        with work:
            yield work
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def cmd_pack_stream(args: argparse.Namespace) -> int:
    opts = StreamOptions(
        chunk_size=args.chunk_kib * 1024, lookback=args.lookback,
        scan_budget=args.scan_budget, level=args.level, experimental_models=args.experimental_models,
        bridge=args.bridge, fast_sample=args.fast_sample,
    )
    with open(args.input, "rb") as src, _atomic_output(args.input, args.output) as dst:
        report = pack_stream(src, dst, opts, second_pass=args.second_pass, temp_dir=Path(args.output).parent)
    print(f"SXZ2: {report.first.original_size} -> {report.stored_size} bytes ({report.first.frames} source frames)")
    print(f"first pass: {dict(report.first.codecs)}, {report.first.probes} bank probes in {report.first.scan_seconds:.3f} s")
    if report.second is not None:
        status = "kept" if report.nested else "discarded"
        print(f"second pass: {report.first.stored_size} -> {report.second.stored_size} bytes ({status})")
    return 0


def cmd_pack_folder(args: argparse.Namespace) -> int:
    opts = StreamOptions(
        chunk_size=args.chunk_kib * 1024, lookback=args.lookback,
        scan_budget=args.scan_budget, level=args.level, experimental_models=args.experimental_models,
        bridge=args.bridge, fast_sample=args.fast_sample,
    )
    def progress(phase: str, size: int) -> None:
        print(f"{phase}: {size / (1 << 30):.2f} GiB processed", file=sys.stderr, flush=True)

    info = pack_folder(Path(args.input), Path(args.output), opts, progress=progress if args.progress else None)
    print(json.dumps(info, indent=2, ensure_ascii=True))
    return 0


def cmd_unpack_folder(args: argparse.Namespace) -> int:
    info = restore_folder(Path(args.input), Path(args.output), max_output=args.max_output)
    print(json.dumps(info, indent=2, ensure_ascii=True))
    return 0


def cmd_unpack(args: argparse.Namespace) -> int:
    out = args.output
    if not out:
        out = args.input[:-4] if args.input.endswith(".sxz") else args.input + ".out"
    if args.max_output is not None and args.max_output < 0:
        raise ValueError("--max-output must be nonnegative")
    with open(args.input, "rb") as src, _atomic_output(args.input, out) as dst:
        is_stream = src.read(4) == STREAM_MAGIC
        src.seek(0)
        if is_stream:
            info = unpack_stream(src, dst, max_output=args.max_output, temp_dir=Path(out).parent)
            stored, original = info.stored_size, info.original_size
        else:
            blob = src.read()
            if args.max_output is not None and _parse_header(blob)[2] > args.max_output:
                raise ValueError("SXZ1 output exceeds configured limit")
            data = unpack(blob)
            dst.write(data)
            stored, original = len(blob), len(data)
    print(f"{stored} -> {original} bytes -> {out}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    with open(args.input, "rb") as fh:
        is_stream = fh.read(4) == STREAM_MAGIC
        fh.seek(0)
        info = inspect_stream(fh, limit=args.limit) if is_stream else inspect(fh.read())
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    if is_stream:
        layer = " (first-pass archive)" if info["nested"] else ""
        print(f"SXZ2: {info['stored_size']} stored bytes, {info['payload_size']} payload bytes{layer}")
        print(f"frames: {info['frames']}; max chunk: {info['chunk_size']} B; codecs: {info['codec_counts']}")
        for seg in info["segments"]:
            print(f"  @{seg['offset']:<12} {seg['codec']:<8} {seg['size']:>9} B -> {seg['cost_bytes']:>9} B")
        return 0
    print(f"file        : {args.input}")
    print(f"version     : {info['version']}  flags={info['flags']}")
    print(f"original    : {info['original_size']} bytes")
    print(f"stored      : {info['stored_size']} bytes  overhead={info['overhead_bytes']:+d}")
    if "ratio" in info:
        print(f"ratio       : {info['ratio']:.4f}  saving={info['saving_percent']:.2f}%")
        print(f"formula area: {info.get('formula_ratio_percent', 0):.2f}% of input")
        if info["residual_bytes"]:
            print(f"residual area: {info['residual_bytes']} bytes of input")
    print(f"codecs      : {info['codec_counts']}")
    for i, seg in enumerate(info["segments"][: args.limit]):
        print(
            f"  [{i:4d}] {seg['codec']:<12} @{seg['offset']:<8} {seg['size']:>8} bytes  "
            f"{seg['cost_bytes']:>8} stored  {seg.get('detail', '')}"
        )
    if len(info["segments"]) > args.limit:
        print(f"  ... {len(info['segments']) - args.limit} more segments")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    if not os.path.isdir(args.dir):
        print(f"sample directory not found: {args.dir}", file=sys.stderr)
        return 2
    rows = run_dir(
        args.dir,
        max_window=args.max_window,
        min_formula_bytes=args.min_formula,
        extend_bytes=args.extend,
        step=args.step,
        level=args.level,
        experimental_models=args.experimental_models,
        scan_budget=args.scan_budget,
    )
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    table = format_markdown(rows)
    print(table)
    if args.save:
        os.makedirs(os.path.dirname(os.path.abspath(args.save)), exist_ok=True)
        with open(args.save, "w", encoding="utf-8") as fh:
            fh.write("# SINUXZ benchmark\n\n")
            fh.write(table + "\n")
        print(f"\nsaved: {args.save}")
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    with open(args.input, "rb") as fh:
        data = fh.read()
    packer = Packer(
        max_window=args.block, min_formula_bytes=args.min_formula, extend_bytes=0,
        experimental_models=args.experimental_models,
    )
    total = (len(data) + args.block - 1) // args.block
    counts: dict[str, int] = {}
    covered = 0
    print(f"{args.input}: {len(data)} bytes, {total} blocks of {args.block} bytes")
    print(f"{'offset':>8}  {'model':<12} {'transform':<12} {'cover':>6}  {'cost':>5}")
    for i in range(total):
        block = data[i * args.block : (i + 1) * args.block]
        cand = packer.find_formula(block)
        if cand is None:
            print(f"{i * args.block:>8}  {'-':<12} {'-':<12} {0:>6}  {'-':>5}")
            continue
        key = f"{cand.model.name}/{cand.transform_id}"
        counts[key] = counts.get(key, 0) + 1
        covered += cand.cover_bytes
        _, _, params = cand.model.describe(cand.params).partition(" ")
        print(
            f"{i * args.block:>8}  {cand.model.name:<12} t{cand.transform_id:<11} "
            f"{cand.cover_bytes:>6}  {cand.payload_bytes:>5}" + (f"  {params}" if params else "")
        )
    print("\nfamily summary:")
    print(f"  covered by formulas: {covered}/{len(data)} bytes ({100 * covered / max(len(data), 1):.1f}%)")
    for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {key:<28} {n} blocks")
    return 0


def cmd_samples(args: argparse.Namespace) -> int:
    paths = build_samples(args.out)
    print(f"wrote {len(paths)} files to {args.out}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    with open(args.input, "rb") as fh:
        data = fh.read()
    info = analyze(data, sample_bits=args.sample_bits)
    if args.json:
        print(json.dumps(info, indent=2))
    else:
        print(format_report(info))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sinuxz", description="formula-based bit stream compression research kit")
    p.add_argument("--version", action="version", version=f"sinuxz {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pack", help="compress a file")
    sp.add_argument("input")
    sp.add_argument("output")
    _common_pack_args(sp)
    sp.set_defaults(func=cmd_pack)

    sp = sub.add_parser("pack-stream", help="compress with bounded-memory SXZ2 frames")
    sp.add_argument("input")
    sp.add_argument("output")
    sp.add_argument("--chunk-kib", type=int, default=1024, help="maximum source frame size (1024 KiB)")
    sp.add_argument("--lookback", type=int, default=4, help="keep this many previous frames for exact references (4)")
    sp.add_argument("--scan-budget", type=int, default=32, help="whole-bank probes per generic frame (32); 0 disables")
    sp.add_argument("--level", type=int, default=6, help="Deflate level (6)")
    sp.add_argument("--second-pass", action="store_true", help="recompress the archive once; keep it only if smaller")
    sp.add_argument("--bridge", action="store_true", help="optionally reuse the previous frame's last 32 KiB as a dictionary")
    sp.add_argument("--fast-sample", action="store_true", help="with scan disabled, bypass Deflate on near-incompressible samples")
    _experimental_arg(sp)
    sp.set_defaults(func=cmd_pack_stream)

    sp = sub.add_parser("pack-folder", help="stream a directory to a verified PAX TAR inside SXZ2")
    sp.add_argument("input")
    sp.add_argument("output")
    sp.add_argument("--chunk-kib", type=int, default=4096)
    sp.add_argument("--lookback", type=int, default=4)
    sp.add_argument("--scan-budget", type=int, default=0, help="whole-bank probes per TAR frame (0)")
    sp.add_argument("--level", type=int, default=1)
    sp.add_argument("--bridge", action="store_true")
    sp.add_argument("--fast-sample", action="store_true", help="skip Deflate on frames whose samples do not shrink")
    sp.add_argument("--progress", action="store_true", help="report each GiB packed or verified on stderr")
    _experimental_arg(sp)
    sp.set_defaults(func=cmd_pack_folder)

    sp = sub.add_parser("unpack-folder", help="restore a pack-folder archive to a new directory")
    sp.add_argument("input")
    sp.add_argument("output")
    sp.add_argument("--max-output", type=int, help="reject decoded TAR larger than this number of bytes")
    sp.set_defaults(func=cmd_unpack_folder)

    sp = sub.add_parser("unpack", help="decompress a .sxz file")
    sp.add_argument("input")
    sp.add_argument("output", nargs="?")
    sp.add_argument("--max-output", type=int, help="reject output beyond this many bytes")
    sp.set_defaults(func=cmd_unpack)

    sp = sub.add_parser("inspect", help="show container layout")
    sp.add_argument("input")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--limit", type=int, default=30)
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("bench", help="compare against zlib/bz2/lzma")
    sp.add_argument("--dir", default="samples")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--save", default=None)
    _common_pack_args(sp)
    sp.set_defaults(func=cmd_bench)

    sp = sub.add_parser("discover", help="map formula families over a file")
    sp.add_argument("input")
    sp.add_argument("--block", type=int, default=256)
    sp.add_argument("--min-formula", type=int, default=16)
    _experimental_arg(sp)
    sp.set_defaults(func=cmd_discover)

    sp = sub.add_parser("samples", help="write the deterministic sample set")
    sp.add_argument("--out", default="samples")
    sp.set_defaults(func=cmd_samples)

    sp = sub.add_parser("analyze", help="bit plane / linear complexity forensics")
    sp.add_argument("input")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--sample-bits", type=int, default=8192)
    sp.set_defaults(func=cmd_analyze)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
