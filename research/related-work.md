# Related work

See the [structured bibliography](references.bib). The distinguishing
question here is attribution under paired controls, not priority for the
general idea of generative compression.

- Shannon (1948), Kolmogorov (1965) and Rissanen (1978) establish separate
  notions of expected coding cost, individual description complexity and model
  selection. None implies that a finite search can compress arbitrary data.
- Ziv and Lempel (1977), Larsson and Moffat's Re-Pair (2000), and
  [Sequitur](https://doi.org/10.1613/jair.374) reuse observed structure.
  A generative external dictionary still pays for selecting its addresses;
  it is not fundamentally exempt from dictionary costs. See
  [Zstandard](https://www.rfc-editor.org/rfc/rfc8878),
  [Brotli](https://www.rfc-editor.org/rfc/rfc7932) and
  [XZ/LZMA2 format](https://tukaani.org/xz/xz-file-format.txt).
- Bounded synthesis constructs compositional programs; symbolic regression,
  e.g. [Schmidt and Lipson, 2009](https://doi.org/10.1126/science.1165893),
  searches relations from observations. A neat fitted equation is not an
  exact compressed representation until all residual and model costs count.
- [Precomp](https://github.com/schnaader/precomp-cpp),
  [Preflate-RS](https://github.com/microsoft/preflate-rs),
  [Lepton](https://github.com/dropbox/lepton), and
  [libjxl](https://github.com/libjxl/libjxl) are prior engineering references
  for reversible format exposure or JPEG reconstruction. Their gains are
  not attributable to the SXZ search.
- [Gorilla](https://doi.org/10.14778/2824032.2824078),
  [ZipNN](https://arxiv.org/abs/2411.05239), and
  [Brevis](https://arxiv.org/abs/2608.02162) address domain-specific data.
  The latter two links are preprints; Brevis synthesizes typed tensor programs
  and is not a controlled same-input benchmark against this project.
- Pi-based compression has an established informal prior-art trail:
  [GB2401443A](https://patents.google.com/patent/GB2401443A/en) (published
  2004, application later withdrawn), [pi-encode](https://github.com/daxtens/pi-encode)
  (a toy encoder with no decoder), and
  [Achieving Awful Compression with Digits of Pi](https://ntietz.com/blog/why-we-cant-compress-messages-with-pi/)
  (an experiment about the address-cost limitation). The
  [PiC — Constants as Compression Generators](https://www.mdlxdcc.org/crp/pic)
  page is an informal research proposal/specification, not a peer-reviewed
  result; it describes an MDL-gated experiment and does not claim a measured
  general win. It could not be located under an academic publication record,
  so treat it as a research proposal.
- [Bailey–Borwein–Plouffe](https://doi.org/10.1090/S0025-5718-97-00856-9)
  supplies digit extraction, not an assurance of cheap target locations.

## Public patent applications

- [GB2401443A](https://patents.google.com/patent/GB2401443A/en),
  David Vincent Broadway, published 2004-11-10, *Data compression using the
  index of a string of digits in the expansion of an irrational number*.
  Includes position-and-length encoding and illustrative examples; its claims
  are not empirical guarantees or evidence of unlimited compression.
- [CN113553002A](https://patents.google.com/patent/CN113553002A/en),
  published 2021-10-26, *Method for compressing and storing data by using
  characteristics of irrational numbers*.
- [WO2025163632A1](https://patents.google.com/patent/WO2025163632A1/en),
  published 2025-08-07, *Compression and encryption of data using irrational
  numbers*.

These are application publications, not peer-reviewed research, benchmarks,
or a freedom-to-operate opinion. See linked records for inventor metadata
and legal status.
