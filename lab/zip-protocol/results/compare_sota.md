# Where the ceiling is: published numbers

Local measurements in [compare_codecs.md](compare_codecs.md) cover tools that can
finish a 100–135 MB input in minutes. The very strongest compressors cannot, so
this page records their published results for context. All enwik8 rows are the
first 100,000,000 bytes of English Wikipedia.

## enwik8 (100 MB of text)

| Method | Family | Compressed B | Ratio | Time |
|---|---|---:|---:|---:|
| Nacrith 2026.03 | neural, 2026 | 11,737,280 | 11.7% | not published |
| ts_zip 2026.03 | LLM-based | 13,875,000 | 13.9% | not published |
| cmix v21 | context mixing | 14,625,000 | 14.6% | 65,155 s |
| NNCP 2026.02 | neural | 14,915,298 | 14.9% | not published |
| paq8px -12L | context mixing | 15,875,000 | 15.9% | 18.8 min for 11 MB text |
| xz -9 | LZMA2 | 24,862,392 | 24.9% | minutes |
| Brotli -q 11 | Brotli | 25,738,596 | 25.7% | minutes |
| zstd -19 | Zstandard | 26,949,726 | 27.0% | tens of seconds |
| bzip2 -9 | BWT | 29,008,758 | 29.0% | tens of seconds |
| gzip -9 | Deflate | 36,445,248 | 36.4% | seconds |

Sources: the enwik8 leaderboard at sota2.com, the cmix benchmark page, and the
paq8px release notes.

## Why they are not in the local table

paq8px v217 was installed and run here on 4 MiB of the same enwik8 file at level
6. After 475 seconds it had reached 72%, which is about **6.3 KB/s**. At that
rate the full 100 MB would need roughly 4.5 hours, and cmix is slower still
(65,155 s for the same file, about 32 GB of RAM recommended). Those tools are
research instruments for measuring entropy, not archive formats for a working
folder.

## Mixed real-world corpora

An independent 2026 benchmark of 55 MB of mixed text, office documents, images
and video reported these full-corpus ratios:

| Format | Level | Ratio |
|---|---|---:|
| zpaq | max | 56.11% |
| 7-Zip (LZMA2) | max | 59.96% |
| tar.xz (LZMA2) | max | 59.98% |
| tar.zst | max | 61.33% |
| tar.br | default | 65.00% |
| RAR 5 | max | 78.09% |
| ZIP | max | 81.87% |
| tar.gz | max | 81.92% |
| LZ4 | max | 84.45% |

That ordering is the practical one: context mixing wins by a few points, LZMA2
is the best ratio that finishes quickly, and Zstandard trades a little ratio for
a large speed win. Already-compressed media barely moves under any of them.
