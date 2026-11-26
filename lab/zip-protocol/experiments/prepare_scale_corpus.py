"""Prepare public audio/data and local photographs for the scaling benchmark."""

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen

AUDIO_URL = "https://librosa.org/data/audio/"
SOURCES = {
    "speech.ogg": (AUDIO_URL + "5703-47212-0000.hq.ogg",
                   "f09254a0daf4b14b292868d46dc2e3c8e158d19fafff739ad4c3931e2ce7b1b0"),
    "music.ogg": (AUDIO_URL + "Kevin_MacLeod_-_Vibe_Ace.hq.ogg",
                  "73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779"),
    "whale.ogg": (AUDIO_URL + "glacier-bay-humpback.hq.ogg",
                  "c3250ff526898aa5528aeb6b81a49aff58f63400ec2ddb8bcb86caf611d33144"),
    "flights-200k.json": ("https://raw.githubusercontent.com/vega/vega-datasets/main/data/flights-200k.json",
                          "82c60682ccdec1a9cf1102b2a011bef789243053f1ac01a531580c72be3d8bc0"),
}


def public_sources(out: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required to prepare the three WAV files")
    for name, (url, digest) in SOURCES.items():
        path = out / name
        limit = 40 * 1024 * 1024
        if path.exists():
            with path.open("rb") as src:
                data = src.read(limit + 1)
        else:
            with urlopen(url, timeout=75) as src:
                data = src.read(limit + 1)
        if len(data) > limit or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"source digest mismatch: {name}")
        if not path.exists():
            with path.open("xb") as dst:
                dst.write(data)
        if path.suffix == ".ogg":
            wav = path.with_suffix(".wav")
            if not wav.exists():
                subprocess.run([
                    ffmpeg, "-nostdin", "-v", "error", "-n", "-i", str(path), "-map", "0:a:0",
                    "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:a", "+bitexact",
                    "-c:a", "pcm_s16le", str(wav),
                ], check=True, timeout=120)


def photos(out: Path, images: Path) -> None:
    from PIL import Image, ImageOps

    for name in ("hubble_deep_field.jpg", "motorcycle_left.png"):
        path = out / Path(name).with_suffix(".ppm")
        if not path.exists():
            with Image.open(images / name) as source, path.open("xb") as dst:
                source.convert("RGB").save(dst, format="PPM")

    path = out / "photo-montage.ppm"
    if not path.exists():
        names = ("astronaut.png", "hubble_deep_field.jpg", "coffee.png", "motorcycle_left.png")
        montage = Image.new("RGB", (2048, 1536))
        for i, name in enumerate(names):
            with Image.open(images / name) as source:
                tile = ImageOps.fit(source.convert("RGB"), (1024, 768), Image.Resampling.LANCZOS)
                montage.paste(tile, (1024 * (i % 2), 768 * (i // 2)))
        with path.open("xb") as dst:
            montage.save(dst, format="PPM")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fetch-public", action="store_true", help="download pinned public inputs, then decode PCM")
    parser.add_argument("--images", type=Path, help="path to a scikit-image data directory; requires Pillow")
    args = parser.parse_args()
    if not (args.fetch_public or args.images):
        parser.error("select --fetch-public and/or --images")
    args.out.mkdir(parents=True, exist_ok=True)
    if args.fetch_public:
        public_sources(args.out)
    if args.images:
        photos(args.out, args.images)
    print(args.out)


if __name__ == "__main__":
    main()
