"""Test whether content-defined boundaries recover repeats shifted by insertions.

A small diagnostic only: it measures exact-reference coverage, not archive size.
"""

import argparse
import random
import zlib
from collections import deque
from pathlib import Path
from time import perf_counter
from typing import Iterator

KIB = 1024


def fixed(data: bytes) -> Iterator[bytes]:
    for offset in range(0, len(data), 8 * KIB):
        yield data[offset : offset + 8 * KIB]


def gear(data: bytes) -> Iterator[bytes]:
    rng = random.Random(67)
    coefficients = [rng.getrandbits(64) for _ in range(256)]
    word_mask = (1 << 64) - 1
    start = value = 0
    for i, byte in enumerate(data, 1):
        value = ((value << 1) + coefficients[byte]) & word_mask
        size = i - start
        if size >= 32 * KIB or size >= 2 * KIB and (value & 8191) == 0:
            yield data[start:i]
            start, value = i, 0
    if start < len(data):
        yield data[start:]


def measure(chunks: Iterator[bytes]) -> tuple[int, int]:
    cache = deque(maxlen=32)
    frames = matched = 0
    for chunk in chunks:
        checksum = zlib.crc32(chunk)
        if any(crc == checksum and old == chunk for crc, old in cache):
            matched += len(chunk)
        cache.append((checksum, chunk))
        frames += 1
    return frames, matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="take up to 128 KiB of real text or binary data")
    args = parser.parse_args()
    with args.input.open("rb") as src:
        sample = src.read(128 * KIB)
    if not sample:
        parser.error("input is empty")
    data = b"".join(bytes([i]) * (i * 11 + 1) + sample for i in range(1, 7))
    for splitter in (fixed, gear):
        start = perf_counter()
        frames, hits = measure(splitter(data))
        print(f"{splitter.__name__}: {len(data)} input B, {frames} frames, "
              f"{hits} duplicate B, {perf_counter() - start:.3f} s")


if __name__ == "__main__":
    main()
