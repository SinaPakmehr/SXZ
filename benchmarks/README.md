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
| CGMC decoder/security | `lab/sxz-cgmc/scripts/test_codec.py`; `audit_tests.py` | none |
| AMRD controls | `lab/sxz-amrd/scripts/run_controls.py` | generated synthetic fixtures |
| Scaling diagnostic | `lab/sxz-scaling/run_phase13.py` | reviewed corpora; native scanner build |
| 2-adic/coordinate/GF(2) | `lab/sxz-2adic/scripts/run_phase14.py` and episodes | reviewed files/offsets |
| Mathematical image | `lab/sxz-image-math/scripts/run_phase15*.py` | reviewed images |
| Grammar/template controls | `lab/sxz-math-grammar/scripts/run_phase16.py` | six corpus files |
| Tensor/BDD/recurrence checks | `lab/sxz-emar/scripts/run_phase17*.py` (self-tests; full runs need inputs) | six corpus files |
| Spectral/Haar audit | `lab/sxz-spectral/scripts/run_phase18.py --selftest`; full runner/audit | six corpus files |
| XOR dictionary/census | `lab/sxz-xordict/scripts/run_phase19.py --selftest`; full runner/audit | six corpus files |
| Attribution/systematic audit | `lab/sxz-attribution/scripts/run_phase20*.py` | local Windows executables, 7zr and comparison files |

Use a disposable copy when a script writes `results/`. Record software versions,
settings, input hashes and paired baselines. Do not pool complete-file and slice
panels or different codec levels. The exact table locations and caveats are in
[results](../results/README.md) and the [reproduction guide](../docs/reproduction.md).
