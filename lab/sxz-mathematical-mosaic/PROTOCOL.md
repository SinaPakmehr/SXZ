# MSMC — frozen decision and resource envelope

- Full-file byte-stream validation (no file-format parser). Fixed dev/test
  split before measurements; dev is reused for dictionary training only
  outside the held-out comparison. Other bases are a prespecified panel of
  six complete files; enwik8 participates whole in the scaling experiment.
- Reference budgets are **total searchable symbols per bank**, not per
  source: 8,192, 100,000, 1,000,000 and 10,000,000. Fourth budget is a
  discovery/scale stress test, not an extra holdout tuning pass. A 100M-symbol
  bank requires encouraging economics at 10M. Test on 1M symbols frozen.
- At least three fixed independent random seed sets; compare math against
  uniform, per-source histogram-matched (sampling with replacement), and a
  shuffled source (same exact per-source histogram). All share lengths,
  base, search seed, duplicate-address budget, and wire field costs.
- Exact k-mers: roughly 24 bits of search seed (base 10 = 8 digits).
  Search every symbol start; shortlist at most 8 reference addresses for
  a repeated key, extend up to 4,096 symbols and verify actual symbols.
  Record caps explicitly. Economic selection is in original byte units.
- Compare exact direct and local-reuse mosaics, raw / compressed metadata /
  metadata + Zstd literals. A repeat-only counterfactual uses the same
  candidate repeats but stores the first copy literally. Separately train
  standard Zstd dictionaries on independent files and count their bytes.
- Continue only if the hybrid cuts at least 1% and 128 bytes relative to
  same-backend direct storage, beats a same-size control on the same files,
  and the win occurs on at least three unrelated held-out complete files.
  Also compare standalone against standard codecs. Synthetic gains do not
  count. First test exact; a small conditional approximate control only
  after that. No production archive or enlarged bank without evidence.
- Decoder bounds: 128 MiB final output, finite instruction count and
  ≤10M generated symbols in a bank; no input-selected code or seeds outside
  the predeclared catalog. Size of shared code/data and cold vs warm measured
  separately. Runtime/hardware and omitted experiments will be documented.
