# Release validation record

This file records what was actually run while preparing the local review
candidate. It is not a claim about untested platforms.

## Verified during preparation

- Windows x64, CPython 3.13, Rust 1.92 GNU toolchain.
- `scripts/check.py`: built the optional native scanner in a temporary
  directory; all **49** core tests and **13** SXZ4 tests passed; the planted
  offline demo restored 65,536 bytes exactly (65,593 direct, 84 modeled).
- Phase 11 `lab/sxz-cgmc/scripts/test_codec.py`: v2 round trips, determinism,
  270 mutations rejected, eight crafted malformed inputs rejected, `TESTS_OK`.
- Phase 11 `audit_tests.py`: corrected 17-case security/resource suite and
  strict-frame identity passed.
- Phase 12 `lab/sxz-amrd/scripts/test_amrd.py`: **10/10** tests passed; the
  legacy BM parity test imports `lab/zip-protocol` and is skipped only if that
  package is unavailable.
- Phase 13-15 source compiles. Their full runners were not rerun here because
  the reviewed corpora/images are not redistributed; the archived results are
  the measurements of record. No substitute dataset was used.
- A fresh public-only copy was installed from `pyproject.toml`; the optional
  Rust scanner was compiled without the private workspace.
- One pinned public RFC input was fetched and checked against its SHA-256;
  `examples/real_roundtrip.py` reconstructed 36,944 bytes exactly. The
  downloaded file was deleted before packaging.
- `scripts/verify.py` audited file types, local links and publication markers.
- `scripts/evidence.py` regenerated the selected figures.
- `CITATION.cff` validated against the Citation File Format 1.2.0 schema with
  `cffconvert` (2.0.0).
- The original private inventory was re-hashed after preparation and matched.
- README numerical claims were checked against raw JSON in
  [claims-audit.md](claims-audit.md). The external Riemann item is described as
  a Lean-community announcement, not an independent audit by SXZ.

## Historical, not newly rerun here

The archived phase suites report 14 NEXT tests, 9 structural-relations tests,
11 MSMC tests and 10 ASMC tests in their original runs. Their result JSON is
preserved; full reruns require external fixtures, trained baselines, and
native tools. Treat those counts as historical records, not as CI badges.

## Not verified

- Linux or macOS CI execution.
- A complete reconstruction of any large historical panel.
- Bit-exact equivalence of historical timings on another machine.
- Resource behavior under adversarial archives or production concurrency.
- A complete clean-clone rerun of Phase 13-15 panels; their inputs are absent.
- Full clean-clone reproduction of the Phase 11 panel; only decoder/security
  tests and compact evidence are published.

Historical performance numbers are measurements, not portability guarantees.
