# SXZ2 streaming and second-pass benchmark

Python 3.13.14, Windows AMD64, zlib 1.3.1.
Deflate level 6, at most 8 heavy probes per generic frame.
32 KiB dictionary bridge: enabled.
All sizes are bytes. Solid zlib is one continuous Deflate stream without framing. The second-pass size is the full candidate; it is discarded unless strictly smaller.
Both compression pass times include I/O to temporary files; the final copy is not included in either individual pass. Decode time is for the chosen archive. Every chosen output is verified byte by byte without reading the file all at once.
Peak RSS is per fresh worker (Python, pack, decode and verification); OS disk caches are not process RSS.

| Input | Input B | Frame KiB / lookback | Solid zlib B | First B | Second B | Kept pass | First / second s | Decode s | Peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| enwik8 | 100000000 | 256 / 4 | 36548921 | 36567849 | 36569007 | 1 | 72.086 / 20.253 | 1.395 | 34.27 |

## Formula scans and container details

| Input | Frame KiB / lookback | First-pass scan s / probes | First-pass formula B | First codecs | Second-pass formula B | Second codecs | Total pack s |
|---|---|---:|---:|---|---:|---|---:|
| enwik8 | 256 / 4 | 40.783 / 3056 | 0 | {'deflate': 1, 'deflate-dict': 381} | 0 | {'raw': 135, 'deflate': 5} | 92.421 |

## Input SHA-256

- `enwik8`: `2b49720ec4d78c3c9fabaee6e4179a5e997302b3a70029f30f2d582218c024a8`
