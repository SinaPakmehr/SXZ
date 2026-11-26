# Third-party notices and rights review

| Component | Relationship | Upstream license or status |
|---|---|---|
| SXZ original Python and native research code | Original project material, licensed outbound under MIT by the copyright holder | MIT (SPDX: MIT); see `LICENSE` |
| [preflate-rs](https://github.com/microsoft/preflate-rs) 0.7.6 | External Cargo dependency, not vendored | Apache-2.0; review locked transitive dependencies before distributing binaries |
| [NumPy](https://numpy.org/) and [python-zstandard](https://github.com/indygreg/python-zstandard) | Installed dependencies | BSD-3-Clause; review wheels and bundled components separately |
| [Brotli](https://github.com/google/brotli), [Pillow](https://python-pillow.org/) | Installed dependencies | MIT and HPND, respectively |
| [Python-FLINT](https://github.com/flintlib/python-flint), [FLINT](https://flintlib.org/) | Installed experimental dependencies | Review the exact wheel and its notices separately; no wheel is bundled |
| [JPEG XL](https://github.com/libjxl/libjxl), [7-Zip](https://www.7-zip.org/), [Zstandard](https://github.com/facebook/zstd) | External baseline tools/input sources | Refer to upstream releases; none of their binaries are published here |

Bibliographic references do not imply incorporation of third-party source.
The MIT grant applies only to original SXZ material authored by Sina Pakmehr.
Third-party software, datasets, model checkpoints, papers, trademarks and
external tools retain their own licenses and conditions; none are relicensed
here. No real input corpus, executable, checkpoint, dependency cache, or native
build is included in this candidate. Rights to reproduce a download and rights
to redistribute it are separate questions. AI-assisted material is included
without any claim of copyright beyond what applicable law permits.
