# Phase 06 — SXZ4 comprehensive validation

## 1. Research question
On identical inputs, how much compression comes from reversible representation,
from exact mathematical models, from residual coding and from the backend?

## 2. Motivation
Earlier phases mixed transform effects, model hits and backend choices. A
validation phase must separate those contributions and preserve negative runs.

## 3. Hypothesis
Exact models and representations will help selected laws and structured data,
but a general-purpose corpus will not show a robust independent engine gain.

## 4. Experimental architecture
The validation suite covers noise, planted spans, unknown laws, component
decomposition, backend variants, transform ablations, tolerance, gating,
container recompression, scaling and repeated timing.

## 5. Mathematical methods
Exact and noisy recurrences; random-position planted spans; unknown order-three
and prime/LCG families; reversible word/plane transforms; exact Deflate stream
reconstruction through Preflate; MDL-style accounting of every field.

## 6. Dataset description
The 39-file SXZ4 panel and a new 48-item public-real panel, with development
and held-out separation. Inputs are complete files or documented slices.
Public provenance is recorded; original private fixtures are unavailable.

## 7. Baselines
Deflate-6, Zstd-19, XZ-6, Brotli-11, backend-only/transform-only/full variants,
and reimplemented numeric baselines where the original tool was unavailable.

## 8. Experimental protocol
Run the same input through each method, decode and compare bytes, record final
archive size and timing. For container tests, require bit-exact reconstruction
of the original compressed stream from plaintext plus corrections.

## 9. Evaluation metrics
Exactness, archive bytes and ratio, model/transform/residual shares, coverage,
probes, encode/decode time, peak memory, and discovery rate by length.

## 10. Quantitative results
The 39-file sums were synthetic 4,984,831→255,058 B, real 3,279,152→1,535,410 B
and precompressed 786,432→786,783 B. On the public-real panel the engine was
worse overall than the best category method; the corrected comparison is
10,222,189 versus 9,747,573 B, about 4.9% larger. ECG representation plus LZMA
was 84,195 versus XZ 118,172 B. The engine added no span savings on most real
files. Raw: [full benchmark](../../lab/zip-protocol/results/sxz4_bench_full.json),
[validation](../../lab/zip-protocol/results/sxz4_validation.json),
[ablation](../../lab/zip-protocol/results/sxz4_ablate.json).

## 11. Positive findings
Representation transforms produced repeatable gains on selected ECG/WAV-like
data; Preflate-based container exposure produced substantial gains on
supported ZIP/XLSX streams; exact reconstruction and CRC checks passed.

## 12. Negative findings
The formula engine did not provide broad real-data gains. A constant tolerance
was not optimal across files. Some originally reported span wins vanished
under cost-aware extension. DOCX/PPTX/PDF support was incomplete.

## 13. Implementation limitations
Panels and held-out sets are small; several external codecs/tools were absent;
Python speed and 256 KiB slices limit comparisons; container parsing is partial.

## 14. Theoretical limitations
A finite span and model family cannot cover all structural descriptions.
Model savings are conditional on backend context; a local win is not a global
archive win. Holdout conclusions are limited by panel size and composition.

## 15. Conclusions
SXZ4 validation separates the effects: representation and conventional
exposure explain most observed gains; independent mathematical spans did not
establish a general advantage. Earlier claims that confused these effects are
superseded (see [errata](../errata.md)).

## 16. Reproduction instructions
Use `experiments.sxz4.validate4` and `bench4` with explicit inputs; see
[reproduction](../../docs/reproduction.md). Do not mix new and archived output
files.

## 17. References
Preflate-RS, RFC 1951, RFC 8878 and XZ format; see [references](../references.bib).
