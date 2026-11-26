"""Restore a pack-folder archive and byte-compare every file with the source."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path

from sinuxz.folder import inventory, restore_folder


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--keep", type=Path, help="restore here instead of a temporary directory")
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    expected = {e.name: e for e in inventory(root)}
    with tempfile.TemporaryDirectory(dir=args.keep or None, prefix="sxz-restore-check-") as tmp:
        target = args.keep / f"{root.name}-restored" if args.keep else Path(tmp) / "restored"
        start = time.perf_counter()
        report = restore_folder(args.archive, target)
        seconds = time.perf_counter() - start
        checked = 0
        for name, entry in expected.items():
            item = target.joinpath(*Path(name).parts)
            if entry.is_dir:
                if not item.is_dir():
                    raise ValueError(f"missing directory after restore: {name}")
                continue
            if item.stat().st_size != entry.info.st_size or digest(item) != digest(entry.path):
                raise ValueError(f"restored bytes differ: {name}")
            checked += 1
        extra = {p.relative_to(target).as_posix() for p in target.rglob("*")}
        if extra != set(expected):
            raise ValueError("restored tree contains unexpected or missing names")
    result = {"source": str(root), "archive": str(args.archive), "files": checked,
              "restore_seconds": seconds, "restored_bytes": report["tar_bytes"]}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
