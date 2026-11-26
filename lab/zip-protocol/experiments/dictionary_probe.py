"""Measure a reversible 32 KiB dictionary bridge between independent frames.

Reports payload lengths only. This is not an SXZ2 codec.
"""

import argparse
import zlib
from pathlib import Path
from typing import BinaryIO


def probe(src: BinaryIO, frame: int, level: int, limit: int | None = None) -> tuple[int, int, int, int, int]:
    previous = b""
    read = plain = bridged = wins = solid_len = 0
    solid = zlib.compressobj(level)
    while limit is None or read < limit:
        cap = frame if limit is None else min(frame, limit - read)
        chunk = src.read(cap)
        if not chunk:
            break
        read += len(chunk)
        plain_size = min(len(chunk), len(zlib.compress(chunk, level)))
        plain += plain_size
        chosen = plain_size
        if previous:
            encoder = zlib.compressobj(level, zdict=previous)
            packed = encoder.compress(chunk) + encoder.flush()
            if len(packed) < chosen:
                decoder = zlib.decompressobj(zdict=previous)
                if decoder.decompress(packed) != chunk or not decoder.eof or decoder.unused_data:
                    raise ValueError("dictionary round-trip mismatch")
                chosen = len(packed)
                wins += 1
        bridged += chosen
        solid_len += len(solid.compress(chunk))
        previous = chunk[-32768:]
    solid_len += len(solid.flush())
    return read, plain, bridged, solid_len, wins


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--chunk-kib", type=int, default=256)
    parser.add_argument("--limit-mib", type=int)
    parser.add_argument("--level", type=int, choices=range(10), default=6)
    args = parser.parse_args()
    if args.chunk_kib < 1 or args.limit_mib is not None and args.limit_mib < 1:
        parser.error("chunk size and any limit must be positive")
    limit = None if args.limit_mib is None else args.limit_mib << 20
    print("| Input | Examined B | Independent B | With bridge B | Solid zlib B | Winning bridge frames |")
    print("|---|---:|---:|---:|---:|---:|")
    for path in args.files:
        with path.open("rb") as src:
            row = probe(src, args.chunk_kib * 1024, args.level, limit)
        print(f"| {path.name} | " + " | ".join(str(n) for n in row) + " |")


if __name__ == "__main__":
    main()
