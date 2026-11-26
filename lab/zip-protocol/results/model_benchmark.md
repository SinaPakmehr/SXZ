# Experimental model benchmark

Photo source: `astronaut.png` (original file and RGB/PNG/JPEG variants).
Python 3.13.14, Windows. Window=128 B; adaptive stride; zlib level 9.
Constant index cold start: 0.291 s; excluded from table times.
Sizes are bytes. `zlib+16` includes the SXZ header; `ZIP` is a complete one-entry ZIP.
Formula B counts exact formula bytes in the selected archive, not PNM residuals.
All produced SXZ files were decoded and compared byte for byte.

| Input | Original | zlib+16 | ZIP | Base SXZ | Experimental SXZ | Formula B | Experimental codecs | Base/Exp pack s | Exp unpack s |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|
| pi-decimal-control | 1024 | 532 | 616 | 532 | 27 | 1024 | constant-slice pi/decimal | 0.168/0.002 | 0.002 |
| e-base256-control | 2048 | 2075 | 2159 | 2064 | 27 | 2048 | constant-slice e/base256 | 0.330/0.002 | 0.007 |
| phi-in-random-control | 65536 | 65578 | 65662 | 65552 | 61573 | 4000 | raw, constant-slice phi/base256 | 2.710/2.996 | 0.011 |
| quadratic-u16le-control | 65536 | 59182 | 59266 | 59182 | 80 | 65536 | quadratic | 2.667/0.160 | 0.161 |
| random-1KiB | 1024 | 1051 | 1135 | 1040 | 1040 | 0 | stored | 0.166/0.188 | 0.000 |
| random-64KiB | 65536 | 65578 | 65662 | 65552 | 65552 | 0 | stored | 2.678/3.207 | 0.000 |
| random-1MiB | 1048576 | 1048918 | 1049002 | 1048592 | 1048592 | 0 | stored | 19.849/29.141 | 0.002 |
| CPython-json-decoder.py | 13237 | 3692 | 3776 | 3692 | 3692 | 0 | deflate-whole | 0.617/0.661 | 0.000 |
| generated-telemetry.jsonl | 65810 | 6297 | 6381 | 6297 | 6297 | 0 | deflate-whole | 2.650/3.110 | 0.001 |
| generated-PCM.wav | 32044 | 30303 | 30387 | 30303 | 30303 | 0 | deflate-whole | 1.299/1.535 | 0.001 |
| gradient-128.ppm | 49167 | 45026 | 45110 | 16877 | 783 | 0 | PNM-above | 1.377/1.634 | 0.020 |
| gradient-128.png | 45143 | 45180 | 45264 | 45159 | 45159 | 0 | stored | 1.830/2.184 | 0.000 |
| python-source.zip | 3776 | 3803 | 3887 | 3792 | 3792 | 0 | stored | 0.655/0.707 | 0.000 |
| photo-original.png | 791555 | 449302 | 449386 | 449302 | 449302 | 0 | deflate-whole | 17.877/22.033 | 0.014 |
| photo-32.ppm | 3085 | 2974 | 3058 | 2974 | 2779 | 0 | PNM-paeth | 0.492/0.580 | 0.003 |
| photo-128.ppm | 49167 | 41492 | 41576 | 41492 | 32648 | 0 | PNM-paeth | 2.156/2.630 | 0.043 |
| photo-128.png | 35293 | 35330 | 35414 | 35309 | 35309 | 0 | stored | 1.430/1.704 | 0.000 |
| photo-512.ppm | 786447 | 627430 | 627514 | 627430 | 448197 | 0 | PNM-paeth | 17.776/22.653 | 0.694 |
| photo-512.jpeg | 53962 | 53827 | 53911 | 53827 | 53827 | 0 | deflate-whole | 2.212/2.683 | 0.001 |

## Constant matching, independent of archive selection

Exact matches of at least 16 bytes at **every** input byte offset; overlapping starts count separately.

| Input | Number of matching starts | Longest verified match (B) |
|---|---:|---:|
| pi-decimal-control | 1009 | 1024 |
| e-base256-control | 2033 | 2048 |
| phi-in-random-control | 3985 | 4000 |
| quadratic-u16le-control | 0 | 0 |
| random-1KiB | 0 | 0 |
| random-64KiB | 0 | 0 |
| random-1MiB | 0 | 0 |
| CPython-json-decoder.py | 0 | 0 |
| generated-telemetry.jsonl | 0 | 0 |
| generated-PCM.wav | 0 | 0 |
| gradient-128.ppm | 0 | 0 |
| gradient-128.png | 0 | 0 |
| python-source.zip | 0 | 0 |
| photo-original.png | 0 | 0 |
| photo-32.ppm | 0 | 0 |
| photo-128.ppm | 0 | 0 |
| photo-128.png | 0 | 0 |
| photo-512.ppm | 0 | 0 |
| photo-512.jpeg | 0 | 0 |
