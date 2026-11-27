# README numerical-claim audit

Checked against preserved JSON. Numbers describe the listed experiment, not a
single comparative benchmark.

| README claim | Source | Check |
|---|---|---|
| 256 KiB second-order recurrence → 84 B | `lab/zip-protocol/results/sxz4_validation.json`, `decompose` | input 262,144; backend+exact 84 |
| 256 KiB LCG → 79 B | `lab/zip-protocol/results/sxz4_bench_full.json`, `lcg32` | `sxz4-on` = 79 |
| Fibonacci 16,428 → 57 B | `lab/sxz-next-research/results/families.json`, `fib-mod-2^32` | baseline 16,428; archive 57 |
| primes 10,009 → 48 B | `lab/sxz-next-research/results/families.json`, `prime-index-1297` | baseline 10,009; archive 48 |
| 100 MB native scan 0.68 s | `lab/sxz-next-research/results/scale.json` | 100 MB native median ≈ 0.68 s for the narrow order-two family |
| MSMC 74.44% raw coverage | `lab/sxz-mathematical-mosaic/results/summary.json` | 10M-symbol development, math |
| 48.12% raw coverage | `lab/sxz-adaptive-stochastic-mosaic/results/overview.json` | `file-fitted-hist`, 22-file mean |
| shared seed 2,048 → 1,002 B | `lab/sxz-adaptive-stochastic-mosaic/results/control.json` | synthetic shared-seed B-affine |

Attribution caveats are in `research/findings.md`, `research/errata.md` and the
phase reports. Raw coverage is not archive-size savings. The unsupported
external Riemann/Lean item was removed from the README during the Phase 11-15
audit rather than retained without verification.

## Phase 11-15 claim checks

| Claim | Source | Check |
|---|---|---|
| CGMC 0/13 gate passes | `lab/sxz-cgmc/results/strict-control-summary.json` | 0 gate passes; strict frames identical 33/33 |
| CGMC 17 malicious cases rejected | `lab/sxz-cgmc/results/audit-tests.json` | all rejected; v3 positive accepted |
| AMRD zero nontrivial spans | `lab/sxz-amrd/results/panel-summary.json`, `analysis.json` | 0 nontrivial; 361,282 B word coverage all simple |
| AMRD bit coverage 30.21% | corrected `8N=12,909,432` denominator | 3,900,113 / 12,909,432 |
| Scaling no hybrid win | `lab/sxz-scaling/results/phase13.json` | C > A at every completed size; B/C estimates |
| 7zr 12 rational records are AP+carry | `lab/sxz-2adic/results/episode2.json` | 12/12 AP; 14-16 B vs 18-20 B |
| Phase 14 no Gröbner basis | phase report and source | no Gröbner implementation or claim |
| Phase 15 gull 9 B win | `lab/sxz-image-math/results/phase15_ep3.json` | 86,641 - 86,632 = 9 B; 0.0104% |
| Phase 15 negative complete images | `phase15_ep3.json` | no E result below all controls |

## Phase 16-20 claim checks

| Claim | Source | Check |
|---|---|---|
| Grammar D/E/F = 138,565 / 135,562 / 138,287 B | `lab/sxz-math-grammar/results/phase16.json` | exact totals; F/D 0.9980, F/E 1.0201; LZMA2 83,457 |
| Grammar 278 B net vs D; 373 B local 7zr gain | `phase16.json`, `phase16-dev.json` | aggregate F-D = -278; 7zr validation F-D = -373 |
| Phase 17 E1 tensor F/base 1.209 | `lab/sxz-emar/results/phase17.json` | F/min = 1.209; 15 regions, 368,640 B |
| Phase 17 E2 BDD G/base 2.957 | `lab/sxz-emar/results/phase17b.json` | G/base = 2.957; 180 tested / 15 selected |
| Phase 17 E3 recurrence MD/base 2.380 | `lab/sxz-emar/results/phase17c.json` | 25,863 / 10,866 = 2.380; 4 KiB only |
| E1 first validation 208.24 s | `lab/sxz-emar/results/phase17-val-initial.json` | preserved failed-limit run; final 14.24 s is not cumulative |
| Phase 18 corrected G/base 1.776 | `lab/sxz-spectral/results/phase18.json` | 18,980 / 10,686 = 1.776; 0/6 saves; max coeff <= 246 |
| Phase 18 original G/base 1.993 historical | `lab/sxz-spectral/results/phase18-original.json` | old nonstandard transform; not the corrected outcome |
| Phase 19 no selected multi-atom codes | `lab/sxz-xordict/results/phase19.json` | tags 2 and 3 total 0; one-atom 7zr 44, BBC 2, IRS 23 |
| Phase 19 139 quadruples / 3.55% | `lab/sxz-xordict/results/phase19-xor-audit.json` | 8-byte validation; 936 B relation / 872 B nontrivial |
| Phase 20 rank 26 / nullity 37 | `lab/sxz-attribution/results/phase20-attribution.json` | 63 vectors; 122 quadruples are redundant equations |
| Phase 20 systematic 427/426 vs 504/567 B | `lab/sxz-attribution/results/phase20-systematic-audit.json` | actual value-set archive; theoretical 329 B |
| Phase 20 full region 4,194/1,092 vs 502 B | same | actual serialized sizes; shuffle2 + zstd-9 is strongest |
| Five executable replication, no economic win | `phase20-attribution.json` | coverage qualifies 5/5; credible cost advantage 0/5 |

The Phase 18 secondary sparsity observation was qualitative, not a numerically
frozen protocol check. Phase 20 value-set savings are not full-region
compression. These are bounded measurements, not universal codec claims. See
[findings](../research/findings.md) and [errata](../research/errata.md).
