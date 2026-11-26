# `sxz-scaling` - Scaling and Mathematical Cost Diagnostics

Historical Phase 13 diagnostic. It combines the full-file native 32-bit
recurrence scan from `lab/sxz-next-research` with a bounded AMRD sample.

```text
cd lab/sxz-scaling
python -B run_phase13.py
```

The reviewed corpora (`enwik8`, `model-weights.bin`, `desktop-mixed.tar`) are
not redistributed; the script expects them at the relative `datasets/` paths in
the source and documents absent inputs rather than substituting them. The native
scanner must be built from `lab/sxz-next-research/native.rs` (`.dll`/`.so`/
`.dylib`); no binary is bundled.

`results/phase13.json` is the compact record of the final 127.5 s run. That run
followed an interrupted 32 MiB zstd-19 attempt; zstd-19/LZMA2 were restricted to
<=8 MiB. Full native scans and sparse AMRD samples are distinct; see the phase
report. `B`/`C` values are size estimates, not serialized archives.

Entry point: `run_phase13.py`. See `research/phases/13-scaling.md`.
