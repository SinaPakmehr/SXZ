# SXZ sparse XOR dictionary prototype (Phase 19)

This directory preserves the bounded exact XOR dictionary experiment and its
exhaustive structural census, described in
[the Phase 19 report](../../research/phases/19-xordict.md). It is research code,
not a general-purpose compressor.

## Source

| Path | Role |
|---|---|
| `scripts/run_phase19.py` | dictionary learning, literal/1/2/3-atom encoding, controls |
| `scripts/run_phase19_guard.py` | cumulative subprocess guard |
| `scripts/audit_phase19_xor.py` | exhaustive distinct-block pair/quad census |

## Protocols and evidence

| Path | Role |
|---|---|
| `protocols/phase19.json` | frozen gate/search space |
| `protocols/phase19-frozen.json` | selected settings frozen before validation |
| `results/phase19-dev.json` | development measurements |
| `results/phase19.json` | validation measurements, both learning modes |
| `results/phase19-runtime.json` | cumulative guard ledger |
| `results/phase19-xor-audit.json` | exhaustive relationship census |

The two learning modes are `dev_transfer` and `local`, both charged with the
complete dictionary. Selected 7zr/BBC/IRS one-atom counts and the 24-archive
F/G interpretation are documented in the report. Zero selected multi-atom
encodings does not imply zero available algebraic relations: the census found
four-value relations at eight-byte blocks only.

## Reproduction limits

The scripts expect the six corpus files at `datasets/corpus/`; they are not
redistributed. Run in a disposable copy because the runners write results.
The audit uses preserved JSON and the same corpus fixtures.

## Sanitization

Public copies rewrite private path roots to repository-relative `lab/` and
`datasets/` paths. Scientific fields and region hashes are unchanged.
Original/private versus public sanitized SHA-256 values are in
[`../PHASES-16-20-PROVENANCE.json`](../PHASES-16-20-PROVENANCE.json).
