# Phase 07 — Native scanning and bounded generative programs

## 1. Research question
Can better native search and compositional program descriptions overcome the
coverage and cost limits observed in SXZ4?

## 2. Motivation
The previous engine missed late, short laws and had a high Python search cost.
A second hypothesis was that a small DSL could express multi-level descriptions
that a fixed model bank cannot.

## 3. Hypothesis
A width-multiscale native scan can find late patterns, while bounded program
inference can pay only when program, parameters, references and residual are
cheaper than an identical exposed representation.

## 4. Experimental architecture
A Rust order-two scanner, a type-preserving DSL with composition, a bounded
A*/beam synthesizer, algebraic recurrence fitting, and whole-file attribution
against matched transforms and conventional codecs.

## 5. Mathematical methods
Multi-window recurrences, modular recovery, prefix expressions, composition,
literals/repetition/permutation/slices, grammar induction, exact residuals, and
native hot-loop generation.

## 6. Dataset description
Complete public files (text, PDF, DOCX, JPEG, PNG, EXE, model weights), full
Silesia members and enwik8 at 1/10/100 MB. Synthetic laws are controls only.

## 7. Baselines
The same typed representation with and without the math proposal, Zstd/Brotli/
XZ, format exposure (Preflate), specialization controls, and SXZ4.

## 8. Experimental protocol
Preserve boundaries, compare forced and locally selected programs, verify
round trips, and repeat every positive at the same segmentation with literal
storage instead of a program reference.

## 9. Evaluation metrics
Archive bytes, isolated gain, match length and coverage, probes, search time,
exact decode and memory; percentages use original input bytes.

## 10. Quantitative results
The native scan found all 24 planted order-two patterns and none of the nine
order-three controls; algebraic recovery with known boundaries recovered all
nine. The 100 MB late 512-byte plant was found by the narrow Rust scan in about
0.68 s, outside the SXZ4 budget. On 15 complete files, a 8 B same-backend JPEG
gain came from a simple quantization-table pattern. [Whole-file table](../../lab/sxz-next-research/results/whole-files.md)
and [controls](../../lab/sxz-next-research/results/planted.json).

## 11. Positive findings
Native search materially improves coverage for its target family. Exact
model/residual and grammar mechanisms can reconstruct selected programs.

## 12. Negative findings
Better search did not imply a general formula-family improvement; order-three
remained outside the scanner. Domain baselines and representation effects
explained the significant size gains. Compositional programs did not produce
a significant independent real-data saving.

## 13. Implementation limitations
The DSL, search depth, candidate set and resource caps are bounded. Python
remains the reference; no production decoder was built.

## 14. Theoretical limitations
The order-two algebraic scan is not a general recurrence solver. Program search
over a finite DSL cannot represent arbitrary generators; exact literals remain
part of the code and affect the count.

## 15. Conclusions
The native scan is a useful research component, not a universal compression
breakthrough. Formula programs must be judged against the identical exposed
representation. This phase informs the later mosaic experiments.

## 16. Reproduction instructions
In `lab/sxz-next-research`, build `native.rs` with `rustc`, then run
`python -B controls.py planted` and `python -B families.py`; see
[reproduction](../../docs/reproduction.md).

## 17. References
Brevis preprint, Re-Pair, A*, Preflate-RS, BBP; see [references](../references.bib).
