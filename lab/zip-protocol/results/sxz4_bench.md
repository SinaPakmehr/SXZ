# SXZ4 benchmark

Every output is decoded and compared byte for byte. Sizes include all headers.
SXZ variants share the Deflate-6 backend; zstd/xz are external references.
Categories are reported separately on purpose.

## synthetic (3 files)

| Method | Total B | Ratio | Encode s | Decode s |
|---|---:|---:|---:|---:|
| `deflate-6` | 589,207 | 74.92% | 0.0 | 0.0 |
| `zstd-19` | 571,268 | 72.64% | 0.1 | 0.0 |
| `xz-6` | 550,876 | 70.05% | 0.2 | 0.0 |
| `sxz2` | 589,244 | 74.93% | 0.0 | 0.0 |
| `sxz3-B` | 589,294 | 74.93% | 2.6 | 0.0 |
| `sxz4-off` | 589,300 | 74.93% | 0.0 | 0.0 |
| `sxz4-tx` | 266,193 | 33.85% | 0.1 | 0.1 |
| `sxz4-on` | 68,931 | 8.77% | 7.1 | 0.1 |
| `sxz4-prog` | 68,931 | 8.77% | 7.2 | 0.1 |

## real (4 files)

| Method | Total B | Ratio | Encode s | Decode s |
|---|---:|---:|---:|---:|
| `deflate-6` | 559,260 | 53.34% | 0.1 | 0.0 |
| `zstd-19` | 527,564 | 50.31% | 0.2 | 0.0 |
| `xz-6` | 497,000 | 47.40% | 0.3 | 0.0 |
| `sxz2` | 559,424 | 53.35% | 0.1 | 0.0 |
| `sxz3-B` | 559,376 | 53.35% | 2.8 | 0.0 |
| `sxz4-off` | 559,384 | 53.35% | 0.1 | 0.0 |
| `sxz4-tx` | 492,328 | 46.95% | 0.1 | 0.0 |
| `sxz4-on` | 492,012 | 46.92% | 18.8 | 0.0 |

## precompressed (1 files)

| Method | Total B | Ratio | Encode s | Decode s |
|---|---:|---:|---:|---:|
| `deflate-6` | 262,230 | 100.03% | 0.0 | 0.0 |
| `zstd-19` | 262,159 | 100.01% | 0.0 | 0.0 |
| `xz-6` | 262,216 | 100.03% | 0.1 | 0.0 |
| `sxz2` | 262,185 | 100.02% | 0.0 | 0.0 |
| `sxz3-B` | 262,259 | 100.04% | 0.7 | 0.0 |
| `sxz4-off` | 262,261 | 100.04% | 0.0 | 0.0 |
| `sxz4-tx` | 262,261 | 100.04% | 0.0 | 0.0 |
| `sxz4-on` | 262,261 | 100.04% | 1.8 | 0.0 |

## Per-file (SXZ4-on vs best reference)

| File | Cat | Raw | SXZ4-on | Best ref | Gap | Spans | Modelled | Models |
|---|---|---:|---:|---|---:|---:|---:|---|
| order2-u32 | syn | 262,144 | 84 | zstd-19: 262,159 | -100.0% | 1 | 100% | order2-word×1 |
| cross-3x-u16 | syn | 262,144 | 403 | xz-6: 246,316 | -99.8% | 3 | 100% | period-bytes×3 |
| csv-numeric | syn | 262,144 | 68,444 | xz-6: 42,344 | +61.6% | 0 | 0% | — |
| eeg-train | rea | 262,144 | 65,138 | xz-6: 55,292 | +17.8% | 0 | 0% | — |
| ecg-train | rea | 262,144 | 92,628 | xz-6: 118,172 | -21.6% | 1 | 33% | period-bytes×1 |
| text-train | rea | 262,144 | 95,566 | xz-6: 84,276 | +13.4% | 0 | 0% | — |
| weights-train | rea | 262,144 | 238,680 | zstd-19: 237,420 | +0.5% | 0 | 0% | — |
| flac-slice | pre | 262,144 | 262,261 | zstd-19: 262,159 | +0.0% | 0 | 0% | — |

## Held-out

| File | Cat | zstd-19 | xz-6 | SXZ4-on |
|---|---|---:|---:|---:|

## Transform chains chosen

| File | SXZ4-on chain | SXZ4-tx chain |
|---|---|---|
| order2-u32 | [0] | [9] |
| cross-3x-u16 | [6, 2] | [6, 2] |
| csv-numeric | [0] | [0] |
| eeg-train | [0] | [0] |
| ecg-train | [6, 1] | [6, 1] |
| text-train | [0] | [0] |
| weights-train | [0] | [0] |
| flac-slice | [0] | [0] |
