# SXZ2 streaming and second-pass benchmark

Python 3.13.14, Windows AMD64, zlib 1.3.1.
Deflate level 6, at most 0 heavy probes per generic frame.
32 KiB dictionary bridge: disabled.
All sizes are bytes. Solid zlib is one continuous Deflate stream without framing. The second-pass size is the full candidate; it is discarded unless strictly smaller.
Both compression pass times include I/O to temporary files; the final copy is not included in either individual pass. Decode time is for the chosen archive. Every chosen output is verified byte by byte without reading the file all at once.
Peak RSS is per fresh worker (Python, pack, decode and verification); OS disk caches are not process RSS.

| Input | Input B | Frame KiB / lookback | Solid zlib B | First B | Second B | Kept pass | First / second s | Decode s | Peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| ffmpeg.exe | 227823104 | 1024 / 4 | 88723107 | 88862816 | 88252344 | 2 | 39.747 / 10.374 | 4.458 | 39.21 |
| enwik8.zip | 36445475 | 1024 / 4 | 36454525 | 36445574 | 36446057 | 1 | 4.057 / 4.003 | 0.196 | 39.30 |

## Formula scans and container details

| Input | Frame KiB / lookback | First-pass scan s / probes | First-pass formula B | First codecs | Second-pass formula B | Second codecs | Total pack s |
|---|---|---:|---:|---|---:|---|---:|
| ffmpeg.exe | 1024 / 4 | 0.000 / 0 | 0 | {'deflate': 218} | 0 | {'deflate': 68, 'raw': 17} | 50.363 |
| enwik8.zip | 1024 / 4 | 0.000 / 0 | 0 | {'raw': 32, 'deflate': 3} | 0 | {'raw': 35} | 8.166 |

## Input SHA-256

- `ffmpeg.exe`: `589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0`
- `enwik8.zip`: `547994d9980ebed1288380d652999f38a14fe291a6247c157c3d33d4932534bc`
