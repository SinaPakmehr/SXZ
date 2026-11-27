# Errata and reporting precedence

- Historical folder runs with scan budget zero measured container/fallback
  behavior, not a failed mathematical search. The detection audit is authoritative.
- For validation's 48-file comparison, the corrected report uses 10,222,189 B
  against 9,747,573 B from the category-wise best external methods, about 4.9%
  larger. Do not cite the earlier 8,445,747 B comparison as authoritative.
- In validation, ECG span savings are zero in the final interpretation;
  the positive result is representation plus backend. Found-but-discarded
  model spans are not archive savings.
- The regenerated planted-span JSON supersedes earlier invalid overlap
  percentages. Architectural pilot runs with duplicated parents or singleton
  groups are not the authoritative structural/ASMC outcomes.
- Numerical values from distinct codec settings or different corpora are
  not pooled. No original raw result was overwritten to make a correction.

## Phases 11-15 corrections

- CGMC's original `huge_declared_output | accepted` entry was a test bug: the
  crafted header declared `orig_len=0`. The decoder was not bypassed. Corrected
  tests enforce `payload_len`, `ntok`, `meta_len`, offset/length and checksum
  bounds; the original result is preserved in `lab/sxz-cgmc/results/`.
- Phase 12's original bit denominator `103,275,456 = 64N` overcounted by 8x.
  Each of eight planes has `N` bits; the correct unique-original-bit denominator
  is `8N=12,909,432`, giving 30.21% coverage. The overlapping-window `2.7e-5`
  value is a nominal scale, not an independent-trials confidence bound.
- Phase 13 native scans are full-file and step-1; AMRD is a 64 KiB sparse sample.
  `B`/`C` are estimates, not archives. zstd-19/LZMA2 were only run through 8 MiB.
  The 127.5 s final run followed an interrupted 32 MiB attempt.
- Phase 14's 12 2-adic records are exactly 16-bit arithmetic progressions with
  one carry. The AP record is 14-16 B, versus 18-20 B rational. The finite
  16-bit suffix is not an infinite period-16 claim. Per-window nullity is not a
  law; only aggregate rank/nullity is reported. ECG 960/1,024 is bit accuracy
  before residual compression, not an archive result.
- Phase 15's Episode 2 56.04 s is total, not per-image; the first 320-node
  attempt was stopped at the 180 s limit and the reported run used 120 nodes
  with large complete images skipped. Phase 15's gull win is
  `9/86,641 = 0.0104%`, not below 0.01%. Episode 3's greedy network selection is
  bounded, not exhaustive, and JPEG XL was unavailable.

## Phases 16–20 corrections and precedence

- Phase 16: subtraction templates are additive templates with a negated base. The 278 B gain is against the bounded ordinary grammar, not against LZMA2. Transform-family selection used a development proxy; the grammar did not test a combined E+F branch. Fixed grids and shared rule budgets limit the inference.
- Phase 17 E1: the 208.24 s initial validation exceeded the 180 s limit. Final 14.24 s dev+validation is not cumulative runtime. A decoder-only speedup was reported to preserve sizes, ranks, hashes and gate outcomes; original evidence is retained. E2 tested 180 configurations and selected 15, explaining `dev_summary.configurations=15`. E3 is a bounded recurrence experiment, not full BMS/Scalar-FGLM; the prefix fit used only 2–10 coordinates. No Gröbner basis was computed.
- Phase 18: the original Haar routines recursively processed detail coefficients as well as approximations. The original reversible packet-like transform must not be described as standard approximation-only Haar lifting. Corrected runs have G/base = 1.776; original G/base = 1.993 is historical, not the corrected result. The qualitative secondary sparsity criterion was not numerically frozen, and the isolated 7zr bit-plane result is diagnostic, not a formal gate pass. Corrected cumulative runtime 26.978 s includes both runs.
- Phase 19: zero selected multi-atom codes does not mean zero algebraic relations. The exhaustive audit found four-value relationships at 8 B only. Selected one-atom blocks: 44 in 7zr (zero), 2 in BBC, 23 in PDF (local mode). 12 paired F/G checks mean 24 individual archives, not 12. The Phase 20 coverage reconciliation supersedes the earlier statement that every participant was unique: 936 relationship bytes minus 64 bytes of repeated values yields 872 nontrivial bytes. The matched reference-only saving bounds for 32 targets are 128 B at 4 B per reference and 32 B at 7 B per reference, before framing.
- Phase 20: the 122 XOR quadruples for 63 vectors are redundant equations in a dependency space of dimension 37, not 122 independent dependencies. Basis costs in the attribution experiment were estimates. The subsequent systematic audit used actual serialized archives: theoretical payload 329 B; actual value-set dictionary 427 B vs raw 504 B or tagged literal 567 B. Full-region systematic hybrid 1,092 B vs shuffle2 + zstd-9 502 B. All five replication regions remain negative economically. The final systematic audit supersedes the original basis-cost interpretation, not the original recorded evidence.

The Phase 16–20 reports and their final audit evidence determine the current conclusions. Do not silently rewrite old protocols or rerun files to match a later correction.
