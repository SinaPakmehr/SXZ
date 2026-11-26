# Glossary

**Archive bytes**: the serialized length including framing and side data.
**Coverage (raw)**: union of exact matched intervals, regardless of final cost.
**Economic coverage**: matched bytes that remain part of a smaller final archive.
**Span**: a contiguous region described by one model and position map.
**Residual**: exact correction or remaining data after a prediction.
**Backend**: general codec used for literals or unmodeled portions.
**Matched segmentation control**: the same intervals with references replaced
by literal bytes while the remaining compressed stream is held constant.
**Bank**: searchable generated/reference symbols and their addresses.
**Shared seed**: one generator definition used by several non-contiguous
records; its description is paid once, addresses are still paid.
**Held-out**: an input not used to tune the decision rule for that stage.
**Historical**: preserved result from its original run; not necessarily rerun.
**Corrected**: a later analysis supersedes the earlier interpretation; raw data
is not overwritten. See [errata](../research/errata.md).
