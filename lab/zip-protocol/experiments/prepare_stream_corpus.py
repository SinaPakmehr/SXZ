"""Fetch and verify the public text, ZIP and PDF files used for SXZ2 tests."""

import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO
from urllib.request import Request, urlopen

MIB = 1 << 20
SOURCES = (
    ("enwik8.zip", "https://mattmahoney.net/dc/enwik8.zip", 60 * MIB,
     "547994d9980ebed1288380d652999f38a14fe291a6247c157c3d33d4932534bc"),
    ("attention.pdf", "https://arxiv.org/pdf/1706.03762", 10 * MIB,
     "bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697"),
)
TEXT_SHA = "2b49720ec4d78c3c9fabaee6e4179a5e997302b3a70029f30f2d582218c024a8"


def checked_copy(src: BinaryIO, digest: str, limit: int, dst: BinaryIO | None = None) -> int:
    hash_ = hashlib.sha256()
    total = 0
    while data := src.read(MIB):
        total += len(data)
        if total > limit:
            raise ValueError("source exceeds limit")
        hash_.update(data)
        if dst is not None:
            dst.write(data)
    if hash_.hexdigest() != digest:
        raise ValueError("source SHA-256 did not match")
    return total


def save_checked(src: BinaryIO, path: Path, digest: str, limit: int) -> None:
    with tempfile.TemporaryFile(dir=path.parent) as pending:
        checked_copy(src, digest, limit, pending)
        pending.seek(0)
        with path.open("xb") as dst:
            shutil.copyfileobj(pending, dst, MIB)


def prepare(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, url, limit, digest in SOURCES:
        path = out / name
        if path.exists():
            with path.open("rb") as src:
                checked_copy(src, digest, limit)
        else:
            req = Request(url, headers={"User-Agent": "SXZ research benchmark/0.1"})
            with urlopen(req, timeout=90) as src:
                save_checked(src, path, digest, limit)
    path = out / "enwik8"
    if path.exists():
        with path.open("rb") as src:
            checked_copy(src, TEXT_SHA, 100_000_000)
    else:
        with zipfile.ZipFile(out / "enwik8.zip") as zip_:
            info = zip_.getinfo("enwik8")
            if len(zip_.infolist()) != 1 or info.file_size != 100_000_000:
                raise ValueError("unexpected enwik8 ZIP layout")
            with zip_.open(info) as src:
                save_checked(src, path, TEXT_SHA, 100_000_000)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.out)
    print(f"Verified enwik8, enwik8.zip and attention.pdf in {args.out}")


if __name__ == "__main__":
    main()
