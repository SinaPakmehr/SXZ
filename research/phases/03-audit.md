# Phase 03 — Controlled detection audit

## 1. Research question
Are missed patterns caused by search budget, alignment, representation, model
bank or accounting, rather than by an absence of structure?

## 2. Motivation
The original premise had not been fairly tested when scanning was disabled or
when only a tiny fraction of each frame was probed.

## 3. Hypothesis
With known patterns, controlled insertions and a larger search budget, coverage
should rise; remaining misses should identify specific limits.

## 4. Experimental architecture
`experiments/audit` contains planted generators, frame variants, real-input
probes and rejection/accounting inspection. It isolates scanner budget,
window size and model-bank orientation.

## 5. Mathematical methods
Exact affine and recurrence plants at controlled offsets; endian and width
variants; reference constant slices; noise rates; and cost comparisons against
the same Deflate backend.

## 6. Dataset description
Generated controls plus historical real binaries, images and text fixtures.
Private or unavailable inputs are not substituted in the public record.

## 7. Baselines
Deflate, raw storage, and archive variants with scanning disabled, enabled or
with altered minimum span. All comparisons use the same implementation.

## 8. Experimental protocol
Insert a known law, vary one factor at a time, pack and unpack, count accepted
spans, and compare final archive size. Verify that a formula hit is retained
only when its full split overhead is cheaper.

## 9. Evaluation metrics
Byte recovery/coverage, accepted-span count, local and final archive savings,
exactness, and probe counts.

## 10. Quantitative results
A 1 MiB frame received 8 probes; four 256 KiB frames received 32. At the 4 MiB
folder setting, 8 probes of 128-byte windows covered about 1 KiB, or 0.024% per
frame. Big-endian u16 affine achieved 100% coverage versus 71% for little-endian.
Coverage was 71% at 1% byte noise and 1% at 20%. A real PE acceptance run with
250 segments was 18,329 B worse than Deflate; PPM was 32,276 B worse. With a
256-byte minimum, that PE case was about 10 B larger. These are historical
settings, not universal results. Raw: [audit_engine.json](../../lab/zip-protocol/results/audit_engine.json).

## 11. Positive findings
The audit found concrete implementation causes and a profitable little-endian
word model correction. Exact plants can be recovered when searched.

## 12. Negative findings
Budget, alignment and splitting can dominate. Length-first acceptance is not a
valid final-cost test. Rejection from a limited scan is not proof of absence.

## 13. Implementation limitations
The audit did not exhaust all offsets, model families or search methods.
Some real archives and native tools were environment-specific.

## 14. Theoretical limitations
A search budget bounds observed positions; it cannot certify a negative over an
unbounded family. Local hit counts omit the context effects of splitting a
global compressed stream.

## 15. Conclusions
The audit invalidates the interpretation of earlier scan-off folder ratios and
establishes the need for controlled, cost-aware validation in later phases.

## 16. Reproduction instructions
Run `python -m experiments.audit.planted` in the legacy package. See
[reproduction](../../docs/reproduction.md); absent inputs are documented rather
than replaced.

## 17. References
Internal audit artifacts and Deflate [RFC 1951](https://www.rfc-editor.org/rfc/rfc1951);
see [references](../references.bib).
