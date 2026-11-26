# `sxz-amrd` - Adaptive Mathematical Representation Discovery

Status: research code and compact evidence. The package contains the direct
algebraic inference engine used by Phases 12-14.

```text
cd lab/sxz-amrd
python -B -m unittest scripts.test_amrd -v
python -B scripts/run_controls.py
```

The unit/integration tests generate deterministic local synthetic controls and
do not need the real-file panel. `run_controls.py` writes generated fixtures under
`data/synthetic/` and a compact result under `results/`; it is a control, not a
general compression benchmark.

Full panel/cross-plane runners expect the reviewed real inputs. They are not
redistributed and their fixed paths are documented in the source. Substituting
other files is not an independent reproduction.

Evidence:

- `results/controls.json` - synthetic discovery accuracy and corrupted control.
- `results/analysis.json`, `panel-summary.json` - compact panel aggregates.
- `results/alignment.json`, `existing-compare.json` - independent checks.
- `results/episode2.json`, `episode3.json` - reversible and cross-plane screens.

The bit-plane denominator is corrected to `8N` unique original bit positions
(12,909,432) in the phase report; the historical `panel.json` field is not
published. See `research/phases/12-amrd.md`.
