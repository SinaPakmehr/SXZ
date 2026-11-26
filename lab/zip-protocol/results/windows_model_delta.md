# OpenVINO paired-cache probe

Frame-by-frame XOR then zlib level 1. Every delta was decoded and XORed back to the exact target bytes. The base is already present, and the selected size includes one selector byte per window but no new archive wrapper. The largest pair was only sampled; smaller pairs were covered in full. These results are not part of the folder archives.

| Pair by size | Mode | Examined B | Equal B | Raw/zlib target B | XOR/zlib target B | Best per frame B | Time s |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1017790464 | sample | 17825792 | 231200 | 15772912 | 16597277 | 15772929 | 2.34 |
| 457723904 | full | 457723904 | 457716613 | 404155813 | 2009698 | 2009808 | 31.48 |
| 4747264 | full | 4747264 | 4741859 | 2994437 | 25841 | 25843 | 0.31 |
| 3764224 | full | 3764224 | 75628 | 2721895 | 3618013 | 2721896 | 0.42 |
| 3354624 | full | 3354624 | 3354035 | 1976351 | 15279 | 15280 | 0.18 |
