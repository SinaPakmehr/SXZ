# Phase 10 — Adaptive Stochastic Mosaic Compression (ASMC)

## 1. Research question
Can a short adaptive generator/seed description reproduce several
non-contiguous regions of a file economically, rather than searching a fixed
mathematical world?

## 2. Motivation
MSMC’s fixed sequences had high raw coverage but little final saving. If one
seed can serve multiple regions, its descriptor might amortize, but address,
length and residual costs remain.

## 3. Hypothesis
A bounded deterministic pseudorandom family, searched adaptively, may yield a
shared seed for enough file regions to beat the same representation and backend
after all costs.

## 4. Experimental architecture
A Rust catalog of counter/mix, xorshift, PCG, LCG, LFSR, GF(256), cellular,
composition, histogram, Markov and hidden-state sources; seed matrices; an
exact k-mer index; and three planners: independent seeds (A), one shared seed
(B), and up to four shared seeds (C).

## 5. Mathematical methods
Seed/parameter spaces, counter and affine jumps, algebraic LFSR/recurrence/LCG
recovery, state/address inversion, 2–16-bit sequence views, affine/delta address
descriptions, weighted intervals, exact and sparse residual patches, entropy
controls, and counting bounds for seeds, matches and shared slices.

## 6. Dataset description
Twenty-two complete general-purpose files (19 reused with matching SHA-256,
three new public originals), plus synthetic single/multi-source, hidden-state,
uniform-random, nonuniform, outside-catalog and noisy controls. Full enwik8 was
available but not used for a large-scale claim because no small-scale gain existed.

## 7. Baselines
Direct framed storage, fixed-seed bank, independent uniform counter bank,
trained histogram and Markov banks, target-fitted histogram (all table costs
charged), Huffman/entropy coding, repeat-only controls, matched-same-split
storage, external trained dictionary, and MSMC.

## 8. Experimental protocol
Exhaust seed spaces only through 16 bits; sample 20/24/32-bit spaces at a
fixed 65,536 seeds. Match exact substrings with six retained addresses, verify
and extend; rank independent/shared seeds with costs; measure actual archives;
and repeat each positive with identical boundaries and literal instead of seed
references. Freeze a predeclared 1% + 128 B rule and a 22-file holdout.

## 9. Evaluation metrics
Exact reconstruction, final archive bytes, isolated gain vs direct and matched
segmentation, raw union coverage, beneficial candidate count, shared-group
count, seed/address/description cost, search and decode throughput, and memory.

## 10. Quantitative results
Adaptive-seed mean raw coverage was 7.98% across the full held-out panel; eight
files had smaller candidate archives with fallback, but the best isolated
gain after matched segmentation was 7 B. All eight apparent wins used SplitMix
seed zero and 7/8-byte zero runs; removing seed zero at equal 4,096-seed bank
size produced no positive candidate. A shared-seed planted control fell from
2,048 to 1,002 B. The pure generator path with no fallback was often worse.
Raw: [tables](../../lab/sxz-adaptive-stochastic-mosaic/results/tables.md),
[held-out](../../lab/sxz-adaptive-stochastic-mosaic/results/heldout.json),
[zero exclusion](../../lab/sxz-adaptive-stochastic-mosaic/results/without-zero.json).

## 11. Positive findings
Shared seeds can amortize across non-contiguous generated regions in planted
data; selected LFSR/LCG/Xorshift laws are recoverable; exact bit-mode and
residual decoding is correct; adding modes raises raw coverage and trivial
zero-run matches.

## 12. Negative findings
On complete real files no candidate met the economic gate. The apparent wins
were explained by a low-complexity prefix and backend segmentation, not a
general adaptive PRNG advantage. Higher seed spaces did not imply higher net
saving. A fixed 32-seed bank with longer prefixes did not beat the sampled
large bank. Uniform/fitted controls sometimes had equal or higher coverage.

## 13. Implementation limitations
Only a finite generator catalog, shallow composition, six addresses per key,
limited instruction/work budgets and no general evolutionary or SAT solver were
used. The 32-bit nominal spaces were sampled, not exhausted. No product decoder
was built.

## 14. Theoretical limitations
For a correct bound, count generator choices × seeds × addresses × target
positions; shared-slice compatibility falls as the total required matches grow.
Search increases opportunities but not the number of short descriptions. A
finite generator can help only if the source lies near that generative class;
otherwise a huge bank is just another address space. No claim violates Shannon
or algorithmic counting bounds.

## 15. Conclusions
ASMC validates the shared-seed mechanism on data generated with that mechanism,
but not a repeatable compression advantage on the tested general-purpose files.
The negative result stops the massive seed search and the product path. A future
test would require an application with a known generator/seed provenance and a
well-defined paired baseline.

## 16. Reproduction instructions
Build `asm_native` with `rustc`, run `python -B experiment.py control`, then the
full suite only with reviewed inputs and baseline JSON; see
[reproduction](../../docs/reproduction.md) and [bound](../../lab/sxz-adaptive-stochastic-mosaic/BOUND.md).
The seed-zero ablation is a documented post-hoc diagnostic.

## 17. References
Marsaglia Xorshift, O’Neill PCG, Blackman–Vigna, Steele–Lea–Flood, Shannon,
Rissanen, Zstandard; see [related work](../related-work.md) and
[references](../references.bib).
