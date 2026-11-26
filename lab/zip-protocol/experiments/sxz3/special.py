"""Specialised reference codecs for the audio and image items.

FLAC and PNG are not general-purpose compressors: they are included because the
research corpus contains raw PCM and raw RGB, where a domain codec is the fair
baseline.  Both are compared on exactly the bytes SXZ3 receives.
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from experiments.sxz3 import engine


def wav_header(data: bytes, rate: int = 44100, channels: int = 2) -> bytes:
    block = channels * 2
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, 16)
            + b"data" + struct.pack("<I", len(data)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("datasets/sxz3-corpus"))
    parser.add_argument("--save", type=Path, default=Path("results/sxz3_special.json"))
    args = parser.parse_args()
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        audio = (args.corpus / "wav-train.bin").read_bytes()
        wav = audio[: (len(audio) // 4) * 4]
        source = tmp / "slice.wav"
        source.write_bytes(wav_header(wav) + wav)
        target = tmp / "slice.flac"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                        "-c:a", "flac", "-compression_level", "8", str(target)], check=True)
        sxz3, _ = engine.pack(wav, arch=engine.ARCH_B)
        rows.append({"item": "audio", "codec": "flac-8", "bytes": target.stat().st_size,
                     "input": len(wav), "sxz3-B": len(sxz3)})

        image = (args.corpus / "ppm-train.bin").read_bytes()
        pixels = image[: 512 * 168 * 3]
        photo = Image.frombytes("RGB", (512, 168), pixels)
        png = tmp / "slice.png"
        photo.save(png, optimize=True)
        sxz3, _ = engine.pack(pixels, arch=engine.ARCH_B)
        rows.append({"item": "image", "codec": "png", "bytes": png.stat().st_size,
                     "input": len(pixels), "sxz3-B": len(sxz3)})

    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    for row in rows:
        print(f"{row['item']:<6} {row['codec']:<8} {row['bytes']:>8,} vs SXZ3-B {row['sxz3-B']:>8,} "
              f"({row['bytes'] / row['sxz3-B']:.2f}x)")


if __name__ == "__main__":
    main()
