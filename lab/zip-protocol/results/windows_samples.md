# Windows local file samples

Up to three 2 MiB windows per file (start, middle, end, 16-byte aligned). Pack times are seconds; all candidates were decoded and byte-compared. Level 1 in every column.
Fast samples three 16 KiB ranges per frame before attempting Deflate. The Python and Rust formula profiles use an otherwise identical budget of eight bank probes per frame.

| Sample | Sample B | Fast B / s | Full Deflate choice B / s | Formula mode: archive B / pack s / scan s (Python) | Same mode (Rust) |
|---|---:|---|---|---|---|
| Desktop JPEG | 6291456 | 6186870 / 0.380 | 6186870 / 0.389 | 6186870 / 1.580 / 1.189 | 6186870 / 0.562 / 0.136 |
| Desktop PNG | 6291456 | 6291579 / 0.115 | 6291579 / 0.351 | 6291579 / 1.691 / 1.351 | 6291579 / 0.508 / 0.135 |
| Lessons MP4 | 6291456 | 5088025 / 0.183 | 5088025 / 0.302 | 5088025 / 1.902 / 1.537 | 5088025 / 0.454 / 0.129 |
| Lessons PDF | 6291456 | 4376179 / 0.305 | 4376179 / 0.284 | 4376179 / 2.009 / 1.401 | 4376179 / 0.780 / 0.185 |
| Music MP3 | 6291456 | 6262071 / 0.264 | 6250779 / 0.393 | 6250779 / 1.612 / 1.219 | 6250779 / 0.500 / 0.146 |
| Music FLAC | 6291456 | 6277990 / 0.117 | 6277990 / 0.304 | 6277990 / 1.529 / 1.196 | 6277990 / 0.503 / 0.135 |
| OpenVINO largest BIN | 6291456 | 5350701 / 0.408 | 5350701 / 0.435 | 5350701 / 1.381 / 1.046 | 5350701 / 0.479 / 0.122 |
| OpenVINO largest BLOB | 6291456 | 5273375 / 0.324 | 5273375 / 0.306 | 5273375 / 1.469 / 1.083 | 5273375 / 0.515 / 0.137 |

## Numeric transform probe (zlib payload only)

| Sample | Identity B | Byte planes 2 | Byte planes 4 | Byte planes 16 | Nibble planes |
|---|---:|---:|---:|---:|---:|
| OpenVINO largest BIN | 5350578 | 5338414 | 5348587 | 5389975 | 5360842 |
| OpenVINO largest BLOB | 5273252 | 5256522 | 5266585 | 5329543 | 5325672 |
