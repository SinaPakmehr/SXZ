# Reproduction guide

From the repository root, use Python 3.13 and Rust 1.92+ without administrator
permissions. A virtual environment is recommended.

```text
python -m pip install -e .
python -m pip install -r requirements/research.txt
python -B scripts/check.py
python -B scripts/fetch_data.py rfc1951.txt
python -B examples/real_roundtrip.py datasets/corpus/rfc1951.txt
python -B scripts/evidence.py
python -B scripts/verify.py
```

`check.py` builds a temporary Rust scanner and tests Python and native
round-trip parity, detection, malformed archives and resource limits. It
configures the optional legacy scanner process-locally. No data download is
needed for tests or the planted demo. The optional real test explicitly fetches
one public file; remove downloaded material before preparing the release export.

## Historical entry points

Keep phase directories as siblings. Run benchmark scripts in a disposable copy:
some historically write to `results/`. Do not overwrite reference measurements.
Dependencies and fixture coverage differ by phase.

| Phase | Entry point | Limits |
|---|---|---|
| 1–2 | `python -m unittest discover -s tests` in `lab/zip-protocol` | Legacy folder/stream commands may not reconstruct unavailable input panels |
| 3 | `python -m experiments.audit.planted` in the legacy directory | Real archive inputs and tools are not distributed |
| 4 | `python -m experiments.sxz3.corpus3 --help` and `bench3 --help` as a module | Synthetic generation and public inputs are separate |
| 5–6 | `python -m experiments.sxz4.test_sxz4`; `python -m experiments.sxz4.validate4 noise` | Later validation families need the documented historical corpus layout |
| 7 | In `lab/sxz-next-research`: `python -B families.py`, `controls.py planted` | Full-file work needs fixtures and appropriate external tools |
| 8 | In `lab/sxz-structural-relations`: `python -B study.py control` | Real run needs inputs, Preflate bridge, and optional JPEG XL binary |
| 9 | In `lab/sxz-mathematical-mosaic`: `python -B measure.py control` | Full test needs complete fixtures and native index |
| 10 | In `lab/sxz-adaptive-stochastic-mosaic`: `python -B experiment.py control` | Full test needs baseline JSON and complete inputs |
| 11 | In `lab/sxz-cgmc`: `python -B scripts/test_codec.py`; `python -B scripts/audit_tests.py` | Panel inputs are not redistributed |
| 12 | In `lab/sxz-amrd`: `python -B -m unittest scripts.test_amrd -v`; `python -B scripts/run_controls.py` | Synthetic controls run locally; real panel inputs absent |
| 13 | In `lab/sxz-scaling`: `python -B run_phase13.py` | Native scanner build; reviewed corpora absent; B/C are estimates |
| 14 | In `lab/sxz-2adic`: `python -B scripts/run_phase14.py`; `python -B scripts/run_episode2.py`; `python -B scripts/run_episode3.py` | Reviewed files/offsets absent; no Gr?bner computation |
| 15 | In `lab/sxz-image-math`: `python -B scripts/run_phase15.py`; `python -B scripts/run_phase15_ep2.py`; `python -B scripts/run_phase15_ep3.py` | Images not redistributed; pixel-level results only |

The Phase 13 scanner reuses the NEXT native source. The three earlier phase-local Rust components can be built with
`rustc --edition=2024 --crate-type cdylib -O SOURCE -o OUTPUT`: use `native.rs`
and stem `sxzscan_next` in NEXT, `index.rs` and stem `msm_index` in MSMC,
and `native.rs` and stem `asm_native` in ASMC. Use `stem.dll` on Windows,
`libstem.so` on Linux and `libstem.dylib` on macOS. For optional bit-exact
Deflate reconstruction, build the NEXT `preflate-bridge` with
`cargo build --release --locked`. None of these builds is bundled.

Fixture maps in the phase runners and the [provenance list](../datasets/README.md)
are complementary. Legacy corpus tools expect repository-relative `datasets/`
paths from their invocation directory unless passed an explicit argument.
Full historical panels are **not** a one-command reconstruction: some original
media/checkpoints, exact generated containers, and private inputs are missing.
Do not call substitute-input results an independent reproduction. See
[release validation](validation.md) for platforms actually tested.
