# `zip-protocol` — core and SXZ1–SXZ4 prototypes

Status: historical Python package with an installable `sinuxz` core and
experimental phase modules. `sinuxz` is the maintained engineering surface;
`experiments.sxz3` and `experiments.sxz4` are archived research code.

Build/check from the repository root:

```text
python -m pip install -e .
python -B scripts/check.py
```

The optional anchor accelerator is `native/reference_scan.rs`; build it as a
shared library and set `SINUXZ_SCAN_DLL` only for the parity test. The core
falls back to Python when it is absent. No compiled artifact is included.

`results/` contains the preserved tables and JSON from phases 1–6. Some values
in early result files were produced under different panels and settings; read
[errata](../../research/errata.md), especially for the validation comparison.
`experiments/sxz4/corpus4.py` and `corpus5.py` contain historical local-path
assumptions; use explicit paths and a disposable results directory for reruns.
