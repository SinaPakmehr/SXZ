# `sxz-structural-relations` — relational-record prototype

Status: historical research code and protocol. This directory has no native
module. The sibling NEXT `preflate-bridge` must be built for format-exposure
runs; the synthetic control does not need it.

```text
python -B -m unittest -v test_relations
python -B study.py control
python -B study.py real
```

The control is self-contained. The complete-file run requires the immutable
fixture panel and optional format tooling. Results are preserved under
`results/`; `pilot-with-overlap/` records a pre-final pilot and is not the
reported outcome. See [08-relationships](../../research/phases/08-relationships.md).
