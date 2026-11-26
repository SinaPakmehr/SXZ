# Phase 12 - Adaptive Mathematical Representation Discovery (AMRD)

## 1. Research question

Can simple mathematical laws be extracted directly from numerical
representations of real files by algebraic algorithms, without brute-force
coefficient enumeration? The phase also asks whether reversible representations
or cross-plane dependencies expose laws hidden from the raw byte stream.

## 2. Mathematical formulation

AMRD views the same bytes as `u8`, `u16le/be`, `u32le/be`, `u64le/be` and eight
bit planes. It implements:

- constant finite differences up to order 3 modulo `2^w`;
- `x[n] = a*x[n-1] + c` from `D[n] = a*D[n-1]`, with exact odd inverses and
  common-power-of-two removal;
- `x[n] = a*x[n-1] + b*x[n-2] + c` from a 2x2 difference system, using only
  odd-determinant equation subsets and recording singular/unresolved windows;
- Berlekamp-Massey over GF(2) on individual bit planes.

A window has 64 or 256 symbols, fits on the first half, must predict the second
half exactly, and is extended to the first mismatch. Records serialize family,
representation, alignment, start, span, coefficients, initial state and
metadata. Constant-tail and degenerate-tail candidates are rejected.

## 3. Reversible representations and cross-plane work

Episode 2 tests identity, byte delta, XOR-with-previous-byte, byte-plane shuffle
widths 2/3/4, shuffle-3 plus delta, and eight-plane separation on three real
32 KiB samples plus one interleaved synthetic control. Episode 3 tests
cross-plane bit operations `Y = X XOR (((X>>j)&1)<<i)`, two-source variants and
bounded compositions, combined with identity, bit planes, shuffle and delta.

All transforms were inverted and checked byte-for-byte. The synthetic control is
explicitly synthetic and is not counted as a real-data gain.

## 4. Dataset and settings

Panel: eight real files, 1,613,679 scanned bytes from 5,468,160 original bytes
(large files sampled to 256 KiB): text, XML, executable, PDF, BMP, ECG, JPEG and
DOCX. Synthetic controls: cubic, affine1, affine2, 16-bit LFSR, 1%-corrupt
affine2 and uniform random. Episode 2/3 use fixed real regions and recorded
offsets; Phase 13 extends scaling.

No coefficient grid, GPU or ML was used in the algebraic inference. Search
budgets and fixed windows were declared before the final run.

## 5. Results

- 677,421 windows; 8,728 consolidated models (933 word, 7,795 bit-plane).
- Word coverage 361,282 B (22.39% of scanned bytes), all constant/periodic.
- **Zero nontrivial polynomial or affine spans** after degenerate-tail removal.
- Held-out/nontrivial coverage: 0 B.
- Bit-plane coverage: 3,900,113 of **12,909,432 unique original bit positions**
  (30.21%), after excluding tails. Plane coverage is not whole-byte coverage.
- Synthetic controls recovered exactly: cubic, affine1, affine2, LFSR16;
  random control produced 0 models in 110,050 windows.
- Corrupt affine2 control recovered `a=5,b=11,c=12345` with 98.999% symbol
  accuracy (41 residual symbols); residual stream 8,192 B, zstd-19 219 B,
  LZMA2 260 B. This is a diagnostic, not a compressed-residual archive.
- BM orders 3-64, median 15; normalized LC 0.023-0.625. Bit-plane recurrences
  are structural observations, not whole-byte compression.
- Episode 2 reversible transforms produced ordinary savings (e.g. ECG
  shuffle3+delta 20,330 -> 11,105 B), but no new real algebraic law. The
  synthetic interleaved control produced a cubic low-byte law.
- Episode 3 cross-plane additions beat the best existing transform on **0/8**
  files; a 1%-and-128-B criterion was met on 0 files. The best cross candidate
  was 1 B worse (EXE) or 7-18 B worse elsewhere.

## 6. Reporting corrections

Episode 1's original bit denominator `103,275,456` was `64N`, an 8x overcount;
the correct unique-original-bit denominator is `8N=12,909,432`. The raw JSON
retains the historical field. The random-control `2.7e-5` value is a nominal
per-window rule-of-three scale, **not** an independent-trials confidence bound
because windows overlap.

## 7. Positive findings

The direct inference pipeline is correct on controlled synthetic data; exact
record reconstruction was verified for all 8,728 consolidated models; the
random control produced no false positives; ring-aware affine handling and
singular-system accounting are explicit; transform-only gains are real but
ordinary.

## 8. Negative findings and limitations

Real files in this panel contain no nontrivial algebraic law at the tested
scales. Word coverage is simple constants/periodicity; bit-plane BM coverage is
not byte-level and rarely pays; cross-plane metadata is never recovered at
archive level. The panel is small, files are sampled, transform selection is
adaptive per file, and no whole-file archive was built.

## 9. Reproduction

From the repository root:

```text
cd lab/sxz-amrd
python -B -m unittest scripts.test_amrd -v
python -B scripts/run_controls.py
```

The controls generate deterministic local fixtures. The full panel and EP2/EP3
runners require the reviewed real inputs; absent inputs are documented rather
than substituted. Compact evidence:
`lab/sxz-amrd/results/controls.json`, `analysis.json`,
`alignment.json`, `existing-compare.json`, `episode2.json`, `episode3.json`,
`panel-summary.json`.

## 10. References

Shannon (1948); Rissanen (1978); Berlekamp (1968); Massey (1969); Zstandard RFC
8878; LZMA2/XZ format; SXZ3/SXZ4 reports. The finite-difference, affine and BM
constructions are adaptations of established methods; the scanner, record
economics, order-3 difference model and cross-plane diagnostics are this
project's implementation.
