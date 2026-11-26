# Benchmarks

The archive preserves exact historical measurements; it does not claim that
all of them are rerunnable from one downloaded corpus. Start with the lightweight
checks and one planted/control experiment, then add a reviewed dataset:

| Scope | Entry point | Full input |
|---|---|---|
| core exactness/parity | `scripts/check.py` | none |
| SXZ4 planted | `examples/demo.py` | none |
| NEXT planted scan | `lab/sxz-next-research/controls.py planted` | none |
| structural control | `lab/sxz-structural-relations/study.py control` | none |
| MSMC control | `lab/sxz-mathematical-mosaic/measure.py control` | native build; optional FLINT |
| ASMC control | `lab/sxz-adaptive-stochastic-mosaic/experiment.py control` | none |

Use a disposable copy when a script writes `results/`. Record software versions,
settings, input hashes and paired baselines. Do not pool complete-file and slice
panels or different codec levels. The exact table locations and caveats are in
[results](../results/README.md) and the [reproduction guide](../docs/reproduction.md).
