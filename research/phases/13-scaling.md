# Phase 13 - Scaling and Mathematical Cost Diagnostics

## 1. Research question

Does increasing real-world file size improve mathematical compression, and is
the limiting factor model discovery, description cost, span length, or matched
conventional compression?

## 2. Method

Three real files were used: `enwik8` (text), `model-weights.bin` (general
binary) and `desktop-mixed.tar` (structured/multimedia). Nested prefixes were
64 KiB, 1 MiB, 8 MiB, 32 MiB and 100 MiB. `enwik8` is 100,000,000 B, so its
largest point is 32 MiB; the other two reached 100 MiB.

The fast native Rust scanner (`lab/sxz-next-research/native.rs`) ran a
**full-file, step-1, 32-bit order-2 affine** search at every size. The Python
AMRD scanner was not run exhaustively: two fixed 32 KiB regions per file at the
largest size provided width/family diagnostics (64 KiB total; 0.195% density at
32 MiB and 0.061% at 100 MiB). Thus native results have constant search density;
AMRD results do not, and are not a scaling curve.

Native search cap: 50,000 hits; no run truncated (maximum 13,003). The initial
attempt to add zstd-19 at 32 MiB exceeded 180 s and was stopped. The final
reported run restricted zstd-19/LZMA2 to <=8 MiB and took 127.5 s. The 180 s
budget therefore includes one interrupted attempt plus the final reduced run.

## 3. Cost accounting

A native hit records position (4 B), length (4 B), coefficients (12 B), initial
state (8 B) and metadata (4 B): 32 B per record. Mathematical-only `B` is
records plus raw literal bytes and a 16 B header; hybrid `C` is records plus
zstd-9 literal bytes and the header. Both are **size estimates**, not serialized
archives. `A` is actual zstd-9 on the same input. zstd-19/LZMA2 are matched
higher-effort checks where computed.

## 4. Results

| file | size | hits | covered B | A zstd-9 | B estimate | C estimate |
|---|---:|---:|---:|---:|---:|---:|
| enwik8 | 64 KiB | 0 | 0 | 23,923 | 65,552 | 23,939 |
| enwik8 | 1 MiB | 0 | 0 | 334,039 | 1,048,592 | 334,055 |
| enwik8 | 8 MiB | 17 | 804 | 2,644,308 | 8,388,364 | 2,644,795 |
| enwik8 | 32 MiB | 151 | 6,724 | 10,442,826 | 33,552,556 | 10,447,232 |
| model-weights | 64 KiB | 0 | 0 | 53,763 | 65,552 | 53,779 |
| model-weights | 1 MiB | 0 | 0 | 949,235 | 1,048,592 | 949,251 |
| model-weights | 8 MiB | 0 | 0 | 7,623,979 | 8,388,624 | 7,623,995 |
| model-weights | 32 MiB | 1 | 36 | 30,154,392 | 33,554,444 | 30,154,434 |
| model-weights | 100 MiB | 1 | 36 | 94,344,364 | 104,857,612 | 94,344,475 |
| desktop-mixed | 64 KiB | 6 | 1,244 | 63,972 | 64,500 | 64,510 |
| desktop-mixed | 1 MiB | 20 | 3,736 | 1,044,162 | 1,045,496 | 1,045,529 |
| desktop-mixed | 8 MiB | 71 | 12,748 | 8,284,150 | 8,378,148 | 8,291,519 |
| desktop-mixed | 32 MiB | 265 | 20,428 | 27,653,842 | 33,542,500 | 27,665,349 |
| desktop-mixed | 100 MiB | 13,003 | 504,452 | 63,822,082 | 104,769,260 | 64,200,425 |

`C` is worse than `A` at every completed size. The smallest loss is +16 B and
the largest +378,343 B. `B` sometimes saves raw bytes when coverage exceeds
records (enwik8-32M about 1.9 KB; desktop-100M about 88 KB), but never beats
`A`. Mathematics alone does not compress real data materially.

## 5. Genuine versus simple coverage

| file-32/100 MiB | constant hits/B | periodic hits/B | genuine affine2 hits/B | affine B/C/D |
|---|---:|---:|---:|---:|
| enwik8-32M | 127 / 5,800 | 17 / 636 | 7 / 288 | 3 / 4 / 0 |
| model-weights-100M | 0 / 0 | 0 / 0 | 1 / 36 | 0 / 1 / 0 |
| desktop-100M | 11,900 / 458,340 | 974 / 32,420 | 129 / 13,692 | 47 / 82 / 0 |

`B` = record >= raw span; `C` = record saves raw but loses to zstd-9 on the
span; `D` = record beats zstd-9. **No affine hit reached D.** Native record cost
32 B gives a raw break-even of 33 B; no conventional break-even was observed up
to 256 B. Genuine affine spans were 32-256 B; no 1024+ affine span occurred.

The 64 KiB AMRD sample found no nontrivial model. Its only models were 26
constants on desktop at offset 0 (widths 8:8, 16:8, 32:7, 64:3; 4,822 B span;
492 B records; all 26 raw-profitable, 4 zstd-9-profitable). These are flat-field
constants, not mathematical discovery.

## 6. Scaling answer

Genuine affine coverage was: enwik8 0 B at 64 KiB/1 MiB, 64 B at 8 MiB, 288 B
at 32 MiB; model-weights 0 B through 8 MiB, 36 B at 32/100 MiB; desktop 512,
768, 2,668, 3,628 and 13,692 B at 64 KiB/1/8/32/100 MiB. Desktop fractions
0.78%, 0.073%, 0.032%, 0.011%, 0.013%; enwik8 stayed below 0.001%. Coverage is
not proportional to size. The 100 MiB desktop increase is dominated by many
tiny 32-63 B hits and constants/periodic runs, not a scaling law.

## 7. Conventional checks and transform control

At 8 MiB, zstd-19/LZMA2 were enwik8 2,365,441/2,303,468 B; model-weights
7,633,783/7,681,900 B; desktop 8,256,094/8,278,140 B. Hybrid at zstd-19 was
also worse (enwik8 +521 B, model +16 B, desktop +2,208 B). Transform-only
controls at 64 KiB/1 MiB: enwik8 identity; model-weights shuffle4/shuffle2;
desktop delta/identity. They are ordinary reversible-transform savings, not
mathematical records.

## 8. Verification and timing

All 13,535 native hits across all completed scales regenerated their exact spans
with the native `rec2` generator; all 26 AMRD constant records reconstructed
exactly. Native records are 32 B; AMRD constants 17-24 B. Final run 127.5 s under
the 180 s budget; native full scans were fast, while zstd-19 at large sizes was
the budget bottleneck.

## 9. Positive findings

The native scanner verified exact discoveries quickly; constants/periodic
regions and a few genuine affine spans were found; computational accounting made
the failure mode clear.

## 10. Negative findings and limitations

No 1024+ affine span, no D-class model, no hybrid win, and no sustained scaling
advantage. Only three files and prefix samples were used; AMRD is a sparse
sample; the B/C estimates are not archives; zstd-19/LZMA2 were not run at 32/100
MiB. No whole-file superiority is claimed.

## 11. Reproduction

From the repository root:

```text
cd lab/sxz-scaling
python -B run_phase13.py
```

The script expects the reviewed corpus paths (or explicit replacements), the
public `lab/sxz-next-research/accelerate.py` loader and the native scanner built
from `native.rs`. Raw data: `lab/sxz-scaling/results/phase13.json`. The input
files are not redistributed.

## 12. References

Shannon (1948); Rissanen (1978); Zstandard RFC 8878; LZMA2/XZ format; SXZ4 and
Phase 12 reports. The native recurrence detector is an implementation of the
SXZ3/SXZ4 affine family, not a new general-purpose compressor.
