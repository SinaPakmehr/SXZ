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

Decode times and memory refer to measured implementations and settings, not
a product target. Weak statistical structure does not imply a profitable
description. No investigated architecture demonstrated general superiority
over established codecs. These results do not rule out new source classes
with short, independently meaningful descriptions.

Read the [phase reports](timeline.md) and [errata](errata.md) before citing an
early result; the reported comparison corpus and baseline matter.
