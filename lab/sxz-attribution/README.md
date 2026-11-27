# SXZ structure-attribution audit (Phase 20)

This directory preserves the structural and systematic-cost audits described
in [the Phase 20 report](../../research/phases/20-attribution.md). It is an
audit, not a new codec.

## Source and evidence

| Path | Role |
|---|---|
| `scripts/run_phase20.py` | PE mapping, XOR/additive census, replication and conventional controls |
| `scripts/run_phase20_guard.py` | cumulative subprocess guard |
| `scripts/audit_phase20_systematic.py` | systematic packed r-bit coefficient-mask archives and exact decode |
| `results/phase20-attribution.json` | structural evidence and replication |
| `results/phase20-runtime.json` | cumulative guard ledger |
| `results/phase20-systematic-audit.json` | actual systematic/ordinary/literal archive sizes |

The 7zr participants lie in the PE `.reloc` section. Five additional Windows
executables/DLLs were sampled by fixed section rules. Their names, system
build hashes, section offsets and measurements are retained, but the binary
fixtures are not redistributed. The original 7zr input is likewise absent and
must be obtained lawfully.

The systematic audit selects a basis directly from the original vectors,
stores basis vectors literally, and uses continuously packed rank-bit masks
for dependent vectors. It charges positions, ordering, occurrence mapping,
literals and framing; value-set savings are not presented as full-region
compression.

## Reproduction limits

The structural runner expects the six corpus files under `datasets/corpus/`
and the named Windows system executables. The systematic audit reads the
preserved Phase 20 JSON plus those local system files. These paths are
environment-dependent; hashes and offsets document the exact local fixtures.
Run in a disposable copy because the runner writes `results/`.

## Sanitization

Public copies replace absolute system paths with `SystemRoot/...` references
and rewrite corpus roots to `datasets/corpus/`. Scientific fields, section
offsets, measurements and fixture hashes are preserved. Original/private versus
public sanitized SHA-256 values are in
[`../PHASES-16-20-PROVENANCE.json`](../PHASES-16-20-PROVENANCE.json).
