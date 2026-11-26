# SXZ4 full corpus (39 items)

Every archive is decoded and compared byte for byte. Sizes include all headers.
Encode times are wall-clock seconds on one machine and are indicative only.

## synthetic (20 files, 4,984,831 B)

| Method | Total B | Ratio | Encode s | Decode s |
|---|---:|---:|---:|---:|
| `deflate-6` | 3,483,670 | 69.89% | 0.3 | 0.0 |
| `zstd-19` | 3,218,395 | 64.56% | 0.6 | 0.0 |
| `xz-6` | 2,889,028 | 57.96% | 1.2 | 0.2 |
| `brotli-11` | 3,037,843 | 60.94% | 8.7 | 0.0 |
| `sxz2` | 3,484,049 | 69.89% | 0.3 | 0.0 |
| `sxz3-B` | 1,689,295 | 33.89% | 23.4 | 0.6 |
| `sxz4-off` | 3,484,290 | 69.90% | 0.3 | 0.0 |
| `sxz4-tx` | 1,439,655 | 28.88% | 0.8 | 0.5 |
| `sxz4-on` | 255,058 | 5.12% | 144.0 | 0.9 |
| `sxz4-prog` | 255,058 | 5.12% | 156.5 | 0.9 |

## real (16 files, 3,279,152 B)

| Method | Total B | Ratio | Encode s | Decode s |
|---|---:|---:|---:|---:|
| `deflate-6` | 1,730,014 | 52.76% | 0.2 | 0.0 |
| `zstd-19` | 1,623,242 | 49.50% | 0.7 | 0.0 |
| `xz-6` | 1,517,932 | 46.29% | 0.8 | 0.1 |
| `brotli-11` | 1,521,213 | 46.39% | 6.2 | 0.0 |
| `sxz2` | 1,730,670 | 52.78% | 0.2 | 0.0 |
| `sxz3-B` | 1,730,423 | 52.77% | 8.6 | 0.0 |
| `sxz4-off` | 1,730,510 | 52.77% | 0.2 | 0.0 |
| `sxz4-tx` | 1,535,410 | 46.82% | 0.4 | 0.1 |
| `sxz4-on` | 1,535,410 | 46.82% | 36.7 | 0.1 |
| `sxz4-prog` | 1,535,410 | 46.82% | 39.9 | 0.1 |

## precompressed (3 files, 786,432 B)

| Method | Total B | Ratio | Encode s | Decode s |
|---|---:|---:|---:|---:|
| `deflate-6` | 786,690 | 100.03% | 0.0 | 0.0 |
| `zstd-19` | 786,477 | 100.01% | 0.0 | 0.0 |
| `xz-6` | 786,648 | 100.03% | 0.2 | 0.0 |
| `brotli-11` | 786,447 | 100.00% | 0.2 | 0.0 |
| `sxz2` | 786,555 | 100.02% | 0.0 | 0.0 |
| `sxz3-B` | 786,777 | 100.04% | 2.1 | 0.0 |
| `sxz4-off` | 786,783 | 100.04% | 0.0 | 0.0 |
| `sxz4-tx` | 786,783 | 100.04% | 0.0 | 0.0 |
| `sxz4-on` | 786,783 | 100.04% | 5.9 | 0.0 |
| `sxz4-prog` | 786,783 | 100.04% | 5.9 | 0.0 |

## Held-out files

| File | Cat | Deflate | zstd-19 | xz-6 | brotli-11 | SXZ4-tx | SXZ4-on | vs best |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| eeg-holdout | real | 65,038 | 56,743 | 55,512 | 57,992 | 65,069 | 65,069 | +17.22% |
| ecg-holdout | real | 155,423 | 141,236 | 116,004 | 122,188 | 93,789 | 93,789 | -19.15% |
| text-holdout | real | 91,600 | 81,593 | 78,768 | 73,555 | 91,631 | 91,631 | +24.57% |
| weights-holdout | real | 240,040 | 238,888 | 240,952 | 238,130 | 240,071 | 240,071 | +0.82% |

## Per file

| File | Cat | In | Best external | Method | SXZ4-tx | SXZ4-on | spans | modelled | chain | models |
|---|---|---:|---:|---|---:|---:|---:|---:|---|---|
| order2-u32 | synt | 262,144 | 262,149 | `brotli-11` | 195,550 | 84 | 1 | 262,144 | [0] | order2-word:1 |
| order2-u64 | synt | 262,144 | 261,248 | `xz-6` | 227,587 | 81 | 1 | 262,144 | [0] | order2-word:1 |
| cross-3x-u16 | synt | 262,144 | 246,316 | `xz-6` | 2,199 | 445 | 3 | 262,144 | [6, 2] | period-bytes:3 |
| cross-4x-u16 | synt | 262,144 | 252,152 | `xz-6` | 528 | 155 | 1 | 262,144 | [4] | period-bytes:1 |
| piecewise | synt | 262,144 | 240,604 | `xz-6` | 131,681 | 1,521 | 2 | 262,144 | [0] | affine-word:1, order2-word:1 |
| gorilla-ts | synt | 262,144 | 53,588 | `xz-6` | 26,027 | 25,117 | 1 | 197,838 | [8, 1] | period-bytes:1 |
| random-walk-f32 | synt | 262,144 | 139,384 | `xz-6` | 124,313 | 124,313 | 1 | 68,224 | [7, 1] | period-bytes:1 |
| csv-numeric | synt | 262,144 | 42,344 | `xz-6` | 68,444 | 68,444 | 0 | 0 | [0] |  |
| float64-ramp | synt | 262,144 | 138,625 | `zstd-19` | 17,684 | 17,684 | 26 | 162,432 | [8, 1] | lcg-word:24, xor-rotate:1, period-bytes:1 |
| xorshift-5-17-13 | synt | 262,144 | 262,149 | `brotli-11` | 262,261 | 71 | 1 | 262,144 | [0] | xorshift-any:1 |
| affine-u24be | synt | 262,143 | 55,340 | `xz-6` | 1,122 | 153 | 2 | 262,143 | [6, 1] | period-bytes:2 |
| order2-u32-noise3 | synt | 262,144 | 260,036 | `xz-6` | 202,696 | 15,296 | 1 | 262,144 | [0] | order2-word:1 |
| ramp-u16le | synt | 262,144 | 68,257 | `brotli-11` | 314 | 71 | 1 | 262,144 | [0] | affine-word:1 |
| quadratic-u16le | synt | 262,144 | 262,149 | `brotli-11` | 23,246 | 73 | 1 | 262,144 | [0] | quadratic-word:1 |
| lfsr16 | synt | 262,144 | 98 | `zstd-19` | 895 | 71 | 1 | 262,144 | [0] | lfsr:1 |
| lcg32 | synt | 262,144 | 262,149 | `brotli-11` | 148,471 | 79 | 1 | 262,144 | [0] | lcg-word:1 |
| composite-sum | synt | 262,144 | 4,364 | `xz-6` | 736 | 276 | 1 | 262,144 | [0] | affine-word:1 |
| float32-ramp | synt | 262,144 | 30,852 | `xz-6` | 1,439 | 981 | 1 | 197,504 | [7, 1] | period-bytes:1 |
| pi-4096 | synt | 4,096 | 4,100 | `brotli-11` | 4,138 | 67 | 1 | 4,096 | [0] | reference-slice:1 |
| lanes-4x-u8 | synt | 262,144 | 1,043 | `brotli-11` | 324 | 76 | 1 | 262,144 | [0] | lanes-word:1 |
| eeg-train | real | 262,144 | 55,292 | `xz-6` | 65,138 | 65,138 | 0 | 0 | [0] |  |
| eeg-holdout | real | 262,144 | 55,512 | `xz-6` | 65,069 | 65,069 | 0 | 0 | [0] |  |
| ecg-train | real | 262,144 | 118,172 | `xz-6` | 92,944 | 92,944 | 1 | 40,064 | [6, 1] | period-bytes:1 |
| ecg-holdout | real | 262,144 | 116,004 | `xz-6` | 93,789 | 93,789 | 0 | 0 | [6, 1] |  |
| weather_melbourne | real | 65,536 | 9,208 | `xz-6` | 13,476 | 13,476 | 0 | 0 | [5] |  |
| finance_apple | real | 60,220 | 17,493 | `brotli-11` | 21,038 | 21,038 | 0 | 0 | [0] |  |
| apple_stock | real | 5,488 | 1,515 | `brotli-11` | 1,985 | 1,985 | 0 | 0 | [21] |  |
| airline_passengers | real | 2,180 | 403 | `brotli-11` | 612 | 612 | 0 | 0 | [6] |  |
| text-train | real | 262,144 | 78,290 | `brotli-11` | 95,566 | 95,566 | 0 | 0 | [0] |  |
| text-holdout | real | 262,144 | 73,555 | `brotli-11` | 91,631 | 91,631 | 0 | 0 | [0] |  |
| weights-train | real | 262,144 | 236,145 | `brotli-11` | 238,680 | 238,680 | 0 | 0 | [0] |  |
| weights-holdout | real | 262,144 | 238,130 | `brotli-11` | 240,071 | 240,071 | 0 | 0 | [0] |  |
| wav-train | real | 262,144 | 197,657 | `brotli-11` | 162,505 | 162,505 | 0 | 0 | [5, 11] |  |
| ppm-train | real | 262,144 | 67,356 | `xz-6` | 84,224 | 84,224 | 0 | 0 | [6, 1] |  |
| exe-train | real | 262,144 | 139,976 | `xz-6` | 160,929 | 160,929 | 0 | 0 | [0] |  |
| tar-train | real | 262,144 | 93,764 | `xz-6` | 107,753 | 107,753 | 0 | 0 | [0] |  |
| flac-slice | prec | 262,144 | 262,149 | `brotli-11` | 262,261 | 262,261 | 0 | 0 | [0] |  |
| jpeg-slice | prec | 262,144 | 262,149 | `brotli-11` | 262,261 | 262,261 | 0 | 0 | [0] |  |
| zip-slice | prec | 262,144 | 262,149 | `brotli-11` | 262,261 | 262,261 | 0 | 0 | [0] |  |

## Files where the span engine beats transforms-only by >0.5%

| File | tx | on | gain |
|---|---:|---:|---:|
| order2-u32 | 195,550 | 84 | 100.0% |
| order2-u64 | 227,587 | 81 | 100.0% |
| cross-3x-u16 | 2,199 | 445 | 79.8% |
| cross-4x-u16 | 528 | 155 | 70.6% |
| piecewise | 131,681 | 1,521 | 98.8% |
| gorilla-ts | 26,027 | 25,117 | 3.5% |
| xorshift-5-17-13 | 262,261 | 71 | 100.0% |
| affine-u24be | 1,122 | 153 | 86.4% |
| order2-u32-noise3 | 202,696 | 15,296 | 92.5% |
| ramp-u16le | 314 | 71 | 77.4% |
| quadratic-u16le | 23,246 | 73 | 99.7% |
| lfsr16 | 895 | 71 | 92.1% |
| lcg32 | 148,471 | 79 | 99.9% |
| composite-sum | 736 | 276 | 62.5% |
| float32-ramp | 1,439 | 981 | 31.8% |
| pi-4096 | 4,138 | 67 | 98.4% |
| lanes-4x-u8 | 324 | 76 | 76.5% |

## What the engine selected

- models: {'order2-word': 4, 'period-bytes': 11, 'affine-word': 3, 'lcg-word': 25, 'xor-rotate': 1, 'xorshift-any': 1, 'quadratic-word': 1, 'lfsr': 1, 'reference-slice': 1, 'lanes-word': 1}
- residual modes: {'exact': 11, 'exceptions': 12, 'xor': 1, 'moddiff': 25}
- transform chains: {'[0]': 25, '[6, 2]': 1, '[4]': 1, '[8, 1]': 2, '[7, 1]': 2, '[6, 1]': 4, '[5]': 1, '[21]': 1, '[6]': 1, '[5, 11]': 1}

