"""Frame-level SXZ2 measurements: budget scope, chunk phase, boundary crossing."""

from __future__ import annotations

import argparse
import io
import json
import zlib
from pathlib import Path

import sinuxz.container as container
import sinuxz.stream as stream
from sinuxz.container import CODEC_FORMULA, inspect
from sinuxz.stream import StreamOptions, pack_stream, unpack_stream
from experiments.audit import planted

MAGIC = stream.MAGIC
HEADER = stream.HEADER
FRAME = stream.FRAME
FOOTER = stream.FOOTER
END = stream.END


class CountingPacker(container.Packer):
    records: list[dict] = []

    def pack(self, data: bytes) -> bytes:
        blob = super().pack(data)
        CountingPacker.records.append({
            "raw": len(data), "probes": self.probe_count, "budget": self.scan_budget,
            "segments": [(seg.codec, seg.size) for seg in self.segments],
        })
        return blob


def frames_of(blob: bytes) -> list[dict]:
    stream_io = io.BytesIO(blob)
    magic, version, flags, chunk, lookback = HEADER.unpack(stream_io.read(HEADER.size))
    if magic != MAGIC:
        raise ValueError("not SXZ2")
    out, offset = [], 0
    while True:
        tag = stream_io.read(1)
        if not tag:
            raise ValueError("truncated")
        if tag[0] == END:
            break
        codec, raw, stored, crc = FRAME.unpack(tag + stream_io.read(FRAME.size - 1))
        payload = stream_io.read(stored)
        formula = 0
        if codec == container.CODEC_FORMULA:
            formula = raw
        elif codec == stream.SXZ1:
            try:
                info = inspect(payload)
            except ValueError:
                info = None
            if info:
                formula = info["formula_bytes"]
        if codec == stream.PCM or codec == stream.PNM:
            formula = raw
        out.append({"offset": offset, "raw": raw, "stored": stored,
                    "codec": stream.CODECS[codec], "formula_bytes": formula})
        offset += raw
    return out


def pack(data: bytes, *, chunk: int, budget: int, experimental: bool, level: int = 6) -> dict:
    CountingPacker.records = []
    saved = stream.Packer
    stream.Packer = CountingPacker
    try:
        options = StreamOptions(chunk_size=chunk, lookback=0, scan_budget=budget,
                                level=level, experimental_models=experimental)
        buf = io.BytesIO()
        report = pack_stream(io.BytesIO(data), buf, options)
    finally:
        stream.Packer = saved
    blob = buf.getvalue()
    restored = io.BytesIO()
    unpack_stream(io.BytesIO(blob), restored)
    if restored.getvalue() != data:
        raise RuntimeError("SXZ2 round trip mismatch")
    deflate = 16 + len(zlib.compress(data, level))
    return {"bytes": len(blob), "deflate": deflate, "net": len(blob) - deflate,
            "frames": frames_of(blob), "probe_records": CountingPacker.records,
            "probes": report.first.probes, "formula_bytes": report.first.formula_bytes}


def coverage(records: list[dict], start: int, length: int) -> int:
    """Formula bytes that actually overlap [start, start+length), frame by frame."""
    total = 0
    base = 0
    for record in records:
        offset = base
        for codec, size in record["segments"]:
            if codec == CODEC_FORMULA and offset < start + length and offset + size > start:
                total += min(offset + size, start + length) - max(offset, start)
            offset += size
        base += record["raw"]
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=Path("results/audit_frames.json"))
    args = parser.parse_args()
    rows = []

    # 1. Is --scan-budget per file or per frame?
    rng0 = __import__("random").Random(3)
    data = rng0.randbytes(1 << 20)
    for chunk, budget in ((1 << 20, 8), (1 << 19, 8), (1 << 18, 8)):
        result = pack(data, chunk=chunk, budget=budget, experimental=False)
        row = {"test": "budget-scope", "chunk": chunk, "budget": budget,
               "frames": len(result["probe_records"]),
               "probes_per_frame": [r["probes"] for r in result["probe_records"]],
               "probes_total": result["probes"]}
        rows.append(row)
        print(row, flush=True)

    # 2. Chunk phase: the same 8 KiB formula at the same absolute offset, different frames.
    rng = __import__("random").Random(11)
    pattern = planted.affine_word(8192, 2, "big", 3, 100)
    start = 3000
    mixed = bytes(rng.getrandbits(8) for _ in range(start)) + pattern + bytes(
        rng.getrandbits(8) for _ in range(20000))
    for chunk in (4096, 65536, 1 << 20):
        for budget in (8, 64, 2048):
            result = pack(mixed, chunk=chunk, budget=budget, experimental=True)
            covered = coverage(result["probe_records"], start, len(pattern))
            row = {"test": "chunk-phase", "chunk": chunk, "budget": budget,
                   "planted": len(pattern), "covered": covered,
                   "coverage": covered / len(pattern), "net": result["net"],
                   "probes": result["probes"], "frames": len(result["frames"])}
            rows.append(row)
            print(row, flush=True)

    # 3. Patterns that cross a frame boundary.
    for case in planted.boundary_cases(65536):
        for chunk in (65536, 262144):
            for budget in (8, 64, 2048):
                result = pack(case.data, chunk=chunk, budget=budget, experimental=True)
                covered = coverage(result["probe_records"], case.start, case.length)
                row = {"test": "crossing", "case": case.name, "chunk": chunk,
                       "budget": budget, "planted": case.length, "covered": covered,
                       "coverage": covered / case.length, "net": result["net"],
                       "probes": result["probes"]}
                rows.append(row)
                print(row, flush=True)

    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print("saved", args.save)


if __name__ == "__main__":
    main()
