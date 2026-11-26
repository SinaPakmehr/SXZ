# Phase 08 — Structural relationships

## 1. Research question
Can non-contiguous but similar structures share a parameterized description
and reduce final archive size after all parameters and residuals are charged?

## 2. Motivation
A generative relation may be non-local: XML elements, PDF objects, tensors,
executable records or image tiles may resemble each other despite distant
offsets.

## 3. Hypothesis
A common model plus per-structure parameters can be cheaper than independent
encodings, but only when the reference, location and residual costs are lower
than the same backend's coding of the exposed structures.

## 4. Experimental architecture
A bounded structural parser supplies known boundaries. Candidate parents are
linked by similarity, then encoded via literal, exact delta, copy/insert,
grammar or a small reversible parameter map. A weighted interval planner
selects intervals and a shared local fragment layer is tested separately.

## 5. Mathematical methods
Numeric-token shifts, dihedral tile maps, byte-planar reversible maps,
modular affine transforms, word-pattern maps, copy/insert and exact deltas;
set-cover-like group selection with explicit model costs.

## 6. Dataset description
Complete XML/DOCX/PPTX/PDF, ONNX tensors, PE binaries and PNG images; 17
complete files in the final panel. Inputs are public or derived fixtures with
hashes; private media are excluded.

## 7. Baselines
Same-file exact deduplication, copy/insert and grammar; same representation
without the math map; raw Zstd/Brotli/XZ; Preflate for exposed streams;
format-specialized controls such as trained dictionaries and PNG/JPEG XL.

## 8. Experimental protocol
Give all methods the same known boundaries, measure each record's final archive
cost, keep one common model per group, and repeat any positive with matched
segmentation and the same Zstd literal stream.

## 9. Evaluation metrics
Exact round trip, final size, net vs matched baseline, number of shared groups,
description/parameter/residual raw bytes, search time, decode time and memory.

## 10. Quantitative results
On 17 complete files the only positive final differences were 576 B on one PDF
at Zstd-3 and 56 B on one executable at Zstd-9, about 0.079% and 0.003%.
Both reversed at the other tested level. After matched segmentation the
remaining independent gains were 2 B (JPEG) and 8 B (WAV). A separate
base-2 exploration left 3 B on a PDF. No family reached 1% plus 128 B. Raw: [tables](../../lab/sxz-structural-relations/results/tables.md),
[real records](../../lab/sxz-structural-relations/results/real.json).

## 11. Positive findings
Pairwise relationships were identified with known boundaries, exact copy and
parameterized descriptions reconstructed correctly, and a planted mirrored
tile control benefited from a shared parent.

## 12. Negative findings
Most gains disappeared under segmentation/backend attribution. Descriptors and
group introductions can cost more than a conventional repeat. The small gains
were not repeatable across files or levels.

## 13. Implementation limitations
Parsers are partial; PDF compressed-object expansion is incomplete; parent
shortlists and parameter families are finite; no full cross-checkpoint tensor
search was performed.

## 14. Theoretical limitations
Similarity is not conditional compression. Any shared representation must
transmit its index, difference and residual; global coding can make a local
saving disappear. The tested families are not exhaustive.

## 15. Conclusions
The phase supports the existence of structural relationships but not a general
compression advantage. The continuation gate was not met, so no broader search
engine was built.

## 16. Reproduction instructions
Run `python -B study.py control` in `lab/sxz-structural-relations`; the full
run requires reviewed inputs and optional tools. See [reproduction](../../docs/reproduction.md).

## 17. References
VCDIFF/RFC 3284, Re-Pair, Preflate-RS, JPEG XL, ZipNN and FM-Delta; see
[references](../references.bib) and [related work](../related-work.md).
