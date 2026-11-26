# Consolidated findings

| Finding | Supported scope |
|---|---|
| Exact mathematical reconstruction | Periodic and recurrence controls, reference slices, finite programs, and seeded mosaics |
| Generator recovery | Selected LFSR, recurrence, Xorshift and LCG controls; no general discovery or arbitrary PRNG recovery |
| Synthetic gains | Real reductions after full accounting on deliberately generated laws; not evidence for general-purpose inputs |
| Real representation gains | ECG shuffle/delta and exact container exposure; improvements are not creditable to novel mathematical discovery |
| Search engineering | Per-frame budget and alignment explained missed hits; a narrow native scanner found late planted laws, not arbitrary laws |
| Structural sharing | Related regions were found; two very small apparent wins changed sign with Zstandard level; zero families passed the continuation gate |
| MSMC | Raw coverage grew to 74.44% on development data with 10 million reference symbols; no net gain at that setting. At 1 million, matched-segmentation attribution left only 2 and 8 bytes on two of 19 held-out full files |
| ASMC | A shared seed benefited planted data, 2,048 to 1,002 B. On 22 real full files the largest isolated gain was 7 B; eight apparent wins depended on repeated zeros from seed zero, and all disappeared in the matched-budget exclusion run |
| CGMC (11) | No real file passed the 1% + 128 B gate. Strict A/B/C controls were byte-identical in 33/33 frames; the long-range result was conventional long-window matching. A test-construction error, not a decoder bypass, explained the old huge-output acceptance; real resource limits were fixed |
| AMRD (12) | Zero nontrivial real polynomial/affine spans in the 8-file panel. Synthetic laws recovered exactly. Corrected bit-plane coverage is 30.21% of 12,909,432 unique original bit positions, not whole-byte coverage. Cross-plane additions met the gate on 0/8 files |
| Scaling (13) | No proportional coverage scaling; genuine affine hits were rare and none beat zstd-9 on the same span. Mathematical-only and hybrid estimates were not archives; hybrid was worse than zstd-9 at every completed size |
| Number theory (14) | 12 real 7zr spans have exact 2-adic descriptions, but the simpler equivalent is a 16-bit AP with one carry (14-16 B), and no archive-level win. Coordinate and quadratic GF(2) relations were negative; no Gr?bner basis was computed |
| Image math (15) | Pixel-level functions and adaptive/compositional networks did not beat matched image controls. The only isolated win was 9 B on one gull crop (0.0104%); complete-image results were negative. No original-file reconstruction claimed |

Decode times and memory refer to measured implementations and settings, not
a product target. Weak statistical structure does not imply a profitable
description. No investigated architecture demonstrated general superiority
over established codecs. These results do not rule out new source classes
with short, independently meaningful descriptions.

Read the [phase reports](timeline.md) and [errata](errata.md) before citing an
early result; the reported comparison corpus and baseline matter. The five new
rows above are syntheses of bounded experiments, not universal benchmarks.
