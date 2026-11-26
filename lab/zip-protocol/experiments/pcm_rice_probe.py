"""Compare an exact Rice bit-count with Deflate on sampled PCM blocks.

This is a size estimate for a possible codec, not an archive writer.
"""

import argparse
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sinuxz.pcm import _encode_block, _mode, wav_layout


def rice_bits(words: list[int]) -> int:
    """Four-bit selector: k=0..14, or selector 15 for raw 16-bit words."""
    n = len(words)
    best = 16 * n
    for k in range(15):
        fixed = (k + 1) * n
        if fixed >= best:
            break
        best = min(best, fixed + sum(word >> k for word in words))
    return 4 + best


def measure(data: bytes, count: int) -> tuple[int, int, int, int]:
    layout = wav_layout(data)
    if layout is None:
        raise ValueError("expected a mono or stereo 16-bit PCM RIFF/WAVE")
    view = memoryview(data)
    size = layout.block_bytes
    nblocks = (layout.end - layout.start + size - 1) // size
    sample = [
        view[layout.start + i * size : min(layout.end, layout.start + (i + 1) * size)]
        for i in sorted({j * (nblocks - 1) // max(1, count - 1) for j in range(count)})
    ]
    modes = (3, 4, 5, 9, 10, 11) if layout.channels == 2 else (3, 4, 5)
    totals = [bytearray() for _ in modes]
    adaptive_bits = 0
    for block in sample:
        per_mode = []
        channel_bytes = len(block) // layout.channels
        frames = channel_bytes // 2
        for mode, stream in zip(modes, totals):
            transformed = _encode_block(block, layout.channels, _mode(mode, layout.channels))
            stream.extend(transformed)
            # Three bits for the per-block predictor; four more per plane pair.
            cost = 3
            for pos in range(0, len(transformed), channel_bytes):
                low = transformed[pos : pos + frames]
                high = transformed[pos + frames : pos + channel_bytes]
                cost += rice_bits([a | (b << 8) for a, b in zip(low, high)])
            per_mode.append(cost)
        adaptive_bits += min(per_mode)
    deflate = min(len(zlib.compress(stream, 9)) for stream in totals)
    return len(sample), sum(len(block) for block in sample), deflate, (adaptive_bits + 7) // 8


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--blocks", type=int, default=12)
    args = parser.parse_args()
    if args.blocks < 2:
        parser.error("--blocks must be at least 2")
    print("| WAV | Blocks | PCM B | Best fixed residual + zlib B | Adaptive Rice estimate B |")
    print("|---|---:|---:|---:|---:|")
    for path in args.files:
        blocks, raw, deflate, rice = measure(path.read_bytes(), args.blocks)
        print(f"| {path.name} | {blocks} | {raw} | {deflate} | {rice} |")


if __name__ == "__main__":
    main()
