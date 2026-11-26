# Architecture

SXZ is a family of research prototypes, not one binary format.

1. **Core exact codec.** A window is fitted against deterministic models,
   extended, and stored as a descriptor plus position map or residual. A
   separate backend compresses unmodeled bytes. Decoding replays descriptors
   and verifies the final output.
2. **Stream and folder layer.** Bounded independent frames carry headers,
   checksums and fallback codecs. Folder mode serializes a safe TAR inventory
   and restores atomically.
3. **SXZ3–SXZ4.** Wider model banks, word/channel relations, exact residuals,
   reversible transforms and independently positioned spans. A cost check and
   transform screen decide what may be retained.
4. **NEXT.** Rust scanning and a typed, bounded program DAG for experiments on
   native coverage, algebraic law fitting and exact composition.
5. **Relationships.** Known structure boundaries and a shortlist of similar
   records; target records reference an earlier model plus parameters and an
   exact residual.
6. **MSMC.** External mathematical banks, multiple radix views, indexed exact
   matching, approximate follow-up and weighted interval mosaic selection.
7. **ASMC.** Adaptive seed/parameter catalogs, exact indexed matching, and
   shared-seed group selection under explicit counting and resource bounds.

Every layer has a corresponding English phase report. Historical prototypes
may use different labels for “span”, “record”, “literal” and “archive”; do not
assume wire compatibility. The lab formats (`XNB1`, `SRX0`, `MSM0`, `ASM0`) are
research serializations, not public SXZ releases.
