# Historical codec comparison

Derived from `compare_codecs.json`; retained settings differ by row.

| Corpus | Codec | Source bytes | Archive bytes | Ratio | Encode s | Decode s | Note |
|---|---|---:|---:|---:|---:|---:|---|
| desktop-mixed | sxz2-fast | 135,127,040 | 91,397,928 | 0.676385 | 3.275 | 0.798 | 4 MiB frames, Deflate 1, scan off |
| desktop-mixed | sxz2-tuned | 135,127,040 | 88,090,336 | 0.651908 | 20.416 | 0.898 | 1 MiB frames, Deflate 6, scan 8, bridge |
| desktop-mixed | sxz2-best | 135,127,040 | 87,411,338 | 0.646883 | 61.965 | 0.828 | 1 MiB frames, Deflate 9, scan 16, bridge, second pass |
| desktop-mixed | zstd-3 | 135,127,040 | 88,467,601 | 0.654699 | 0.301 | 0.157 |  |
| desktop-mixed | zstd-19 | 135,127,040 | 83,167,214 | 0.615474 | 57.889 | 0.243 |  |
| desktop-mixed | zstd-22 | 135,127,040 | 82,985,997 | 0.614133 | 239.248 | 0.218 |  |
| desktop-mixed | xz-6 | 135,127,040 | 82,585,932 | 0.611173 | 180.332 | 3.378 | single thread |
| desktop-mixed | xz-9e | 135,127,040 | 82,448,192 | 0.610153 | 323.188 | 10.916 | single thread |
| desktop-mixed | brotli-9 | 135,127,040 | 85,507,403 | 0.632793 | 155.938 | 1.218 |  |
| desktop-mixed | brotli-11 | 135,127,040 | 82,108,195 | 0.607637 | 639.598 | 1.233 |  |
| desktop-mixed | bzip2-9 | 135,127,040 | 83,239,001 | 0.616006 | 12.293 | 8.020 |  |
| desktop-mixed | gzip-9 | 135,127,040 | 87,405,418 | 0.646839 | 33.267 | 0.762 |  |
| desktop-mixed | 7z-lzma2-9 | 135,127,040 | 82,481,388 | 0.610399 | 143.685 | 3.522 | LZMA2 max, 14 threads |
| desktop-mixed | zpaq-m5 | 135,127,040 | 76,865,009 | 0.568835 | 228.183 | 316.269 | PAQ-family, maximum method |
