# SXZ2 streaming and second-pass benchmark

Python 3.13.14, Windows AMD64, zlib 1.3.1.
Deflate level 6, at most 8 heavy probes per generic frame.
32 KiB dictionary bridge: enabled.
All sizes are bytes. Solid zlib is one continuous Deflate stream without framing. The second-pass size is the full candidate; it is discarded unless strictly smaller.
Both compression pass times include I/O to temporary files; the final copy is not included in either individual pass. Decode time is for the chosen archive. Every chosen output is verified byte by byte without reading the file all at once.
Peak RSS is per fresh worker (Python, pack, decode and verification); OS disk caches are not process RSS.

| Input | Input B | Frame KiB / lookback | Solid zlib B | First B | Second B | Kept pass | First / second s | Decode s | Peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| flights-200k.json | 9863892 | 256 / 4 | 906348 | 907596 | 907676 | 1 | 2.194 / 0.226 | 0.034 | 34.70 |

## Formula scans and container details

| Input | Frame KiB / lookback | First-pass scan s / probes | First-pass formula B | First codecs | Second-pass formula B | Second codecs | Total pack s |
|---|---|---:|---:|---|---:|---|---:|
| flights-200k.json | 256 / 4 | 1.661 / 304 | 0 | {'deflate': 1, 'deflate-dict': 37} | 0 | {'raw': 4} | 2.422 |

## Input SHA-256

- `flights-200k.json`: `82c60682ccdec1a9cf1102b2a011bef789243053f1ac01a531580c72be3d8bc0`
