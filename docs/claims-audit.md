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
phase reports. Raw coverage is not archive-size savings. The external Lean
community announcement linked from the README was fetched and is described as an
announcement, not as an independent audit by this project.
