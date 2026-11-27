# SXZ exact spectral prototype and Haar audit (Phase 18)

This directory preserves the original and corrected Phase 18 experiments
described in [the Phase 18 report](../../research/phases/18-spectral.md).
The original and corrected evidence are intentionally separate; neither is
overwritten.

## Source

| Path | Role |
|---|---|
| `scripts/run_phase18_original.py` | original reversible packet-like transform and its controls |
| `scripts/run_phase18.py` | corrected standard approximation-only Haar and FWHT codec |
| `scripts/run_phase18_guard.py` | cumulative subprocess guard |
| `scripts/audit_phase18_haar.py` | independent reference comparison, level traces and range checks |

## Protocols

| Path | Role |
|---|---|
| `protocols/phase18-original.json` | pre-audit protocol for the original run |
| `protocols/phase18-corrected.json` | corrected codec freeze used for the corrected rerun |

## Evidence

- Original: `results/phase18-dev-original.json`,
  `results/phase18-original.json`,
  `results/phase18-runtime-original.json`.
- Corrected: `results/phase18-dev.json`, `results/phase18.json`,
  `results/phase18-runtime.json`.
- Arithmetic audit: `results/phase18-haar-audit.json`.

The original transform was invertible but recursively decomposed detail
coefficients. The corrected standard lifting was frozen and rerun with the same
data, configurations, controls and gate. The corrected aggregate G/base is
1.776; the historical original value 1.993 is not the corrected outcome. The
secondary sparsity notion was qualitative and was not numerically defined in
the protocol.

## Reproduction limits

The scripts expect the six corpus files at `datasets/corpus/`; they are not
redistributed. The audit reads preserved JSON and source and additionally
checks the selected raw regions, so it is blocked without those fixtures. Run
in a disposable copy because the runners write results.

## Sanitization

Public copies rewrite private path roots to repository-relative `lab/` and
`datasets/` paths. Scientific fields, sizes and hashes of input regions are
unchanged. Original/private versus public sanitized SHA-256 values are listed
in [`../PHASES-16-20-PROVENANCE.json`](../PHASES-16-20-PROVENANCE.json).
