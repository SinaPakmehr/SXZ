# `sxz-next-research` — direct-matching and DSL prototype

Status: historical research code. Build `native.rs` and the optional
`preflate-bridge` from source; no DLL or external tool is bundled.

```text
rustc --edition=2024 --crate-type cdylib -O native.rs -o sxzscan_next.dll
cargo build --release --locked --manifest-path preflate-bridge/Cargo.toml
python -B controls.py planted
python -B families.py
```

Use the `.so`/`.dylib` filename on Linux/macOS. Complete-file scripts expect
fixtures under `datasets/`; absent inputs are documented rather than
substituted. `results/` preserves measurements and profiles after path
sanitization. The final phase report is [07-next](../../research/phases/07-next.md).
