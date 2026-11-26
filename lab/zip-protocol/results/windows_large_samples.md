# Windows local file samples

Up to three 16 MiB windows per file (start, middle, end, 16-byte aligned). Pack times are seconds; all candidates were decoded and byte-compared. Level 1 in every column.
Fast samples three 16 KiB ranges per frame before attempting Deflate. The Python and Rust formula profiles use an otherwise identical budget of eight bank probes per frame.

| Sample | Sample B | Fast B / s | Full Deflate choice B / s | Formula mode: archive B / pack s / scan s (Python) | Same mode (Rust) |
|---|---:|---|---|---|---|
| OpenVINO 4.30 GiB BIN | 50331648 | 45001094 / 3.007 | 45001094 / 2.925 | 45001094 / 12.761 / 9.615 | 45001094 / 3.999 / 0.778 |
| Music largest MP3 | 50331648 | 50126231 / 2.011 | 50027142 / 2.952 | 50027142 / 13.199 / 10.014 | 50027142 / 3.861 / 0.766 |

## Numeric transform probe (zlib payload only)

| Sample | Identity B | Byte planes 2 | Byte planes 4 | Byte planes 16 | Nibble planes |
|---|---:|---:|---:|---:|---:|
| OpenVINO 4.30 GiB BIN | 45000971 | 44961675 | 44993946 | 45076378 | 45192417 |
