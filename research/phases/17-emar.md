# Phase 17 - Exact Multidimensional Algebraic Representation

## 1. Research question

Can exact algebraic decompositions and bounded logical models describe real
byte regions more cheaply than matched compression controls? The phase tested
three branches under exact reconstruction: finite-field tensor factorization,
reduced ordered binary decision diagrams (ROBDDs), and bounded multidimensional
recurrences. All costs, including dictionaries, boundaries, residuals and
framing, are charged.

## 2. Common data and arithmetic

The six real files from the surrounding phases are used: `book1`,
`bbc.rss.xml`, `7zr.exe`, `irs1040.pdf`, `hopper.bmp` and `ecg-holdout.bin`.
Development and validation use first/last disjoint regions. Episode 1 uses
4/16/64 KiB regions, Episode 2 the same 15 regions, and Episode 3 only 4 KiB
regions. No synthetic benchmark data is included.

Controls differ by episode and are defined explicitly:

- **Episode 1:** A zstd-9 raw; B zstd-19 raw; C raw LZMA2 preset 6 plus one
  selector byte; D selected coordinate ordering + zstd-9 without decomposition;
  E exact serialized matrix/TT representation alone; F E + zstd-9; G best
  conventional transform (delta, stride-3 shuffle, global add/xor) + zstd-9.
  The baseline is min(A,B,C,D,G) per region.
- **Episode 2:** A zstd-9 raw; B zstd-19 raw; C raw LZMA2 preset 6 plus one
  byte; D matched bit-plane and coordinate transform + zstd-9; E selected graph
  without redundant-variable elimination (exact); E_zstd9 is the same graph
  compressed; F exact selected diagram; G F + zstd-9. The baseline is
  min(A,B,C,D,E,E_zstd9).
- **Episode 3:** A zstd-9 raw; B zstd-19 raw; C raw LZMA2 preset 6 plus one
  byte; D best delta/XOR/spatial predictor + zstd-9; E one-dimensional
  recurrence with the same boundary mask and flattened lags; F multidimensional
  recurrence with raw XOR residuals; G the same recurrence with zstd-9
  residuals. The baseline is min(A,B,C,D,E_best), where E_best is the best 1D
  variant.

Episode 1 reuses GF(2^8) with irreducible polynomial `0x11B`; addition is XOR
and multiplication/inversion use log/exp and 256x256 tables. All tensor algebra
is exact. No floating-point SVD, thresholding or residual fitting is used.

## 3. Episode 1 - exact matrix and Tensor-Train decomposition

Regions are reshaped into 2D, 3D, 4D, 4-ary and binary tensors. Five shapes and
three reversible coordinate orders (linear, axis-reverse and odd/even bit
grouping) were tested: 15 configurations per file/size, 225 development
configurations. Matrix factors use deterministic finite-field RREF
`M = U V`. TT cores use sequential rank factorization with
`T(i1,...,id) = G1(i1)...Gd(id)` and `r0 = rd = 1`.

For every file/size the smallest compressed representation F selected 2D
linear matrix factorization. The smallest exact representation E selected 3D
TT. The development E was always larger than raw; the minimum coefficient
ratio was 1.0586 (7zr 4 KiB). No configuration was below 0.75N.

| validation aggregate | A | B | C | D | E | F | G | F/base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 15 regions, 368,640 B input | 202,839 | 194,804 | 175,942 | 203,061 | 711,639 | 212,510 | 192,163 | 1.209 |

The per-region best-baseline denominator min(A,B,C,D,G) sums to 175,765 B.
F/min-baseline is 212,510 / 175,765 = 1.209. F/A was 1.048, F/C 1.208,
F/D 1.047, F/G 1.106; E was 1.930N, much larger than F.
A 7zr 4 KiB region had rank 20/64 and E = 2,580 B, but F = 1,354 B
versus a 936 B baseline; the low rank did not survive 16/64 KiB scaling. A
3D full-rank TT cost 1.078N, while 2D was 2.000N and binary tensorization
2.667N; higher dimensionality redistributed information into larger cores, not
a shorter description. The gate failed 0/6 and the branch closed negative. All 30 E/F archives and the
matched controls reconstructed from serialized bytes with matching SHA-256.

**Runtime correction:** the first scalar-2D validation run took 208.24 s and
exceeded the 180 s limit. It is preserved as `phase17-val-initial.json`. After a
decoder-only row-vectorized speedup, all sizes, ranks, hashes and gate outcomes
were identical. Final E1 development plus validation was 14.24 s; this is the
final run, not cumulative time including the failed attempt.

## 4. Episode 2 - exact Boolean decision diagrams

The second branch treats the `k` position bits as variables. Three
representations were tested: eight Boolean bit-plane ROBDDs with separate node
dictionaries, the same eight planes with one shared dictionary, and one MTBDD
with byte terminals. Four variable orders and both reductions (merge identical
nodes, eliminate equal-low/high nodes) were used. Graphs serialize level-wise
with charged roots, terminals, level counts and compact child references.

The raw development record contains **180 tested configurations** (15 regions
x 12 configurations) and **15 selected regions**. The frozen protocol field
`dev_summary.configurations=15` counted selected regions, not tested
configurations; this report uses the raw record.

| episode 2 aggregate | F | G | D | E | E_zstd | A | B | C | baseline | G/base |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 15 regions, 368,640 B | 796,012 | 518,719 | 242,246 | 811,772 | 529,049 | 202,839 | 194,804 | 175,942 | 175,416 | 2.957 |

The selected graphs contained 216,287 nonterminals (0.587N) and 568 terminal
entries; exact F was 2.159N. Reductions removed 38.5% by equal children and
49.9% by merging; 11.6% survived. Removing redundant-variable elimination
increased size by only 1.98%. Shared dictionaries shared nodes across planes
but compressed worse; all 15 selections were MSB-first, with 10 separate
graphs and 5 MTBDDs. No file saved at least 1%; the gate failed 0/6. All 45 F/G/E archives and the
D/A/B/C controls reconstructed exactly. This is a bounded graph serializer, not the specialized Kieffer-Flajolet-Yang encoding
algorithm, and no novelty is claimed.

## 5. Episode 3 - bounded multidimensional recurrences

Episode 3 tested causal 2D, 3D and 4D recurrences with at most 16 coefficients,
axis/diagonal/mixed shifts, first/second-order lags and an optional affine
constant. Coefficients were fitted on a deterministic initial prefix and
verified on remaining eligible coordinates. Boundary values and exact residual
variants were charged. A matched 1D recurrence used the same boundary mask and
flattened lags.

| aggregate | raw/residual | compressed residual | 1D control | baseline | ratio | boundary |
|---|---:|---:|---:|---:|---:|---:|
| 6 x 4 KiB validation | 33,608 | 25,863 | 25,756 | 10,866 | 2.380 | 14,127 |

No exact nontrivial law was found: the full half-prefix was inconsistent and
the longest consistent prefix was only 2-10 coordinates. Training fits were
exact on those tiny prefixes, but held-out rates were 0.31-64.7%. The 7zr
model reached 64.7% held-out coverage but remained approximate. All 18
selected/raw-residual/1D-control archives reconstructed exactly; all gates
failed and the branch closed negative. This is a bounded BMS/Scalar-FGLM-inspired
experiment, not a complete implementation of either method. No Gröbner basis
was computed or claimed.

## 6. Cross-episode interpretation and limits

All three branches lose to matched controls on their tested panels. Episode 1's
E1 numbers and Episode 2/3 numbers are not a single same-size benchmark: E1
spans 4/16/64 KiB, E2 uses the same 15 regions, and E3 uses only 4 KiB. The
negative results are bounded to the chosen families, budgets and regions, not
universal impossibility claims. The TT result is an exact finite-field
adaptation; approximate real-valued tensor behavior need not transfer.

## 7. Reproduction and evidence

Public source, protocols and compact results are under
[`lab/sxz-emar`](../../lab/sxz-emar/). The runners expect corpus fixtures under
`datasets/corpus/`; original files, including 7zr and ECG, are not
redistributed. Historical failed/corrected runs are retained rather than
overwritten. Run scripts in a disposable copy because they write results.

Key evidence:

- E1: [`phase17.json`](../../lab/sxz-emar/results/phase17.json),
  [`phase17-dev.json`](../../lab/sxz-emar/results/phase17-dev.json),
  [`phase17-val-initial.json`](../../lab/sxz-emar/results/phase17-val-initial.json)
- E2: [`phase17b.json`](../../lab/sxz-emar/results/phase17b.json),
  [`phase17b-dev.json`](../../lab/sxz-emar/results/phase17b-dev.json)
- E3: [`phase17c.json`](../../lab/sxz-emar/results/phase17c.json),
  [`phase17c-dev.json`](../../lab/sxz-emar/results/phase17c-dev.json)
- Frozen records: [`protocols/`](../../lab/sxz-emar/protocols/)

## 8. References

- Oseledets, "Tensor-Train Decomposition," SIAM J. Sci. Comput. 33(5), 2011,
  DOI 10.1137/090752286.
- Khoromskij, "O(d log N)-Quantics Approximation of N-d Tensors in
  High-Dimensional Numerical Modeling," Constr. Approx. 34, 2011,
  DOI 10.1007/s00365-011-9131-1.
- Bryant, "Graph-Based Algorithms for Boolean Function Manipulation," IEEE
  Trans. Computers, 1986, DOI 10.1109/TC.1986.1676819.
- Kieffer, Flajolet and Yang, "Universal Lossless Data Compression Via Binary
  Decision Diagrams," arXiv:1111.1432.
- Sakata, minimal 2D recurring relations (1988); N-dimensional
  Berlekamp-Massey (1990).
- Berthomieu, Boyer and Faugère, DOI 10.1016/j.jsc.2016.11.005; Berthomieu and
  Faugère, arXiv:2107.02582.

The last two are related linear-algebra/Gröbner references; this project did not
compute a Gröbner basis. See [related work](../related-work.md) and
[references](../references.bib).
