# Phase 09 — Mathematical Sequence Mosaic Compression (MSMC)

## 1. Research question
Can an arbitrary file be decomposed into slices of independent mathematical
sequences, and can storing generator/address descriptions replace enough raw
bytes to shrink the final archive?

## 2. Motivation
This is the founder’s original hypothesis stated directly. Earlier phases had
drifted toward fitting many models to adjacent bytes; MSMC instead tests exact
substring presence in external sequence banks.

## 3. Hypothesis
Some regions may be exact slices of standard constants, number-theoretic
sequences or deterministic generators. A local library of repeated mathematical
pieces plus global segmentation might pay off if address and description costs
are small relative to the literal alternative.

## 4. Experimental architecture
A frozen generator catalog, multiple reversible numeric views, an indexed
substring search, exact and approximate candidate extraction, two mosaic
architectures (direct references and locally defined pieces), weighted interval
planning, and raw/compressed/hybrid archive encodings.

## 5. Mathematical methods
Certified decimal/hex prefixes with Arb, BBP controls, primes and arithmetic
functions, LCG/xorshift/LFSR/GF(2^8)/cellular/word compositions, modular and
digits representations, k-mer indexing, k-mer match probability and
description-code accounting.

## 6. Dataset description
Complete public TXT/PDF/DOCX/XLSX/PPTX/HTML/JSON/XML/JPEG/PNG/BMP/MP4/MP3/WAV/
EXE/DLL/ZIP/ONNX files, plus Canterbury, Calgary, Silesia and full enwik8.
Synthetic mosaics are controls only. Some generated containers and all source
media are not redistributed.

## 7. Baselines
Raw and framed Zstd-3/9/19, Brotli-9, XZ-6, trained Zstd dictionaries (charged),
exact deduplication and grammar, the same exposed representation without math,
and SXZ4. Source/random controls use matched total bank size.

## 8. Experimental protocol
Search all target starts at a fixed seed length, verify and extend actual
symbols, expand several numeric bases, select a bounded set of addresses and
intervals, serialize all metadata/residuals, and reconstruct the complete
original. Test development and held-out sets separately; repeat positives at
the same boundaries without a mathematical reference.

## 9. Evaluation metrics
Final archive bytes and ratio, exactness, raw and economic coverage, match
length distribution, number of profitable candidates, address/description
cost, search time and decode time/memory. Raw coverage is not counted as a saving.

## 10. Quantitative results
At 10 million development symbols, mean byte coverage was 74.44% for math,
74.22% for uniform and 80.02% for distribution-matched controls; no net gain
was observed at that scale. On 19 held-out files and a 1 million-symbol bank,
mean raw coverage was 18.98%; only two files had smaller final candidates.
Matched segmentation left 2 B on JPEG and 8 B on WAV, not the headline
764/436 B. The planted multi-source control improved from 12,408 to 9,721 B.
Raw: [tables](../../lab/sxz-mathematical-mosaic/results/tables.md),
[held-out](../../lab/sxz-mathematical-mosaic/results/test.json),
[same splits](../../lab/sxz-mathematical-mosaic/results/same-splits.json).

## 11. Positive findings
The engine can discover and exactly reconstruct planted slices, supports
certified constants and varied representations, and a large bank increases
raw coverage. The approximate follow-up reconstructed a controlled two-error
case exactly.

## 12. Negative findings
Coverage was largely explained by random/control banks at the large size.
Address and descriptor costs erased the gain on general files. Random controls
occasionally beat math on a fixed file. Distribution fitting did not improve
the final archive.

## 13. Implementation limitations
Search retains limited duplicate-key addresses, caps extension, uses a fixed
abstract bank and not per-file fitted generators, and the decoder is a research
harness. Target-format parsers were not used in the main test.

## 14. Theoretical limitations
A finite description index cannot encode all bytes cheaply. Matching a short
pattern is increasingly likely by chance as the bank grows; its address costs
about the same order as direct entropy coding. Address savings and reference
reuse must be paid by selection and residual information.

## 15. Conclusions
MSMC answers the original hypothesis on this finite tested setting: exact
mathematical slices exist, but economic gains on general-purpose inputs did
not follow. This is a negative result for the tested catalogs/indicators, not
a proof that no mathematical representation can ever help.

## 16. Reproduction instructions
Run `python -B measure.py control` after building `msm_index`; full test input
and baseline JSON are required. See [reproduction](../../docs/reproduction.md),
[protocol](../../lab/sxz-mathematical-mosaic/PROTOCOL.md), and the
[decision record](../errata.md). BBP/constant controls are in `diagnostics.py`.

## 17. References
Shannon, Kolmogorov, Rissanen, BBP, suffix arrays/FM-index, Re-Pair, Preflate,
JPEG XL, ZipNN, FM-Delta; see [related work](../related-work.md) and
[references](../references.bib).
