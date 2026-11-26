"""Measure the size a plain ZIP (Deflate level 1) would need for real folders."""

from __future__ import annotations

import argparse
import json
import time
import zipfile
from pathlib import Path

from sinuxz.folder import inventory


class Counter:
    def __init__(self) -> None:
        self.size = 0

    def write(self, data: bytes) -> int:
        self.size += len(data)
        return len(data)

    def tell(self) -> int:
        return self.size

    def flush(self) -> None:
        pass


def measure(name: str, root: Path, level: int) -> dict:
    entries = inventory(root)
    start = time.perf_counter()
    sink = Counter()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=level, strict_timestamps=False) as archive:
        for entry in entries:
            archive.write(entry.path, entry.name)
    return {"folder": name, "source": str(root), "files": sum(not e.is_dir for e in entries),
            "zip_bytes": sink.size, "seconds": time.perf_counter() - start, "level": level}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", nargs="+", help="name=path")
    parser.add_argument("--level", type=int, choices=range(0, 10), default=1)
    parser.add_argument("--save", type=Path, help="write a Markdown table here")
    parser.add_argument("--json", type=Path, help="write the raw rows here")
    args = parser.parse_args()
    rows = []
    for item in args.folder:
        name, _, path = item.partition("=")
        if not path:
            raise SystemExit("use name=path for every folder")
        row = measure(name, Path(path), args.level)
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    if args.save:
        lines = ["# Plain ZIP baseline for real Windows folders", "",
                 f"Deflate level {args.level}, bytes counted in memory; no archive is kept.",
                 "ZIP bytes include its own headers and directory entries. Times only encode;",
                 "they do not read back or verify the archive.", "",
                 "| Folder | Files | ZIP bytes | Encode seconds |", "|---|---:|---:|---:|"]
        lines += [f"| {r['folder']} | {r['files']} | {r['zip_bytes']} | {r['seconds']:.2f} |" for r in rows]
        args.save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
