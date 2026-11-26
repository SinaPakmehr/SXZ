"""Check whether two equal-length files are cheaper as a base plus XOR deltas."""

from __future__ import annotations

import argparse
import time
import zlib
from pathlib import Path


def xor(left: bytes, right: bytes) -> bytes:
    return (int.from_bytes(left, "little") ^ int.from_bytes(right, "little")).to_bytes(len(left), "little")


def evaluate(basis: Path, target: Path, frame: int, sampled: bool) -> dict:
    total = basis.stat().st_size
    if total != target.stat().st_size:
        raise ValueError("files are not the same length")
    if sampled and total > frame:
        offsets = sorted({((total - frame) * i // 16) // 4096 * 4096 for i in range(17)})
    else:
        offsets = range(0, total, frame)
    n = same_bytes = plain_bytes = delta_bytes = chosen_bytes = wins = 0
    start = time.perf_counter()
    with basis.open("rb") as a, target.open("rb") as b:
        for offset in offsets:
            a.seek(offset)
            b.seek(offset)
            size = min(frame, total - offset)
            left, right = a.read(size), b.read(size)
            if len(left) != size or len(right) != size:
                raise ValueError("short read; file may have changed")
            delta = xor(left, right)
            packed = zlib.compress(delta, 1)
            if xor(left, zlib.decompress(packed)) != right:
                raise ValueError("delta round-trip mismatch")
            n += size
            same_bytes += delta.count(0)
            plain = min(len(right), len(zlib.compress(right, 1)))
            plain_bytes += plain
            delta_bytes += len(packed)
            chosen_bytes += 1 + min(len(packed), plain)  # one selection byte per measured chunk
            wins += len(packed) < plain
    return {"file_size": total, "examined": n, "same": same_bytes, "normal": plain_bytes,
            "xor_deflate": delta_bytes, "per_frame_choice": chosen_bytes, "winning_frames": wins,
            "seconds": time.perf_counter() - start}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--chunk-mib", type=int, choices=range(1, 17), default=4)
    parser.add_argument("--sample", action="store_true")
    args = parser.parse_args()
    print(evaluate(args.base, args.target, args.chunk_mib << 20, args.sample))


if __name__ == "__main__":
    main()
