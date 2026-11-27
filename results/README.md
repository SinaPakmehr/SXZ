# Results index

All JSON under `lab/*/results/` is preserved historical evidence unless a row
says otherwise. Paths and environment strings were sanitized during publication;
scientific fields were not rewritten. `release-manifest.json` is generated after
the final audit.

| Phase | Key measurements | Primary files |
|---|---|---|
| 3 audit | probe budgets, alignment failures, local vs final loss | `audit_engine.json`, `audit_variants.json` |
| 4 SXZ3 | model/residual ablations, synthetic and real panels | `sxz3_bench.json`, `sxz3_ablate.json` |
| 5–6 SXZ4 | 39-file panel, public panel, ablations, timing, containers | `sxz4_bench_full.json`, `sxz4_validation.json`, `sxz4_ablate.json`, `sxz4_container.json` |
| 7 NEXT | native scan, DSL, full-file attribution | `planted.json`, `families.json`, `real.json`, `whole-files.md` |
| 8 relationships | record-level and complete-file paired results | `real.json`, `specialized.json`, `same-splits.json`, `tables.md` |
| 9 MSMC | banks, representations, held-out ceilings, same-splits | `dev.json`, `radix.json`, `test.json`, `same-splits.json`, `summary.json` |
| 10 ASMC | seeds, shared reference, controls, post-hoc ablation | `dev.json`, `heldout.json`, `without-zero.json`, `control.json`, `tables.md` |
| 16 grammar | bounded RePair, templates, matched controls | `lab/sxz-math-grammar/results/phase16.json`, `phase16-dev.json` |
| 17 EMAR | tensors, BDDs, recurrences; original and superseded runs | `lab/sxz-emar/results/phase17*.json`, `phase17b*.json`, `phase17c*.json` |
| 18 spectral | original/corrected Haar, FWHT, audit | `lab/sxz-spectral/results/phase18*.json` |
| 19 XOR dictionary | two modes, exhaustive relationship census | `lab/sxz-xordict/results/phase19*.json` |
| 20 attribution | PE census, replication, systematic coefficient masks | `lab/sxz-attribution/results/phase20*.json` |

[Figures](../figures/README.md) are derived from the JSON. Absolute sizes are
preferred to ratios when panels differ. See [errata](../research/errata.md) and
[methodology](../research/methodology.md) before combining rows.
