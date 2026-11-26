"""Format-aware experiments: is there headroom inside ZIP/PDF containers?

The engine so far sees bytes.  A ZIP member is already Deflate-compressed and a
PDF stream is often Flate-compressed, so the raw byte stream looks random even
though the *content* is not.  This module measures the headroom honestly:

* a member is only eligible when the original Deflate stream can be reproduced
  bit for bit from its content and a recorded zlib level;
* every other byte of the container is stored literally and its cost is counted;
* the rebuilt file is compared with the original byte for byte.

Nothing is approximated: if the rebuild does not match, the row is marked
invalid and the measured size is not used.
"""

from __future__ import annotations

import argparse
import json
import lzma
import re
import struct
import time
import zipfile
import zlib
from pathlib import Path

import zstandard


def best_compress(data: bytes) -> tuple[str, bytes]:
    options = []
    options.append(("xz", lzma.compress(data, preset=6)))
    options.append(("zstd", zstandard.ZstdCompressor(level=19).compress(data)))
    import brotli

    options.append(("brotli", brotli.compress(data, quality=11)))
    options.append(("deflate", zlib.compress(data, 9)))
    return min(options, key=lambda item: len(item[1]))


def deflate_stream(content: bytes, level: int) -> bytes:
    compressor = zlib.compressobj(level, zlib.DEFLATED, -15)
    return compressor.compress(content) + compressor.flush()


def find_level(raw: bytes, content: bytes) -> int | None:
    for level in (6, 9, 1, 2, 3, 4, 5, 7, 8):
        try:
            if deflate_stream(content, level) == raw:
                return level
        except zlib.error:
            return None
    return None


def zip_regions(data: bytes) -> list[dict]:
    import io

    regions = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.compress_type != zipfile.ZIP_DEFLATED or info.compress_size == 0:
                continue
            offset = info.header_offset
            if data[offset : offset + 4] != b"PK\x03\x04":
                continue
            name_len, extra_len = struct.unpack_from("<HH", data, offset + 26)
            start = offset + 30 + name_len + extra_len
            raw = data[start : start + info.compress_size]
            try:
                content = zf.read(info)
            except Exception:
                continue
            if zlib.decompress(raw, -15) != content:
                continue
            level = find_level(raw, content)
            regions.append({"name": info.filename, "start": start, "end": start + len(raw),
                            "raw": raw, "content": content, "level": level})
    return regions


def rebuild(data: bytes, regions: list[dict], streams: list[bytes], literal_compressed: bytes,
            codec: str, literal_raw: int) -> bytes:
    out = bytearray(data)
    for region in regions:
        out[region["start"] : region["end"]] = b"\x00" * (region["end"] - region["start"])
    # The literal is the original file with eligible streams zeroed, compressed
    # as one stream; put it back first, then splice the re-deflated members.
    if codec == "xz":
        literal = lzma.decompress(literal_compressed)
    elif codec == "zstd":
        literal = zstandard.ZstdDecompressor().decompress(literal_compressed,
                                                          max_output_size=literal_raw)
    elif codec == "brotli":
        import brotli

        literal = brotli.decompress(literal_compressed)
    else:
        literal = zlib.decompress(literal_compressed)
    expected = len(data) - sum(region["end"] - region["start"] for region in regions)
    if len(literal) != expected:
        raise ValueError("literal length mismatch")
    mask = bytearray(len(data))
    for region in regions:
        mask[region["start"] : region["end"]] = b"\x01" * (region["end"] - region["start"])
    index = 0
    for i, flag in enumerate(mask):
        if not flag:
            out[i] = literal[index]
            index += 1
    for region, stream in zip(regions, streams):
        content = zstandard.ZstdDecompressor().decompress(stream, max_output_size=1 << 31)
        if content != region["content"]:
            raise ValueError("content mismatch")
        rebuilt = deflate_stream(content, region["level"])
        if rebuilt != region["raw"]:
            raise ValueError("deflate reproduction mismatch")
        out[region["start"] : region["end"]] = rebuilt
    return bytes(out)


def experiment_zip(path: Path) -> dict:
    data = path.read_bytes()
    start = time.perf_counter()
    regions = zip_regions(data)
    eligible = [r for r in regions if r["level"] is not None]
    streams = [zstandard.ZstdCompressor(level=19).compress(r["content"]) for r in eligible]
    mask = bytearray(len(data))
    for r in eligible:
        mask[r["start"] : r["end"]] = b"\x01" * (r["end"] - r["start"])
    compact = bytes(data[i] for i, flag in enumerate(mask) if not flag)
    codec, literal = best_compress(compact)
    # Rebuild uses Zstd for member contents, so the literal codec may differ.
    rebuilt = rebuild(data, eligible, streams, literal, codec, len(data))
    ok = rebuilt == data
    meta = 4 + 8 * len(eligible) + 1 + 1  # magic, offset/level pairs, codec id
    total = len(literal) + sum(len(s) for s in streams) + meta
    return {
        "suite": "zip", "name": path.name, "bytes": len(data),
        "xz_whole": len(lzma.compress(data, preset=6)),
        "members": len(regions), "reproducible": len(eligible),
        "member_bytes": sum(r["end"] - r["start"] for r in regions),
        "eligible_bytes": sum(r["end"] - r["start"] for r in eligible),
        "content_bytes": sum(len(r["content"]) for r in eligible),
        "total": total, "ratio": total / len(data), "ok": ok,
        "literal_codec": codec, "encode": time.perf_counter() - start,
        "levels": {str(r["level"]): sum(1 for x in eligible if x["level"] == r["level"])
                   for r in eligible},
    }


# ---------------------------------------------------------------------------
# PDF Flate streams
# ---------------------------------------------------------------------------
STREAM_RE = re.compile(rb"stream\r?\n")


def pdf_regions(data: bytes) -> list[dict]:
    regions = []
    for match in STREAM_RE.finditer(data):
        begin = match.end()
        end = data.find(b"endstream", begin)
        if end < 0:
            continue
        blob = data[begin:end]
        if blob.endswith(b"\r\n"):
            blob = blob[:-2]
        elif blob.endswith(b"\n"):
            blob = blob[:-1]
        try:
            content = zlib.decompress(blob)
        except zlib.error:
            continue
        if not content:
            continue
        level = find_level(blob, content)
        regions.append({"start": begin, "end": begin + len(blob), "raw": blob,
                        "content": content, "level": level})
    return regions


def experiment_pdf(path: Path) -> dict:
    data = path.read_bytes()
    start = time.perf_counter()
    regions = pdf_regions(data)
    eligible = [r for r in regions if r["level"] is not None]
    streams = [zstandard.ZstdCompressor(level=19).compress(r["content"]) for r in eligible]
    mask = bytearray(len(data))
    for r in eligible:
        mask[r["start"] : r["end"]] = b"\x01" * (r["end"] - r["start"])
    compact = bytes(data[i] for i, flag in enumerate(mask) if not flag)
    codec, literal = best_compress(compact)
    rebuilt = rebuild(data, eligible, streams, literal, codec, len(data))
    ok = rebuilt == data
    meta = 4 + 8 * len(eligible)
    total = len(literal) + sum(len(s) for s in streams) + meta
    return {
        "suite": "pdf", "name": path.name, "bytes": len(data),
        "xz_whole": len(lzma.compress(data, preset=6)),
        "streams": len(regions), "reproducible": len(eligible),
        "stream_bytes": sum(r["end"] - r["start"] for r in regions),
        "eligible_bytes": sum(r["end"] - r["start"] for r in eligible),
        "content_bytes": sum(len(r["content"]) for r in eligible),
        "total": total, "ratio": total / len(data), "ok": ok,
        "literal_codec": codec, "encode": time.perf_counter() - start,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_container.json"))
    parser.add_argument("--patterns", nargs="*", default=["*.zip", "*.docx", "*.pptx", "*.xlsx",
                                                         "*.pdf"])
    args = parser.parse_args()
    paths = list(args.paths)
    if not paths:
        root = Path("datasets/sxz5-data/raw")
        for pattern in args.patterns:
            paths += sorted(root.glob(pattern))
    rows = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else []
    done = {r["name"] for r in rows}
    for path in paths:
        if path.name in done:
            continue
        try:
            if path.suffix.lower() == ".pdf":
                row = experiment_pdf(path)
            elif path.suffix.lower() in (".zip", ".docx", ".pptx", ".xlsx"):
                row = experiment_zip(path)
            else:
                continue
        except Exception as exc:
            print(f"{path.name:<28} ERROR {exc}", flush=True)
            continue
        rows.append(row)
        args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"{path.name:<28} {row['bytes']:>9,} -> {row['total']:>9,} "
              f"({row['ratio']:6.2%}) xz={row['xz_whole']:>9,} "
              f"repro={row['reproducible']}/{row.get('members', row.get('streams'))} ok={row['ok']}",
              flush=True)
    print("saved", args.save)


if __name__ == "__main__":
    main()
