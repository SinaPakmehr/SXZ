# `sxz-mathematical-mosaic` — MSMC prototype

Status: historical research code and raw results. It is not a supported
archive format.

```text
rustc --edition=2024 --crate-type cdylib -O index.rs -o msm_index.dll
python -B -m unittest -v test_mosaic
python -B measure.py control
```

Use the `.so`/`.dylib` filename on Linux/macOS. `measure.py control` is
self-contained apart from Python-FLINT/NumPy. Full panels require complete
fixtures, and `diagnostics.py` JPEG XL controls require an externally obtained
tool; neither is bundled. `results/` contains the historical numbers and the
regenerated English tables. See [09-msmc](../../research/phases/09-msmc.md).
