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
