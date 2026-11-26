# SXZ structural-relations experiment — protocol

- Full files only for primary results. References are within the same file;
  no pretrained or cross-file dictionary is free. Keep the first occurrence
  once and link only to earlier reconstructed records.
- Give methods the same known boundaries. Compare raw file Zstd/Brotli/XZ,
  exposed plain structures, exact dedup, nonlocal differential (arithmetic
  and copy/insert), a bounded grammar and the same differential plus a small
  parametric map. Report a per-record oracle separately from measured
  whole-file optimization. Include original framing, metadata, corrections,
  reference indices, parameters, residual and checksums in every result.
- Supported parameter classes are intentionally narrow: numeric-token shifts,
  bounded offset/dihedral maps, per-channel/additive bias or invertible affine
  modulo 256, and literal word-pattern remaps (unsigned modular). They are
  only evaluated at already-known boundaries.
- A family warrants more search only with a repeatable full-file gain of
  at least 1% and 256 bytes in at least two independently sourced real files
  over its best conventional matched baseline. Treat gains only versus raw
  inputs as representation effects. Independently report decode and memory
  costs and stronger external format-specialized codecs where practical.
- Keep controls and measured real-file conclusions separate. Stop on a
  negative gate; no new production archive version.
