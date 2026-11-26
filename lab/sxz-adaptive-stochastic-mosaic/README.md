# `sxz-adaptive-stochastic-mosaic` — ASMC prototype

Status: historical research code and raw results. `ASM0` is a bounded lab
serialization, not a production decoder.

```text
rustc --edition=2024 --crate-type cdylib -O native.rs -o asm_native.dll
python -B -m unittest -v test_asm
python -B experiment.py control
```

Use the `.so`/`.dylib` filename on Linux/macOS. The full held-out suite expects
the reviewed panel and archived baseline JSON; results are preserved under
`results/`. The seed-zero ablation is an explicitly post-hoc diagnostic.
See [10-asmc](../../research/phases/10-asmc.md) and
[BOUND.md](BOUND.md).
