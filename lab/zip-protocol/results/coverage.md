# Formula coverage sweep

Percentage of bytes reproduced *exactly* by at least one formula in the
model bank, scanning aligned blocks. 100% means the whole file could be
regenerated from parameters; 0% means no closed form was found.
This measures describability only; the container additionally requires a
formula segment to be smaller than deflate for the same span.

| sample | 16 B | 32 B | 64 B | 128 B | 256 B | 512 B | 1024 B |
|---|---:|---:|---:|---:|---:|---:|---:|
| zeros_4k.bin | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| pattern_4k.bin | 99.9 | 99.9 | 99.9 | 99.9 | 99.9 | 99.9 | 99.9 |
| counter_4k.bin | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| lfsr_4k.bin | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| xorshift_4k.bin | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| mixed_4k.bin | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 | 50.0 |
| text_1k.txt | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| gradient_32x32.png | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| random_1k.bin | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## Family breakdown

### zeros_4k.bin
  - 16 B: 100.0%  (const/identity x256)
  - 32 B: 100.0%  (const/identity x128)
  - 64 B: 100.0%  (const/identity x64)
  - 128 B: 100.0%  (const/identity x32)
  - 256 B: 100.0%  (const/identity x16)
  - 512 B: 100.0%  (const/identity x8)
  - 1024 B: 100.0%  (const/identity x4)

### pattern_4k.bin
  - 16 B: 99.9%  (period/identity x256)
  - 32 B: 99.9%  (period/identity x128)
  - 64 B: 99.9%  (period/identity x64)
  - 128 B: 99.9%  (period/identity x32)
  - 256 B: 99.9%  (period/identity x16)
  - 512 B: 99.9%  (period/identity x8)
  - 1024 B: 99.9%  (period/identity x4)

### counter_4k.bin
  - 16 B: 100.0%  (affine/identity x256)
  - 32 B: 100.0%  (affine/identity x128)
  - 64 B: 100.0%  (affine/identity x64)
  - 128 B: 100.0%  (affine/identity x32)
  - 256 B: 100.0%  (affine/identity x16)
  - 512 B: 100.0%  (affine/identity x8)
  - 1024 B: 100.0%  (affine/identity x4)

### lfsr_4k.bin
  - 16 B: 100.0%  (lfsr/identity x256)
  - 32 B: 100.0%  (lfsr/identity x128)
  - 64 B: 100.0%  (lfsr/identity x64)
  - 128 B: 100.0%  (lfsr/identity x32)
  - 256 B: 100.0%  (lfsr/identity x16)
  - 512 B: 100.0%  (lfsr/identity x8)
  - 1024 B: 100.0%  (lfsr/identity x4)

### xorshift_4k.bin
  - 16 B: 100.0%  (xorshift32/identity x256)
  - 32 B: 100.0%  (xorshift32/identity x128)
  - 64 B: 100.0%  (xorshift32/identity x64)
  - 128 B: 100.0%  (xorshift32/identity x32)
  - 256 B: 100.0%  (xorshift32/identity x16)
  - 512 B: 100.0%  (xorshift32/identity x8)
  - 1024 B: 100.0%  (xorshift32/identity x4)

### mixed_4k.bin
  - 16 B: 50.0%  (const/identity x64, affine/identity x64)
  - 32 B: 50.0%  (const/identity x32, affine/identity x32)
  - 64 B: 50.0%  (const/identity x16, affine/identity x16)
  - 128 B: 50.0%  (const/identity x8, affine/identity x8)
  - 256 B: 50.0%  (const/identity x4, affine/identity x4)
  - 512 B: 50.0%  (const/identity x2, affine/identity x2)
  - 1024 B: 50.0%  (const/identity x1, affine/identity x1)

### text_1k.txt
  - 16 B: 0.0%  (none)
  - 32 B: 0.0%  (none)
  - 64 B: 0.0%  (none)
  - 128 B: 0.0%  (none)
  - 256 B: 0.0%  (none)
  - 512 B: 0.0%  (none)
  - 1024 B: 0.0%  (none)

### gradient_32x32.png
  - 16 B: 0.0%  (none)
  - 32 B: 0.0%  (none)
  - 64 B: 0.0%  (none)
  - 128 B: 0.0%  (none)
  - 256 B: 0.0%  (none)
  - 512 B: 0.0%  (none)
  - 1024 B: 0.0%  (none)

### random_1k.bin
  - 16 B: 0.0%  (none)
  - 32 B: 0.0%  (none)
  - 64 B: 0.0%  (none)
  - 128 B: 0.0%  (none)
  - 256 B: 0.0%  (none)
  - 512 B: 0.0%  (none)
  - 1024 B: 0.0%  (none)
