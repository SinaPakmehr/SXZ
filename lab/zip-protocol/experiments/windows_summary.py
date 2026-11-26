"""Merge pack-folder JSON reports and a ZIP baseline into one Markdown table."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ORDER = ["desktop", "music-lessons", "music", "openvino-int4"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outputs", type=Path, help="directory containing <folder>.json")
    parser.add_argument("--zip", type=Path, help="JSON written by windows_zip_baseline.py --json")
    parser.add_argument("--save", type=Path, default=Path("results/windows_folders.md"))
    args = parser.parse_args()
    rows = []
    for name in ORDER:
        path = args.outputs / f"{name}.json"
        if path.exists():
            row = json.loads(path.read_text(encoding="utf-8"))
            row["folder"] = name
            rows.append(row)
    if not rows:
        raise SystemExit(f"no folder reports in {args.outputs}")
    zips = {row["folder"]: row for row in json.loads(args.zip.read_text(encoding="utf-8"))} \
        if args.zip and args.zip.exists() else {}
    lines = ["# SXZ2 on complete Windows folders", "",
             "Each folder was streamed straight into PAX TAR and SXZ2 (4 MiB frames, Deflate level 1,",
             "formula scan off, fast sampling on), then the whole archive was decoded again and its",
             "TAR SHA-256 compared with the bytes produced during packing. `pack` and `verify` are",
             "wall-clock seconds; a restore to disk was measured separately. Runs shared one SSD, so",
             "they are not isolated-disk numbers. ZIP is Deflate level 1 encoded into a byte counter",
             "with the same files, without reading or verifying the result; it was measured for the",
             "two smaller folders only.", "",
             "| Folder | Files | Input GiB | Archive B | Saved | Pack s | Verify s | ZIP B | ZIP s | vs ZIP |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        zip_row = zips.get(row.get("folder"))
        if "archive_bytes" not in row:
            continue
        saved = 1 - row["archive_bytes"] / row["input_bytes"]
        text = (f"| {row['folder']} | {row['files']} | {row['input_bytes'] / 2**30:.2f} | "
                f"{row['archive_bytes']} | {saved:.2%} | {row['pack_seconds']:.2f} | "
                f"{row['verify_seconds']:.2f} |")
        if zip_row:
            diff = row["archive_bytes"] / zip_row["zip_bytes"] - 1
            text += f" {zip_row['zip_bytes']} | {zip_row['seconds']:.2f} | {diff:+.2%} |"
        else:
            text += " — | — | — |"
        lines.append(text)
    total_in = sum(r["input_bytes"] for r in rows if "archive_bytes" in r)
    total_out = sum(r["archive_bytes"] for r in rows if "archive_bytes" in r)
    lines.append(f"| **total** | {sum(r['files'] for r in rows)} | {total_in / 2**30:.2f} | "
                 f"**{total_out}** | **{1 - total_out / total_in:.2%}** | "
                 f"{sum(r['pack_seconds'] for r in rows):.2f} | "
                 f"{sum(r['verify_seconds'] for r in rows):.2f} | — | — | — |")
    args.save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
