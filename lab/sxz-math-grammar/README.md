# SXZ mathematical grammar prototype (Phase 16)

This directory preserves the bounded RePair/parameterized-template experiment
described in [the Phase 16 report](../../research/phases/16-math-grammar.md).
It is a research prototype, not a supported codec.

## Preserved source and evidence

| Path | Role |
|---|---|
| `scripts/run_phase16.py` | deterministic grammar codec, controls, guard and result writer |
| `protocols/phase16-protocol.json` | frozen search space, controls and gate |
| `results/phase16-dev.json` | development measurements |
| `results/phase16.json` | frozen validation measurements |

The two result files are the complete machine-readable records. The report
contains the compact absolute-size table and the negative conclusion.

## Reproduction limits

The script expects six corpus files at `datasets/corpus/`; those inputs are not
redistributed. Place lawfully obtained copies there, or pass the runner's
supported split/file options. Run it in a disposable copy because it writes
`results/`. The original private run used a six-process pool and wrote the
development and validation records separately.

## Sanitization

Public copies rewrite historical private path roots to repository-relative
`lab/` and `datasets/` paths. Scientific fields, sizes, settings and hashes of
input regions are unchanged. The source-to-public mapping and original/private
versus sanitized/public SHA-256 values are recorded in
[`../PHASES-16-20-PROVENANCE.json`](../PHASES-16-20-PROVENANCE.json).
