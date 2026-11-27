# Phase 18 - Exact Spectral Representation

## 1. Research question

Can real byte regions be reconstructed exactly from sparse or highly
compressible Walsh-Hadamard, integer-Haar or identity coefficients and beat
matched compression controls? No coefficient is thresholded, deleted,
quantized or approximated. All metadata, block framing, coefficient payloads
and indices are charged.

## 2. Method

Three exact transforms were implemented:

- **FWHT:** `C = H x`, inverse `x = H C / N`, with exact divisibility checked
  for every coefficient.
- **Integer Haar lifting:** `d = b - a`, `s = a + floor(d/2)`, inverse
  `a = s - floor(d/2)`, `b = a + d`. Python integers prevent overflow.
- **Identity:** matched block/bit-plane representation without a spectral map.

Representations are original byte values or eight binary bit-planes. Block
lengths are 64, 256, 1024 and 4096 bytes. Three serializations were tested:
signed zigzag varints, biased fixed-width packing, and sparse nonzero indices
with delta positions. The smallest actual serialized archive selects the
encoding. The 4 KiB regions are the same six files and disjoint development/
validation regions as Phases 16-17. 48 spectral configurations per file were
measured on development; the smallest G (archive + zstd-9) was frozen before
validation.

Controls: **A** zstd-9, **B** zstd-19, **C** LZMA2, **D** matched identity
block/bit-plane representation + zstd-9, **E** delta/XOR/shuffle/global
transform + zstd-9, **F** exact spectral archive, **G** F + zstd-9. No raw
fallback is used in F/G. The baseline is min(A,B,C,D,E) per region.

## 3. Haar correction

The original implementation was reversible but not standard recursive
approximation-only Haar lifting. Its loop processed every block at every level:

```text
for start in range(0, n, step):
```

After the first level the second half contains detail coefficients; the next
level then decomposed those details. This is a full wavelet-packet transform.
For unsigned byte inputs the standard transform must keep approximations in
[0,255], details in [-255,255], `max|coeff| <= 255` and at most 511 distinct
values. The original exceeded these bounds (7zr max 534; ECG max 34,397 and
837 distinct). The selected original configurations were Haar bytes, so the
statistics were not accidentally taken from FWHT.

The corrected implementation processes only the approximation segment. It
matches an independent reference block-for-block, satisfies the bounds, and
reconstructs exactly. Original and corrected scripts, protocols and results
are preserved separately. The original G/base 1.993 is historical, not the
corrected outcome.

## 4. Corrected validation results

All selected configurations were standard Haar. Sizes are actual serialized
bytes; `nz` is the coefficient nonzero fraction.

| file | config | F | G | D | E | A | B | C | baseline | G/base | nz |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| book1 | bytes L4096 fixed | 4,114 | 3,650 | 2,536 | 2,125 | 2,116 | 2,095 | 2,182 | 2,095 | 1.742 | 0.950 |
| bbc | bytes L64 varint | 4,620 | 3,410 | 1,615 | 1,304 | 1,297 | 1,292 | 1,298 | 1,292 | 2.639 | 0.967 |
| 7zr | bit-planes L1024 fixed | 3,151 | 1,056 | 756 | 956 | 948 | 936 | 983 | 756 | 1.397 | 0.075 |
| irs1040 | bytes L256 fixed | 3,699 | 2,619 | 1,873 | 1,630 | 1,619 | 1,607 | 1,534 | 1,534 | 1.707 | 0.611 |
| hopper | bytes L64 varint | 5,387 | 4,486 | 3,773 | 3,225 | 3,430 | 3,294 | 2,933 | 2,933 | 1.529 | 0.990 |
| ecg | bit-planes L4096 fixed | 8,223 | 3,759 | 2,654 | 2,241 | 2,569 | 2,503 | 2,076 | 2,076 | 1.811 | 0.385 |
| **total** | | **29,194** | **18,980** | **13,207** | **11,481** | **11,979** | **11,727** | **11,006** | **10,686** | **1.776** | **0.360** |

The corrected aggregate is G/base 1.776 (G/A 1.584, G/D 1.437, G/E 1.653);
every file is between 1.397x and 2.639x baseline. Standalone F is 1.188N;
hybrid G is 0.772N. Corrected selected coefficient maxima are at most 246 and
distinct values at most 390.

## 5. Sparsity versus compression

Book1 4 KiB development, best encoding per representation:

| representation | L64 | L256 | L1024 | L4096 |
|---|---:|---:|---:|---:|
| FWHT bytes nonzero | 0.998 | 1.000 | 1.000 | 1.000 |
| Haar bytes nonzero | 0.951 | 0.953 | 0.955 | 0.953 |
| FWHT bit-planes nonzero | 0.776 | 0.820 | 0.846 | 0.860 |
| Haar bit-planes nonzero | 0.245 | 0.248 | 0.249 | 0.252 |

Standard Haar bit-planes are mathematically sparse (max coefficient 1, three
distinct values), but eight streams make F 7.2-8.2 KiB and G 4.0-4.4 KiB,
larger than Haar bytes (F 4.1 KiB, G 3.6-3.9 KiB). 7zr bit-planes at L1024
are 7.55% nonzero and F=3,151 B, but G=1,056 B versus matched D=756 B. This is
a localized encoding bottleneck, not a gate pass. The secondary sparsity
criterion was qualitative and was not numerically defined in the protocol;
only the 1%/two-file primary gate was formally frozen.

## 6. Gate and interpretation

| check | result | pass |
|---|---|---:|
| corrected F/G exact reconstruction | 12/12 | yes |
| G >= 1% saving vs strongest baseline on >=2 files | 0/6 | **no** |
| secondary sparsity | qualitative only | not a numeric check |

The corrected branch is negative. The original nonstandard transform is
retained as historical evidence, including its 1.993 ratio; the standard-Haar
corrected result is 1.776. No 16/64 KiB scaling was attempted because the
4 KiB panel already showed no savings and high nonzero fractions.

## 7. Runtime and limits

Cumulative guard (original + corrected runs) was 26.978 s: corrected
development 8.574 s and validation 1.067 s, with the original run preserved.
The audit itself and final runs stayed under the 180 s cap. Corrected encode
sum was 0.030 s, selected decode 0.039 s.

The experiment covers only exact integer transforms on bounded 4 KiB regions.
It does not implement lossless coefficient-bit quantization or the specialized
logic/spectral coding in the cited literature. No whole-file or general codec
claim is made.

## 8. Reproduction and evidence

Public code and evidence are in
[`lab/sxz-spectral`](../../lab/sxz-spectral/). The corpus files are not
redistributed. The corrected and original protocols, scripts, results and audit
are retained separately.

Key evidence:

- [`phase18.json`](../../lab/sxz-spectral/results/phase18.json) (corrected)
- [`phase18-original.json`](../../lab/sxz-spectral/results/phase18-original.json)
- [`phase18-haar-audit.json`](../../lab/sxz-spectral/results/phase18-haar-audit.json)
- [`protocols/phase18-corrected.json`](../../lab/sxz-spectral/protocols/phase18-corrected.json)

## 9. References

- Calderbank, Daubechies, Sweldens and Yeo, "Wavelet Transforms That Map
  Integers to Integers," Appl. Comput. Harmon. Anal. 5(3):332-369, 1998,
  DOI 10.1006/acha.1997.0238.
- Philips, Denecker, De Neve and Van Assche, "Lossless Quantization of
  Hadamard Transform Coefficients," IEEE Trans. Image Process.
  9(11):1995-1999, 2000, PMID 18262937, DOI 10.1109/83.877223.
- Falkowski, "Lossless Binary Image Compression Using Logic Functions and
  Spectra," Comput. Electr. Eng. 30(1):17-43, 2004,
  DOI 10.1016/S0045-7906(03)00035-1.

This implementation performs exact integer transforms only; it does not
implement those papers' specialized coefficient quantization or coding. See
[related work](../related-work.md) and [references](../references.bib).
