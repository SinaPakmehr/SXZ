# Phase 16 - Parameterized Mathematical Grammar

## 1. Research question

Can a bounded RePair grammar plus scalar parameterized byte templates produce
smaller exact archives than matched ordinary-grammar and transform controls on
real files? Coverage alone is not evidence: every dictionary record, rule id,
invocation parameter, literal, header and stream bit is charged.

## 2. Method

The codec uses literal fallback, cost-aware RePair pairs, and three exact
template operations on bytes, using addition and subtraction modulo 256 and bitwise XOR.
Arithmetic modulo 256 is over Z/256Z, not GF(2^8).

- `add: (T + a) mod 256`;
- `xor: T XOR a`;
- `sub: (a - T) mod 256`.

`T` is a literal template and `a` is one byte charged at each invocation.
Templates use fixed windows of 8, 16, 32, 64 or 128 bytes at half-window
strides. A rule requires at least two non-overlapping occurrences. Rules whose
template is constant or whose invocations all use the same parameter are
rejected, so exact repeats and constant runs cannot be counted as mathematical
gain.

The total budget is 128 rules, with at most 32 mathematical rules. Pair and
mathematical rules share that budget. Math invocations are barriers: pair rules
cannot cross them. Streams use either literal runs or a bitmap plus rule
references; the smaller serialized form is selected. The exact serialized
size is measured, not a coverage estimate.

An algebraic result simplifies the family: `sub(T,a) = add(-T,a) mod 256`.
With literal templates, SUB has the same cost and expressive power as ADD.
Zero SUB rules were selected. XOR remains independent. The three operators are
effectively two.

## 3. Data and frozen protocol

Six real inputs were used: `book1` (text), `bbc.rss.xml` (structured text),
`7zr.exe` (executable), `irs1040.pdf`, `hopper.bmp` and `ecg-holdout.bin`.
Two disjoint equal regions per file were capped at 32 KiB: first for
development, last for frozen validation. `bbc` and `hopper` cannot supply two
32 KiB regions, so they use 14,130 and 24,645 byte regions.

Controls:

- **A** zstd-9;
- **B** zstd-19;
- **C** raw LZMA2 preset 6 plus one selector byte;
- **D** ordinary bounded grammar;
- **E** development-frozen ordinary transform plus D;
- **F** D plus parameterized templates.

The E transform families selected on development were global-add (book1, 7zr,
irs1040), global-xor (bbc), delta (hopper) and stride-3 shuffle (ecg). A global
parameter is re-selected on each region and charged. The gate thresholds were
fixed before development and the protocol was frozen before validation.

## 4. Validation results

All sizes are actual serialized bytes. The table includes the three conventional
codecs and the matched grammar controls.

| input | bytes | zstd-9 | zstd-19 | LZMA2 | D | E | F | F/D | F/E |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| book1 | 32,768 | 14,204 | 13,829 | 13,701 | 22,175 | 22,180 | 22,175 | 1.0000 | 0.9998 |
| bbc | 14,130 | 3,372 | 3,351 | 3,343 | 11,164 | 11,169 | 11,164 | 1.0000 | 0.9996 |
| 7zr | 32,768 | 18,048 | 16,870 | 14,383 | 27,213 | 27,268 | 26,840 | 0.9863 | 0.9843 |
| irs1040 | 32,768 | 21,277 | 20,598 | 19,305 | 28,846 | 28,917 | 28,846 | 1.0000 | 0.9975 |
| hopper | 24,645 | 20,479 | 19,668 | 17,402 | 23,950 | 23,048 | 24,045 | 1.0040 | 1.0433 |
| ecg | 32,768 | 20,018 | 19,291 | 15,323 | 25,217 | 22,980 | 25,217 | 1.0000 | 1.0973 |
| **total** | **169,847** | **97,398** | **93,607** | **83,457** | **138,565** | **135,562** | **138,287** | **0.9980** | **1.0201** |

The development aggregate was D 141,492, E 137,672 and F 141,399 bytes, with
F/D 0.99934 and F/E 1.02707. Validation followed the same pattern.

## 5. Gate and interpretation

| check | result | pass |
|---|---|---:|
| exact D/E/F reconstruction | 36/36 archives | yes |
| math rules and invocations present | 64 / 347 | yes |
| F/D <= 0.98 | 0.99799 | **no** |
| F/E <= 0.99 | 1.02010 | **no** |
| files improved vs D >= 4/6 | 1/6 | **no** |

Only 7zr improved against D, by 373 bytes (1.37%). Hopper was 95 bytes worse;
the other four files tied D. The aggregate F advantage over D was 278 bytes
(0.20%), while E was 2,725 bytes smaller than F. Math rules occurred only in
hopper development/validation and 7zr validation: 3,392 covered bytes. Their
templates, records and parameters cost 1,352 bytes directly; displaced pair
rules and stream framing account for the rest of the gap. The structure is
localized and not substantial at panel level. Parameterized scalar templates
therefore produced no meaningful independent gain under exact cost accounting.

## 6. Limits

The 128-rule grammar is far from zstd/LZMA absolute sizes; the experiment tests
mechanism gain, not state of the art. The transform-family control was selected
on development using a compressed-size proxy, so its validation result may be
conservative. Fixed half-window grids can miss unaligned occurrences. No joint
E+F branch was tested: math rules and pair rules share a budget, and pair rules
cannot cross math invocations. `bbc` and `hopper` use smaller half-file regions.

The reported 22.01 s is final script execution only (12.07 s development plus
9.94 s validation with a six-process pool), not the total interactive session.

## 7. Reproduction and evidence

The public source, frozen protocol and compact results are in
[`lab/sxz-math-grammar`](../../lab/sxz-math-grammar/). The scripts expect the
six corpus files at the documented `datasets/corpus/` paths; the inputs are not
redistributed. A disposable copy is required because the runner writes results.

Evidence:

- [`results/phase16.json`](../../lab/sxz-math-grammar/results/phase16.json)
- [`results/phase16-dev.json`](../../lab/sxz-math-grammar/results/phase16-dev.json)
- [`protocols/phase16-protocol.json`](../../lab/sxz-math-grammar/protocols/phase16-protocol.json)

## 8. References

Larsson and Moffat, Re-Pair, DOI 10.1109/5.892708; Zstandard RFC 8878; XZ/LZMA2
format. See [related work](../related-work.md) and
[references](../references.bib). This is a bounded experiment, not a claim of a
new general-purpose compressor.
