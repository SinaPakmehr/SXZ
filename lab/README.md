# Historical phase code

Each sibling directory preserves an experimental prototype and its
machine-readable results. These are research artifacts, not one supported
codec. The phase reports in [`../research/phases`](../research/phases) explain
what each prototype tested and what was superseded.

| Directory | Phase | Role |
|---|---|---|
| `zip-protocol` | 1–6 | core package, audited scanner, SXZ3, SXZ4 and validation |
| `sxz-next-research` | 7 | native scan, DSL, bounded synthesis and whole-file controls |
| `sxz-structural-relations` | 8 | metadata-backed relational records and paired controls |
| `sxz-mathematical-mosaic` | 9 | fixed mathematical banks and mosaic selection |
| `sxz-adaptive-stochastic-mosaic` | 10 | adaptive seeds, shared-seed controls and bounds |

Do not run two experiments that write the same JSON concurrently. Record a new
run separately rather than overwriting historical results. Some scripts expect
complete fixtures under `datasets/`; unavailable inputs are not replaced with
lookalikes. See [reproduction](../docs/reproduction.md) and
[data provenance](../datasets/README.md).
