"""Measure reversible numeric transforms on a simple mono PCM WAV (not an SXZ codec)."""

import argparse
import struct
import zlib
from pathlib import Path

if __package__:
    from .model_benchmark import audio_sample
else:
    from model_benchmark import audio_sample

WAV_HEADER = struct.Struct("<4sI4s4sIHHIIHH4sI")


def split_wav(data: bytes) -> tuple[bytes, bytes]:
    if len(data) < WAV_HEADER.size:
        raise ValueError("short WAV file")
    riff, size, wave, fmt, fmt_size, code, channels, rate, speed, align, bits, tag, length = WAV_HEADER.unpack_from(data)
    if (
        (riff, wave, fmt, fmt_size, code, channels, align, bits, tag)
        != (b"RIFF", b"WAVE", b"fmt ", 16, 1, 1, 2, 16, b"data")
        or speed != 2 * rate or length % 2 or length + WAV_HEADER.size != len(data) or size + 8 != len(data)
    ):
        raise ValueError("expected simple mono 16-bit PCM WAV with a 44-byte header")
    return data[:WAV_HEADER.size], data[WAV_HEADER.size:]


def difference(words: list[int]) -> list[int]:
    return [(value - prev) & 65535 for prev, value in zip([0, *words], words)]


def probe(data: bytes) -> list[tuple[int, int, int]]:
    header, audio = split_wav(data)
    words = [value for (value,) in struct.iter_unpack("<H", audio)]
    sizes = []
    for order in range(3):
        interleaved = b"".join(word.to_bytes(2, "little") for word in words)
        planar = interleaved[::2] + interleaved[1::2]
        variants = []
        for split_bytes, payload in ((False, interleaved), (True, planar)):
            compressed = zlib.compress(header + payload, 9)
            decoded_header, decoded = split_wav(zlib.decompress(compressed))
            if split_bytes:
                mid = len(decoded) // 2
                restored = bytearray(len(decoded))
                restored[::2], restored[1::2] = decoded[:mid], decoded[mid:]
                decoded = restored
            recovered = [value for (value,) in struct.iter_unpack("<H", decoded)]
            for _ in range(order):
                for i in range(1, len(recovered)):
                    recovered[i] = (recovered[i] + recovered[i - 1]) & 65535
            if decoded_header + b"".join(word.to_bytes(2, "little") for word in recovered) != data:
                raise ValueError("PCM round-trip mismatch")
            variants.append(len(compressed))
        sizes.append((order, *variants))
        words = difference(words)
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="use the generated test WAV if omitted")
    args = parser.parse_args()
    try:
        rows = probe(args.input.read_bytes() if args.input else audio_sample())
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print("| Difference order | Interleaved zlib B | Byte-plane zlib B |")
    print("|---:|---:|---:|")
    for order, interleaved, planar in rows:
        print(f"| {order} | {interleaved} | {planar} |")


if __name__ == "__main__":
    main()
