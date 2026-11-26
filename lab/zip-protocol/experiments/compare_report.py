"""Turn compare_codecs.json into Markdown tables and gap summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ORDER = ["sxz2-fast", "sxz2-tuned", "sxz2-best", "gzip-9", "bzip2-9", "zstd-3", "zstd-19",
         "zstd-22", "brotli-9", "brotli-11", "xz-6", "xz-9e", "7z-lzma2-9", "zpaq-m5"]

CORPORA = ["enwik8", "desktop-mixed", "music-mixed", "model-weights"]

DESCRIPTION = {
    "sxz2-fast": "SXZ2 4 MiB / Deflate 1 / scan off",
    "sxz2-tuned": "SXZ2 1 MiB / Deflate 6 / scan 8 / bridge",
    "sxz2-best": "SXZ2 1 MiB / Deflate 9 / scan 16 / bridge / 2nd pass",
    "gzip-9": "zlib level 9, 32 KiB window",
    "bzip2-9": "BWT, block 900k",
    "zstd-3": "Zstandard, fast default",
    "zstd-19": "Zstandard high",
    "zstd-22": "Zstandard ultra, 14 threads",
    "brotli-9": "Brotli quality 9",
    "brotli-11": "Brotli quality 11",
    "xz-6": "LZMA2 preset 6, one thread",
    "xz-9e": "LZMA2 preset 9 extreme, one thread",
    "7z-lzma2-9": "7-Zip LZMA2 max, 14 threads",
    "zpaq-m5": "zpaq maximum method, PAQ family",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=Path("results/compare_codecs.json"))
    parser.add_argument("--save", type=Path, default=Path("results/compare_codecs.md"))
    args = parser.parse_args()
    rows = json.loads(args.json.read_text(encoding="utf-8"))["rows"]
    by = {(r["corpus"], r["codec"]): r for r in rows}
    corpora = [c for c in CORPORA if any(k[0] == c for k in by)]

    lines = ["# SXZ2 against the strongest general-purpose compressors", "",
             "The same bytes are given to every tool. Each result was decompressed and",
             "SHA-256 compared with the input; sizes include each format's own headers.",
             "Times are wall clock on one laptop, external tools include process start-up,",
             "and multi-threaded rows used all 14 logical CPUs. `MB/s` is input size divided",
             "by encode or decode seconds.", "",
             "| Codec | Setting |",
             "|---|---|"]
    for codec in ORDER:
        if any(k[1] == codec for k in by):
            lines.append(f"| `{codec}` | {DESCRIPTION.get(codec, '')} |")
    lines.append("")

    for corpus in corpora:
        source = next(by[(corpus, codec)]["source_bytes"] for codec in ORDER if (corpus, codec) in by)
        lines += ["", f"## {corpus} ({source:,} bytes)", "",
                  "| Codec | Bytes | Ratio | Encode s | Encode MB/s | Decode s | Decode MB/s | vs best |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|"]
        present = [by[(corpus, c)] for c in ORDER if (corpus, c) in by]
        best = min(r["bytes"] for r in present)
        for codec in ORDER:
            row = by.get((corpus, codec))
            if not row:
                continue
            lines.append(f"| `{codec}` | {row['bytes']:,} | {row['ratio']:.2%} | "
                         f"{row['encode']:.2f} | {source / row['encode'] / 1e6:.1f} | "
                         f"{row['decode']:.2f} | {source / row['decode'] / 1e6:.1f} | "
                         f"{row['bytes'] / best - 1:+.2%} |")
    args.save.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
