# Phase 20 - Mathematical Structure Attribution

## 1. Research question

Why were exact algebraic dependencies concentrated in the 7zr eight-byte
blocks? This phase distinguishes meaningful generative structure from ordinary
executable-format redundancy and chance. It does not implement a new
compression codec.

## 2. Previous evidence audit

The 63 relationship-participating eight-byte vectors have **GF(2) rank 26**
and **nullity 37**. The 122 four-value quadruples are redundant equations in
that 37-dimensional dependency space, not 122 independent dependencies. The
full 155-value 7zr region has rank 43/nullity 112.

A reduced basis of 26 vectors occupies 208 bytes. Coefficient-mask weights
range from 1 to 17, average 10.03. With one-byte IDs the value-set description
is 903 bytes; the raw 504-byte vector payload is smaller (567 bytes if every
value carries a one-byte tag). The reference-only bound for 32 targets is
`32*(8-4)=128` bytes at four-byte references and `32*(8-7)=32` bytes at
seven-byte references. The earlier 160/64 figures used mismatched tag
accounting.

The L=8 validation census has 936 relationship bytes and 872 nontrivial bytes.
The 64-byte difference is exactly BBC's three repeated values (48 B) plus
hopper's one repeated value (16 B); zero/constant/short-period values
contribute zero. The Phase 19 single-atom counts are 7zr 44, BBC 2 and IRS 23.

## 3. 7zr structure

The Phase 19 validation region is file offsets **598,528-602,623**, inside the
PE **`.reloc`** section (raw range 579,584-602,623). The PE layout is
`.text`, `.rdata`, `.data`, `.sxdata`, `.rsrc`, `.reloc`; the region is not
machine code, resources, padding or overlay. All 63 participating blocks are
8-byte aligned inside `.reloc`, span four relocation blocks and four pages,
and align to 2-byte relocation entries. They are 16-bit relocation fields
grouped into eight-byte words with address/pointer arithmetic.

The XOR relations are therefore address-table structure. They are not simply
single-lane coincidences: 114 of 122 quadruples have all eight byte lanes
active; seven have four and one has seven. Modular 64-bit addition gives a
larger census: 1,109 four-value equations, 129 values, 1,032 bytes (25.2%)
coverage, versus 504 bytes (12.3%) for XOR. Additive equations are counted as
unique pair-sum relations; no GF(2) nullity is assigned.

The strongest conventional control for the 7zr region is **shuffle2 + zstd-9
at 502 bytes**, versus 936 zstd-19, 948 zstd-9 and 983 LZMA2. Separating the
16-bit lanes already captures the relocation regularity; the exact algebraic
form does not improve on it.

## 4. Independent replication

Five additional real Windows executables/DLLs were selected by fixed structural
rules: first aligned `.text`, `.rdata`, `.data`, `.rsrc`, last `.reloc` 4 KiB
and a uniform midpoint. No file was selected by observed relationship strength.

| file | region | nontrivial coverage | basis rank/nullity | basis full-region estimate | best conventional |
|---|---|---:|---:|---:|---|
| notepad.exe | `.rdata` | 60.2% | 20 / 321 | 1,800 B | C_lzma2 769 B |
| cmd.exe | `.rdata` | 62.1% | 29 / 320 | 2,293 B | C_lzma2 960 B |
| kernel32.dll | `.reloc` | 30.9% | 30 / 128 | 4,740 B | shuffle2 648 B |
| advapi32.dll | `.reloc` | 50.4% | 33 / 230 | 4,632 B | shuffle2 960 B |
| powershell.exe | `.rdata` | 60.5% | 18 / 347 | 1,373 B | C_lzma2 730 B |

The dependencies replicate in `.rdata` and `.reloc`, but the basis
descriptions are dense (weights up to 22) and every full-region estimate is
larger than the best conventional transform. `.rdata` relations are often
lane-local (notepad 22,528/41,584 quadruples have at most two active lanes;
powershell 65,817/89,376), consistent with UTF-16/pointer/field formatting.
`.reloc` relations require byte-lane deinterleaving, which shuffle2 exploits.

Non-executable comparison regions are weak: book1 and PDF 0% nontrivial
coverage, BBC 1.8%, hopper 3.7%, ECG 2.9%; none reaches 10%.

## 5. Final systematic coefficient-mask audit

A basis was selected directly from the original participating vectors and
stored literally. Dependent vectors use one continuously packed r-bit mask
each. Full-region archives charge basis/dependent positions, reconstruction
order, occurrence tags/references, literals, metadata and framing.

For 7zr, the theoretical payload is `26*8 + ceil(37*26/8) = 208 + 121 = 329`
bytes. Actual sizes are:

| archive | bytes | zstd-9 |
|---|---:|---:|
| systematic value-set dictionary | 427 | 426 |
| ordinary value-set dictionary | 602 | 545 |
| raw vector payload / tagged literal | 504 / 567 | — |
| systematic full 4 KiB | 4,194 | 1,092 |
| ordinary full 4 KiB | 4,369 | 1,197 |
| literal full 4 KiB | 4,120 | 964 |
| best conventional (shuffle2) | — | 502 |

The systematic value-set dictionary genuinely saves 175 bytes over the
ordinary dictionary and 77 bytes over the raw 504-byte vector payload, but the
theoretical 329 bytes is not a serialized size. Once positions, occurrence
mapping and literal blocks are included, the full-region archive loses to the
literal and conventional controls. The same holds in the five replication
regions: full systematic zstd-9 sizes are 1,592-2,450 B versus 648-960 B for
the best conventional controls. Value-set savings are not full-region
compression.

## 6. Gate and decision

| gate | result | pass |
|---|---|---:|
| >=10% nontrivial coverage in >=2 additional files | 5/5 executables | yes |
| credible description-cost advantage not explained by standard transforms | 0/5 | **no** |

Coverage replicates; economic advantage does not. The dependencies are ordinary
executable-format redundancy in address and structured-data tables, already
exploited by byte-lane transforms. **Phase 19 is definitively closed negative
for the tested representations, and Phase 20 stops after Episode 1. No Phase 21
was started.**

## 7. Runtime and evidence

The structural audit took 20.499 s; the systematic audit 2.437 s. Cumulative
guard was 23.370 s, under the 180 s cap. All systematic, ordinary and literal
archives reconstructed from serialized bytes.

Public source and evidence are in
[`lab/sxz-attribution`](../../lab/sxz-attribution/). No Windows EXE/DLL files
are redistributed; the JSON records names, hashes and section offsets only.

- [`phase20-attribution.json`](../../lab/sxz-attribution/results/phase20-attribution.json)
- [`phase20-systematic-audit.json`](../../lab/sxz-attribution/results/phase20-systematic-audit.json)
- [`run_phase20.py`](../../lab/sxz-attribution/scripts/run_phase20.py)
- [`audit_phase20_systematic.py`](../../lab/sxz-attribution/scripts/audit_phase20_systematic.py)

## 8. References

The PE/COFF section format and relocation table are documented by the Microsoft
PE specification. Related algebraic work includes Sakata's 2D/N-dimensional
Berlekamp-Massey papers and Berthomieu, Boyer and Faugère, DOI
10.1016/j.jsc.2016.11.005; no complete BMS/Scalar-FGLM or Gröbner-basis
implementation is claimed. See [related work](../related-work.md) and
[references](../references.bib).
