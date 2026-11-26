# SXZ2 on complete Windows folders

Each folder was streamed straight into PAX TAR and SXZ2 (4 MiB frames, Deflate level 1,
formula scan off, fast sampling on), then the whole archive was decoded again and its
TAR SHA-256 compared with the bytes produced during packing. `pack` and `verify` are
wall-clock seconds; a restore to disk was measured separately. Runs shared one SSD, so
they are not isolated-disk numbers. ZIP is Deflate level 1 encoded into a byte counter
with the same files, without reading or verifying the result; it was measured for the
two smaller folders only.

| Folder | Files | Input GiB | Archive B | Saved | Pack s | Verify s | ZIP B | ZIP s | vs ZIP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| desktop | 405 | 2.05 | 2005814320 | 8.96% | 31.51 | 8.83 | 2001724778 | 114.47 | +0.20% |
| music-lessons | 446 | 3.52 | 3607852419 | 4.56% | 68.99 | 13.85 | 3600120401 | 252.18 | +0.21% |
| music | 3831 | 25.02 | 26255160351 | 2.25% | 975.94 | 135.92 | — | — | — |
| openvino-int4 | 230 | 8.54 | 8195042347 | 10.58% | 559.85 | 115.41 | — | — | — |
| **total** | 4912 | 39.12 | **40063869437** | **4.63%** | 1636.30 | 274.00 | — | — | — |
