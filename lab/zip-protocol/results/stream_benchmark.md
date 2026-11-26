# SXZ2 streaming and second-pass benchmark

Python 3.13.14, Windows AMD64, zlib 1.3.1.
Deflate level 6, at most 8 heavy probes per generic frame.
All sizes are bytes. Solid zlib is one continuous Deflate stream without framing. The second-pass size is the full candidate; it is discarded unless strictly smaller.
Both compression pass times include I/O to temporary files; the final copy is not included in either individual pass. Decode time is for the chosen archive. Every chosen output is verified byte by byte without reading the file all at once.
Peak RSS is per fresh worker (Python, pack, decode and verification); OS disk caches are not process RSS.

| Input | Input B | Frame KiB / lookback | Solid zlib B | First B | Second B | Kept pass | First / second s | Decode s | Peak MiB |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| enwik8 | 100000000 | 1024 / 4 | 36548921 | 36653107 | 36653273 | 1 | 39.212 / 12.157 | 1.256 | 40.68 |
| enwik8.zip | 36445475 | 1024 / 4 | 36454525 | 36445574 | 36446057 | 1 | 12.702 / 9.758 | 0.120 | 40.23 |
| attention.pdf | 2215244 | 1024 / 4 | 1139396 | 1139545 | 1123804 | 2 | 0.732 / 0.406 | 0.035 | 36.42 |
| mshtml.dll | 24031232 | 1024 / 4 | 10080591 | 10092243 | 10064782 | 2 | 9.747 / 3.449 | 0.402 | 46.42 |
| ffmpeg.exe | 227823104 | 1024 / 4 | 88723107 | 88856514 | 88249158 | 2 | 92.151 / 22.248 | 2.883 | 47.75 |
| music.wav | 10841388 | 1024 / 4 | 9844970 | 4654733 | 4650138 | 2 | 23.354 / 2.216 | 7.393 | 41.68 |
| photo-montage.ppm | 9437201 | 1024 / 4 | 7623708 | 4935145 | 4935238 | 1 | 18.562 / 2.595 | 11.959 | 40.65 |
| flights-200k.json | 9863892 | 1024 / 4 | 906348 | 908116 | 908157 | 1 | 2.269 / 0.423 | 0.075 | 38.56 |
| music.ogg | 1452719 | 1024 / 4 | 1428468 | 1428519 | 1428573 | 1 | 0.486 / 0.510 | 0.020 | 36.50 |
| random-64MiB.bin | 67108864 | 1024 / 4 | 67129345 | 67109724 | 67110597 | 1 | 31.288 / 27.990 | 0.263 | 38.61 |
| repeated-32MiB.bin | 33554432 | 1024 / 4 | 147050 | 5693 | 831 | 2 | 0.318 / 0.012 | 0.079 | 35.79 |
| repeated-32MiB.bin | 33554432 | 1024 / 0 | 147050 | 167420 | 1389 | 2 | 8.716 / 0.071 | 0.168 | 34.09 |
| math-in-noise-32MiB.bin | 33554432 | 1024 / 4 | 33556753 | 33284733 | 33285177 | 1 | 14.296 / 16.907 | 1.206 | 42.32 |
| enwik8 | 100000000 | 256 / 4 | 36548921 | 36966886 | 36968072 | 1 | 69.869 / 24.025 | 1.855 | 34.26 |
| enwik8 | 100000000 | 4096 / 4 | 36548921 | 36573847 | 36573992 | 1 | 59.206 / 14.869 | 1.251 | 68.16 |

## Formula scans and container details

| Input | Frame KiB / lookback | First-pass scan s / probes | First-pass formula B | First codecs | Second-pass formula B | Second codecs | Total pack s |
|---|---|---:|---:|---|---:|---|---:|
| enwik8 | 1024 / 4 | 26.441 / 768 | 0 | {'deflate': 96} | 0 | {'raw': 34, 'deflate': 1} | 51.421 |
| enwik8.zip | 1024 / 4 | 9.784 / 280 | 0 | {'raw': 32, 'deflate': 3} | 0 | {'raw': 35} | 22.511 |
| attention.pdf | 1024 / 4 | 0.595 / 24 | 0 | {'deflate': 3} | 0 | {'deflate': 2} | 1.144 |
| mshtml.dll | 1024 / 4 | 6.276 / 184 | 768 | {'deflate': 21, 'sxz1': 2} | 0 | {'raw': 6, 'deflate': 4} | 13.212 |
| ffmpeg.exe | 1024 / 4 | 58.827 / 1744 | 16326 | {'deflate': 208, 'sxz1': 10} | 0 | {'deflate': 68, 'raw': 17} | 114.498 |
| music.wav | 1024 / 4 | 0.005 / 4 | 0 | {'raw': 1, 'pcm': 11} | 0 | {'deflate': 4, 'raw': 1} | 25.583 |
| photo-montage.ppm | 1024 / 4 | 0.002 / 1 | 0 | {'raw': 1, 'pnm': 10} | 0 | {'raw': 5} | 21.174 |
| flights-200k.json | 1024 / 4 | 1.879 / 80 | 0 | {'deflate': 10} | 0 | {'raw': 1} | 2.698 |
| music.ogg | 1024 / 4 | 0.372 / 16 | 0 | {'deflate': 2} | 0 | {'raw': 2} | 1.003 |
| random-64MiB.bin | 1024 / 4 | 24.976 / 512 | 0 | {'raw': 64} | 0 | {'raw': 65} | 59.411 |
| repeated-32MiB.bin | 1024 / 4 | 0.229 / 8 | 0 | {'deflate': 1, 'copy': 31} | 0 | {'deflate': 1} | 0.333 |
| repeated-32MiB.bin | 1024 / 0 | 8.265 / 256 | 0 | {'deflate': 32} | 0 | {'deflate': 1} | 8.790 |
| math-in-noise-32MiB.bin | 1024 / 4 | 11.088 / 256 | 266144 | {'raw': 30, 'sxz1': 2} | 0 | {'raw': 32} | 31.270 |
| enwik8 | 256 / 4 | 51.289 / 3056 | 0 | {'deflate': 382} | 0 | {'raw': 137, 'deflate': 5} | 94.039 |
| enwik8 | 4096 / 4 | 39.532 / 192 | 0 | {'deflate': 24} | 0 | {'raw': 9} | 74.146 |

## Input SHA-256

- `enwik8`: `2b49720ec4d78c3c9fabaee6e4179a5e997302b3a70029f30f2d582218c024a8`
- `enwik8.zip`: `547994d9980ebed1288380d652999f38a14fe291a6247c157c3d33d4932534bc`
- `attention.pdf`: `bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697`
- `mshtml.dll`: `61ec67599957ba9284fedfe7cffc9c637d21f3af7bdf384c1ce14d8c9fd35375`
- `ffmpeg.exe`: `589e50b766d251afdf181dd664d40bd94407e200b019989fd7468c7d118a28d0`
- `music.wav`: `783e5d7412beb8c3ac8acb3f91c1360953fb3e9e37f2798b4559a769aece95dd`
- `photo-montage.ppm`: `f2debfb5b296009fb6bc53e77238ae977cb1e7d2d2e732ff5d3533d23136cbe9`
- `flights-200k.json`: `82c60682ccdec1a9cf1102b2a011bef789243053f1ac01a531580c72be3d8bc0`
- `music.ogg`: `73d6443ef90a7c022f164e5aa90e56c2291585930b39b1656d0765abbc1f1779`
- `random-64MiB.bin`: `97a6433f870f51b240218a1a570fefdc1a955c9dd04ef0ed7618f5168961ba82`
- `repeated-32MiB.bin`: `b2001f9db9983c68329b24bf1bc8b5596a11496202c8875803c49a3dfa1d6389`
- `math-in-noise-32MiB.bin`: `d538d5b0d4df771b0d69e75802b4ca53b6e46fc61cb76b3f98f5d17c6ff77327`
