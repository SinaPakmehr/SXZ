# `sxz-cgmc` - Contextual Generative Mosaic Compression

Status: historical research code and compact evidence. `CGMC` is a bounded lab
container, not a production codec. The v3 header adds SHA-256 integrity; v2
remains decodable.

```text
cd lab/sxz-cgmc
python -B scripts/test_codec.py
python -B scripts/audit_tests.py
```

`test_codec.py` checks round trips, deterministic planning, strict-control
identity and malformed inputs. `audit_tests.py` regenerates the 17-case
security/resource regression. The historical panel runner is not bundled
because its reviewed inputs are not redistributable; see the phase report and
`results/` for the recorded measurements.

Evidence:

- `results/strict-control-summary.json` - A/B/C attribution controls.
- `results/audit-tests.json` - corrected malformed-input outcomes.
- `results/math-audit.json`, `ml-validation.json`, `approx.json` - diagnostics.
- `results/long-range.json`, `long-range-synth.json` - matched long-window tests.
- `results/perf.json` - measured scanner/decode performance.

The original Appendix J `huge_declared_output | accepted` result was a
test-construction error (`orig_len=0`), not a decoder bypass; the corrected test
is in `scripts/audit_tests.py`. No source paper, corpus file or third-party
binary is included. See `research/phases/11-cgmc.md`.
