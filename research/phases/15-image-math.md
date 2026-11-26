# Phase 15 - Mathematical Image Representation

## 1. Research question

Can actual decoded image pixels be described more cheaply by coordinate
functions, geometric regions or small compositional function networks than by
matched conventional image controls?

## 2. Data

Six real images: two JPEG photographs (`banana`, `gull`), two graphics
(`python-logo` PNG, `transparency` BMP), and two screenshot/document images
(`exif` PNG, a research plot PNG). Large images use deterministic
maximum-variance 256x256 crops; `python-logo` is complete. RGBA alpha is
preserved. Original-file SHA-256 and decoded-pixel SHA-256 are recorded
separately. Images are not redistributed; provenance is in
`datasets/provenance.json`.

All results are **pixel-level**. Re-encoding a PNG/BMP/JPEG does not reproduce
the original compressed file; no original-file reconstruction is claimed.

## 3. Episode 1: fixed regions and analytical functions

Regions 8x8, 16x16, 32x32 and 64x64; constant, linear/quadratic, 2x2 piecewise
planes, radial/elliptical quadratic, bounded sinusoids, and linear+sinusoid
sums. Coefficients were fitted by least squares, quantized at scale 256, and
reconstructed by deterministic integer rounding. Residuals `(X-F) mod 256`
were compressed with zstd-9.

Controls: A direct zstd-9; B records+raw residual; C records+zstd-9 residual;
D left/up spatial prediction+zstd-9; E actual PNG of the same pixels; F lossless
JPEG XL unavailable. Constant/gradient-only control `C0` separated ordinary
flat-field prediction.

Complete tested crops:

| image | A | C | D | E PNG | exact |
|---|---:|---:|---:|---:|---:|
| banana | 82,336 | 81,887 | 65,203 | 62,612 | 18.75% |
| gull | 132,465 | 137,467 | 86,641 | 91,567 | 0% |
| python-logo | 3,873 | 4,051 | 4,448 | 4,157 | 9.86% |
| transparency | 9,674 | 5,649 | 1,829 | 896 | 20.83% |
| exif | 37,280 | 53,874 | 44,378 | 44,853 | 0% |
| fig1 | 52 | 925 | 53 | 686 | 76.56% |

No image had C below all matched controls. C beat A only for banana and
transparency, but lost to spatial/PNG by 19,275 B and 4,753 B. Exact coverage
was dominated by flat constant tiles. F is unavailable because no JXL encoder
was installed. Formula records were 288-960 B; residual streams remained large.
All six pixel arrays reconstructed exactly.

## 4. Episode 2: adaptive quadtree

A bounded 120-node quadtree compared constant, linear/quadratic, radial,
sinusoidal, linear+sinusoid, shared-family, per-channel mixed, palette (<=64
colors), two-color rectangle/ellipse, literal and spatial fallback. Cost was
records + zstd residual + tree topology.

Adaptive C reduced fixed-tile B on all six crops, but **C equaled the matched
adaptive control D on all six**. No palette, shape, shared or radial/sine leaf
was selected; selected leaves were only spatial, literal or constant. The only
crop where C was best among A/B/E/PNG was `python-logo` (3,529 B vs A 3,873,
B 4,051, PNG 4,157), and D was also 3,529 B.

Complete `python-logo`: C 3,529 B against A 3,873, B 4,051, F PNG 4,157; D
identical. Complete transparency/exif/fig1 quadtrees were skipped after the
180 s budget was reached. Exact mathematical coverage is 0%; constant leaves
are ordinary flat-field coverage, not nontrivial math.

**Runtime correction:** Episode 2's 56.04 s was total for six crops, not per
image. Per-image encoding was 2.1-4.9 s; decoding 0.00005-0.00024 s. The first
320-node full-image attempt exceeded 180 s and was stopped; the reported run
used 120 nodes and skipped complete transparency/exif/fig1. The 180 s figure
includes that interrupted attempt.

## 5. Episode 3: compositional function networks

A shared 28-node feature dictionary included coordinates, multiplication,
absolute value, min/max, thresholds and bounded sine/cosine. Greedy selection
used actual serialized JSON plus zstd-9 residual; channel weights were quantized
at scale 4096. D was linear/Fourier features without nonlinear composition; E
was the full dictionary. Direct and left-spatial residuals were both tested.

E improved linear control D on every crop by 190-6,179 B, but selected only two
nodes: `const` plus one threshold/coordinate feature. No depth-2/3 multiplied,
absolute, min/max or sinusoidal composition survived. Example banana RGB
channel 0: `(969693 - 36461*[y>=0])/4096`.

Only the gull crop was an isolated win: E 86,632 B vs spatial 86,641 and
adaptive 86,663. The improvement is `9/86,641 = 0.0104%`, not below 0.01%.
Complete images: no E result beat all controls. Logo E 4,449 vs C 3,529/A 3,873;
transparency E 189,951 vs B 183,239/PNG 173,913; exif E 73,644 vs A 73,403;
fig1 E 25,395 vs A 22,046. All crop and complete serialized networks decoded and
verified. JPEG XL remains unavailable; the greedy search was capped and is not
exhaustive.

## 6. Positive findings

Exact coordinate functions can describe flat graphic/screenshot tiles; adaptive
partitioning and ordinary spatial/PNG prediction are real gains; serialized
network and residual reconstruction is correct; a nonlinear dictionary can
slightly improve a linear feature control.

## 7. Negative findings and limitations

No consistent mathematical/geometric/net image-level gain; complete-image
results negative; the only gull win is 0.0104% and one crop; deep compositions
were never selected; no JXL comparison; no original-file reconstruction; crops
are 256x256 except one complete logo; no whole-file claim.

## 8. Reproduction

From the repository root:

```text
cd lab/sxz-image-math
python -B scripts/run_phase15.py
python -B scripts/run_phase15_ep2.py
python -B scripts/run_phase15_ep3.py
```

The scripts expect the reviewed image paths and do not redistribute the images.
Compact evidence: `lab/sxz-image-math/results/phase15.json`,
`phase15_ep2.json`, `phase15_ep3.json`. The local display of Persian/Unicode
text is not part of these reports.

## 9. References

Naderi Yeganeh, *Pictures from Networks of Mathematical Functions*, DOI
10.1080/10724117.2024.2368373: conceptual inspiration only; this project does
not reproduce his complete method, and no collaboration or endorsement is
implied. PNG specification; Zstandard RFC 8878; LosslessINR/COIN are related
image-representation work, not implemented here. See
[related work](../related-work.md) and [references](../references.bib).
