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
| Phase 14 no Gr?bner basis | phase report and source | no Gr?bner implementation or claim |
| Phase 15 gull 9 B win | `lab/sxz-image-math/results/phase15_ep3.json` | 86,641 - 86,632 = 9 B; 0.0104% |
| Phase 15 negative complete images | `phase15_ep3.json` | no E result below all controls |

These are bounded measurements, not universal codec claims. See
[findings](../research/findings.md) and [errata](../research/errata.md).
