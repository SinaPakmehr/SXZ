# Phase 19 - Adaptive Algebraic Dictionary Discovery

## 1. Research question

Can a bounded dictionary of reusable fixed-length byte-block atoms plus exact XOR
compositions encode aligned blocks more cheaply than an ordinary block
dictionary? The experiment tests exact GF(2) compositions; it is not
approximate dictionary learning or low-rank matrix factorization.

## 2. Method

Aligned blocks of 8, 16, 32 and 64 bytes are treated as binary vectors. Atom
candidates come from frequent distinct source blocks and frequent pairwise XOR
differences in a bounded top-block pool. Greedy selection uses an estimated
description-length reduction over a bounded sample, followed by actual
serialized archive verification. Capacities of 16, 32 and 64 atoms were tested.
Blocks are encoded as a literal, one atom, XOR of two distinct atoms, or (for
the best development configuration) XOR of three distinct atoms. The complete
dictionary is stored in every archive; the decoder needs no external training
data.

Two learning modes were measured separately:

- **dev_transfer:** dictionary learned on the development region, applied
  unchanged to validation;
- **local:** dictionary learned on the validation region using the same frozen
  settings.

Controls: A zstd-9, B zstd-19, C LZMA2, D ordinary single-atom dictionary,
E fixed 8L-bit GF(2) basis, D_F the exact F dictionary with composition
disabled, F learned XOR dictionary, G F + zstd-9. D/E were also zstd-compressed.
Baseline is min(A,B,C,D,D_zstd,E,E_zstd,D_F,D_F_zstd). Literals, atoms, IDs,
tags, references, metadata and framing are charged.

The six real files and first/last disjoint 4 KiB regions are used. 16 KiB was
not attempted because 4 KiB already produced no selected multi-atom encodings
and no savings. The gate and search space were fixed in `protocol-19.json`;
the selected settings were frozen in `protocol-19-frozen.json` before
validation.

## 3. Selected development settings

Every file selected **L=64 bytes, capacity 16, max_atoms=2**. The learned
dictionary was empty for book1, bbc, irs1040, hopper and ecg, and contained one
rank-0 all-zero atom for 7zr. All tested two-atom configurations and the best
three-atom pass produced zero two/three-atom compositions on development. The
smallest archive therefore selected the fewest blocks with the least framing.

## 4. Validation

| file | atoms dev/local | rank | F dev/local | G dev/local | D_F zstd | E zstd | baseline | G/base dev/local | one-atom blocks |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| book1 | 0 / 0 | 0 | 4,171 / 4,171 | 2,221 / 2,221 | 2,221 | 2,129 | 2,095 | 1.060 / 1.060 | 0 / 0 |
| bbc | 0 / 1 | 0/1 | 4,171 / 4,109 | 1,491 / 1,495 | 1,491 / 1,495 | 1,309 | 1,292 | 1.154 / 1.157 | 0 / 2 |
| 7zr | 1 / 1 | 0 | 1,463 / 1,463 | 980 / 980 | 979 | 958 | 936 | 1.047 / 1.047 | 44 / 44 |
| irs1040 | 0 / 1 | 0/1 | 4,171 / 2,786 | 1,685 / 1,690 | 1,685 / 1,689 | 1,629 | 1,534 | 1.098 / 1.102 | 0 / 23 |
| hopper | 0 / 0 | 0 | 4,171 / 4,171 | 3,523 / 3,523 | 3,523 | 3,437 | 2,933 | 1.201 / 1.201 | 0 / 0 |
| ecg | 0 / 0 | 0 | 4,171 / 4,171 | 2,664 / 2,664 | 2,664 | 2,581 | 2,076 | 1.283 / 1.283 | 0 / 0 |
| **total** | | | **22,318 / 20,871** | **12,564 / 12,573** | **12,563 / 12,571** | **12,043** | **10,866** | **1.156 / 1.157** | |

F/G selected no tag-2 or tag-3 encodings. The nonliteral selected blocks were
7zr 44 one-atom zero blocks, BBC 2 one-atom blocks in local mode, and IRS 23
one-atom blocks in local mode. All are one-atom; the 7zr zero atom is trivial.
Dictionary rank was zero except the local BBC/IRS one-atom dictionaries
(rank 1). The matched ablation D_F was essentially identical to F, so the
learned dictionary provided no composition gain. The fixed basis E_zstd was
smaller than F/G.

## 5. Exhaustive relationship census

A separate census enumerated all distinct block values and all unordered
pairs at each of the four block lengths (8, 16, 32 and 64 bytes), with no
candidate pruning. It measured both three-value `A XOR B = C`
and four-value `A XOR B = C XOR D` relations.

| length/split | distinct | pairs | three-value | four-value | relation coverage | nontrivial coverage |
|---|---:|---:|---:|---:|---:|---:|
| 8 dev | 2,891 | 700,138 | 0 | 8 | 1.27% | 0.85% |
| 8 val | 2,423 | 540,423 | 0 | 139 | 3.81% | 3.55% |
| 16 dev/val | 2,747 | 329,546 | 0 | 0 | 0 | 0 |
| 32 dev/val | 1,389 | 83,768 | 0 | 0 | 0 | 0 |
| 64 dev/val | 699 | 20,982 | 0 | 0 | 0 | 0 |

No distinct three-value relation exists anywhere. Four-value relations exist
only at L=8. The earlier statement that every participant was
unique was too strong: the validation total is 936 relationship bytes, of
which 872 are nontrivial; the 64-byte difference is BBC's three repeated
values (3 x 2 x 8 = 48 B) plus hopper's one repeated value (2 x 8 = 16 B).
Zero/constant/short-period values contribute zero.

The 7zr validation region dominates: 122 unique quadruples, 63 values,
12.3% nontrivial coverage, GF(2) rank 26. This is available structure, not
selected multi-atom encoding. The gate required at least 10% nontrivial
multi-atom coverage in two validation files; only one file reached it, so the
secondary branch fails. The 12 paired F/G checks refer to 24 individual
archives (six files x two modes x two variants), not 12 archives.

## 6. Gate and interpretation

| gate | result | pass |
|---|---|---:|
| G >= 1% saving vs strongest baseline on >=2 files | 0/6 in both modes | **no** |
| selected nontrivial multi-atom coverage >= 10% on >=2 files | 0/6 | **no** |
| exhaustive available L=8 four-value coverage >= 10% | 1/6 (7zr only) | **no** |

The branch is negative. Zero selected compositions does not mean zero available
relations: the L=8 census found real four-value structure, concentrated in
7zr. The Episode 1 dictionary simply did not select or encode it. That is a
selection/encoding bottleneck, not evidence for a broad compression gain.

## 7. Runtime and evidence

Cumulative guard was 6.292 s (development 0.868 s, validation 0.586 s,
exhaustive audit 4.838 s). Encoding sum was 0.020 s; selected decoding sum was
0.0004 s. All selected/control archives reconstructed from serialized bytes.

Public source and evidence are in
[`lab/sxz-xordict`](../../lab/sxz-xordict/). The inputs are not redistributed.

- [`phase19.json`](../../lab/sxz-xordict/results/phase19.json)
- [`phase19-dev.json`](../../lab/sxz-xordict/results/phase19-dev.json)
- [`phase19-xor-audit.json`](../../lab/sxz-xordict/results/phase19-xor-audit.json)
- [`protocols/`](../../lab/sxz-xordict/protocols/)

## 8. References

Aharon, Elad and Bruckstein, "K-SVD: An Algorithm for Designing Overcomplete
Dictionaries for Sparse Representation," IEEE Trans. Signal Process.
54(11):4311-4322, 2006, DOI 10.1109/TSP.2006.881199. Ramirez, "Binary Matrix
Factorization via Dictionary Learning," arXiv:1804.05482. This is a bounded
exact XOR experiment, not an implementation of either approximate method. See
[related work](../related-work.md) and [references](../references.bib).
