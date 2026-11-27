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
| `sxz-cgmc` | 11 | context generators, strict controls, decoder security and long-range checks |
| `sxz-amrd` | 12 | direct algebraic inference, reversible representations and cross-plane screens |
| `sxz-scaling` | 13 | nested real-data scaling and mathematical cost diagnostics |
| `sxz-2adic` | 14 | 2-adic rationals, coordinate functions and quadratic Boolean relations |
| `sxz-image-math` | 15 | pixel-coordinate functions, adaptive regions and compositional networks |
| `sxz-math-grammar` | 16 | bounded RePair grammar and parameterized templates |
| `sxz-emar` | 17 | exact finite-field tensors, decision diagrams and bounded multidimensional recurrences |
| `sxz-spectral` | 18 | exact integer transforms, Haar audit and corrected runs |
| `sxz-xordict` | 19 | sparse XOR dictionaries and exhaustive aligned-block census |
| `sxz-attribution` | 20 | executable structure attribution and systematic coefficient-mask audit |

Do not run two experiments that write the same JSON concurrently. Record a new
run separately rather than overwriting historical results. Some scripts expect
complete fixtures under `datasets/`; unavailable inputs are not replaced with
lookalikes. See [reproduction](../docs/reproduction.md) and
[data provenance](../datasets/README.md).
