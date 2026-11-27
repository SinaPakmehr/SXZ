# SXZ exact multidimensional algebra prototype (Phase 17)

This directory preserves the three bounded branches described in
[the Phase 17 report](../../research/phases/17-emar.md): exact finite-field
matrix/Tensor-Train factorization, reduced ordered BDDs, and multidimensional
recurrences. It is research code, not a supported compressor.

## Source

| Path | Episode / role |
|---|---|
| `scripts/run_phase17.py` | E1 exact GF(2^8) matrix/TT codec and controls |
| `scripts/run_phase17b.py` | E2 ROBDD/MTBDD codec and controls |
| `scripts/run_phase17b_guard.py` | E2 cumulative subprocess guard |
| `scripts/run_phase17c.py` | E3 bounded recurrence discovery |
| `scripts/run_phase17c_guard.py` | E3 cumulative subprocess guard |

`run_phase17c.py` imports the GF utilities from `run_phase17.py` in this same
directory. No external package beyond `zstandard` is required.

## Protocols

| Path | Episode |
|---|---|
| `protocols/phase17-e1-protocol.json` | E1 pre-validation freeze |
| `protocols/phase17-e1-protocol-final.json` | E1 final/frozen protocol |
| `protocols/phase17-e2-protocol.json` | E2 frozen protocol |
| `protocols/phase17-e3-protocol.json` | E3 pre-validation freeze |
| `protocols/phase17-e3-protocol-final.json` | E3 final/frozen protocol |

## Evidence

- E1: `results/phase17-dev.json`, `results/phase17.json`,
  `results/phase17-val-initial.json`.
- E2: `results/phase17b-dev.json`, `results/phase17b.json`,
  `results/phase17b-runtime.json`.
- E3: `results/phase17c-dev.json`, `results/phase17c.json`,
  `results/phase17c-runtime.json`.

The initial E1 validation is retained because it exceeded the 180 s limit;
the later decoder-only speedup did not change sizes, ranks, hashes or gate
outcomes. Do not overwrite the initial file when rerunning.

## Reproduction limits

The scripts expect the six corpus files at `datasets/corpus/`; they are not
redistributed. Run in a disposable copy because the runners write results.
E1 spans 4/16/64 KiB regions, E2 the same 15 regions, and E3 only 4 KiB regions.
E2 tested 180 configurations and selected 15; the historical
`dev_summary.configurations=15` field counted selected regions, not tests.

## Sanitization

Public copies rewrite private path roots to repository-relative `lab/` and
`datasets/` paths and make the E1 import local. Scientific fields and scores
are unchanged. Original/private versus public sanitized SHA-256 values are in
[`../PHASES-16-20-PROVENANCE.json`](../PHASES-16-20-PROVENANCE.json).
