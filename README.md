# SXZ — Searching for Data in the Universe of Mathematics

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status: Experimental research](https://img.shields.io/badge/status-experimental%20research-orange.svg)](ROADMAP.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](requirements/research.txt)
[![Rust](https://img.shields.io/badge/Rust-stable-000000.svg)](docs/reproduction.md)

*An open research project exploring mathematical and generative approaches to lossless data compression.*

[English](README.md) | [Persian](README-fa.md)


## How It All Started

What if, instead of storing information bit by bit, we could describe it using mathematical rules, formulas, constants, and numerical sequences — and regenerate the original data whenever we needed it?

You may have heard that your phone number, your birthday, and potentially much longer sequences of information could be hiding somewhere within the digits of π. Although it has not been proven that every possible finite digit sequence occurs in π, I find the possibility itself fascinating.

Perhaps you've also generated a random number and noticed that several of its digits happen to match part of your own phone number.

Now imagine doing this on a much larger scale. Instead of a handful of digits, imagine millions or billions of symbols. Instead of a single mathematical constant, imagine an entire library of mathematical functions, number-theoretic sequences, prime numbers, constants, and pseudorandom generators.

Could we find pieces of our digital information somewhere within these sequences? Could we store instructions for regenerating those pieces rather than storing the pieces themselves? And, most importantly, could those descriptions actually be smaller than what existing compression algorithms produce?

These are the questions that led me to start SXZ.

## Why I Think This Is Worth Exploring

Even if we could achieve just a 2% reduction in compressed size compared with strong existing compression algorithms, that improvement could be valuable given the enormous amount of data humanity stores and transfers every day.

One particularly interesting possibility is asymmetric compression: performing computationally expensive searches during encoding while keeping decoding fast and lightweight.

If successful, such an approach could have applications in cloud storage, data transmission, data centers, software distribution, and AI model distribution.

We can use AI agents to formulate hypotheses, develop algorithms, run experiments, and analyze results. Combining these capabilities with careful controls, reproducible artifacts and substantial computational resources might open research directions that were previously harder to investigate.

Of course, more computing power alone does not guarantee a solution. Perhaps the answer lies in a better algorithm. Perhaps it requires an entirely different mathematical formulation of the problem.

That is part of what makes this research interesting.

## Has This Idea Been Explored Before?

Yes, aspects of this idea have been explored before. I personally discovered several of these earlier attempts after already going through multiple stages of developing SXZ.

Some interesting examples include:

- [GB2401443A](https://patents.google.com/patent/GB2401443A/en) — a patent application with a 2003 priority date, exploring data compression through the locations of digit sequences within irrational numbers.
- [CN113553002A](https://patents.google.com/patent/CN113553002A/en) — a 2021 patent application exploring compression and storage using properties of irrational numbers.
- [pi-encode](https://github.com/daxtens/pi-encode) — an experimental implementation exploring how information can be located within the binary digits of π.
- [Achieving Awful Compression with Digits of Pi](https://ntietz.com/blog/why-we-cant-compress-messages-with-pi/) — a 2024 experiment demonstrating the difficulties of compressing information through references to π.
- [PiC — Constants as Compression Generators](https://www.mdlxdcc.org/crp/pic) — a closely related research proposal exploring mathematical constants as generative sources for compression.

I see these earlier attempts as an opportunity to learn from others rather than a reason to abandon the question.

SXZ attempts to investigate a broader collection of hypotheses systematically, ranging from algebraic relationships and program synthesis to mathematical sequence mosaics, alternative numerical representations, and adaptive pseudorandom generators.

## An Invitation to Curious Minds

I started this project out of personal curiosity, with the limited computational resources available to me and the help of two AI systems: **GPT-6.2 (Sol)** as a research and discussion partner, and **DeepSeek V4.1 Flash** as a coding and experimentation agent.

With their assistance, I explored hypotheses, developed experimental architectures, implemented algorithms, and examined the results. Some experiments produced remarkable results on synthetic data. Others failed to provide meaningful improvements on real-world files. The AI systems assisted the research; their outputs are not a substitute for independent verification.

But I don't want this project to be limited to my own ideas or experiments.

I'm genuinely excited to see what a mathematician, computer scientist, machine learning researcher, compression expert, or simply another curious developer might discover by approaching the problem from a different perspective.

If you have access to substantial computational resources, enjoy number theory, work on compression algorithms, or simply love experimenting with unconventional ideas, I would love to see what you can bring to this project. Perhaps someone with powerful GPUs, better search strategies, or expertise in machine learning can take the exploration further than I could.

Even a rigorous mathematical argument demonstrating why one of our hypotheses cannot work would be a valuable scientific contribution.

I am looking forward to seeing where our collective curiosity takes us.

---

## Continuing the Mathematical Adventure

After the first ten phases, I was still curious! This time, I decided to explore a few different directions. Could we discover mathematical laws directly from digital data? Would larger files reveal structures that remain hidden in smaller ones? Could number theory help us describe sequences that appear random?

Over the next five phases, I explored these questions using ideas from algebra, 2-adic numbers, and nonlinear mathematical relationships. One particularly interesting direction was inspired by the work of [Hamid Naderi Yeganeh](https://doi.org/10.1080/10724117.2024.2368373), an Iranian mathematical artist. Seeing how complex images could be created through networks of mathematical functions made me wonder whether we could reverse the process: start with an existing image and discover a mathematical description of it.

Some of the experiments led to interesting observations. For example, 2-adic rational reconstruction revealed a structure in part of an executable file that could subsequently be expressed using a simpler mathematical rule. Some image experiments also outperformed individual conventional baselines. However, after accounting for the full description costs and comparing against matched controls, I still haven't found the meaningful, repeatable compression improvement I'm looking for.

I find these results interesting in their own right. We now understand the problem and its limitations a little better than we did at the beginning. Perhaps searching through more formulas isn't the answer. Perhaps we need to look at the problem from an entirely different perspective.

The reports, experimental code, benchmark results, and scientific references from these five phases are now available in the repository. I hope anyone curious about these ideas can explore them, challenge them, and continue from where we've arrived.

---

## What Is SXZ?

SXZ is an experimental research framework investigating mathematical and algorithmic descriptions of digital information for lossless data compression.

Its objective is to discover shorter descriptions from which the original information can be regenerated exactly, without losing a single bit.

SXZ is not a production-ready compression utility, nor is it a proven replacement for ZIP, Zstandard, Brotli, or LZMA. It is a collection of experimental engines, mathematical tools, algorithms, benchmarks, and research findings.

The central research question is:

**Can mathematical and generative representations describe digital information more economically than existing compression methods?**

## Explore the Repository

- [Research overview](research/overview.md) · [Timeline](research/timeline.md) · [Mathematical foundations](research/mathematical-foundations.md)
- [Consolidated findings](research/findings.md) · [Errata](research/errata.md) · [Related work](research/related-work.md) · [Bibliography](research/references.bib)
- [Experimental code](lab/README.md) · [Benchmark results](results/README.md) · [Reproduction guide](docs/reproduction.md)
- [Datasets and availability](datasets/README.md) · [Limitations](research/limitations.md) · [Open questions](research/open-questions.md)

## Research Journey

| Phase | Research focus | Main finding | Report and code |
|---|---|---|---|
| 01 — SXZ1 | Mathematical pattern encoding | Compact descriptions of planted mathematical sequences. | [Report](research/phases/01-sxz1.md) · [Code](lab/zip-protocol/) |
| 02 — SXZ2 | Streaming and native optimization | Working streaming prototype; no independent mathematical advantage established on general files. | [Report](research/phases/02-sxz2.md) · [Code](lab/zip-protocol/) |
| 03 — Detection audit | Search budgets and detection accuracy | Search limits miss planted patterns; local savings need whole-file controls. | [Report](research/phases/03-audit.md) · [Code](lab/zip-protocol/experiments/audit/) |
| 04 — SXZ3 | Extended models and residual coding | Strong synthetic results; no consistent real-file gain. | [Report](research/phases/04-sxz3.md) · [Code](lab/zip-protocol/experiments/sxz3/) |
| 05 — SXZ4 | Mathematical spans and reversible transforms | Compact synthetic recurrences; promising ECG transforms. | [Report](research/phases/05-sxz4.md) · [Code](lab/zip-protocol/experiments/sxz4/) |
| 06 — Validation | Real-data validation and ablation | ECG gains attributed chiefly to ordinary transforms; no general advantage. | [Report](research/phases/06-validation.md) · [Code](lab/zip-protocol/experiments/sxz4/) |
| 07 — SXZ-NEXT | Algebraic inference, program synthesis, native scanning | Faster targeted detection; no repeatable new real-file gain. | [Report](research/phases/07-next.md) · [Code](lab/sxz-next-research/) |
| 08 — Structural relations | Relationships between non-adjacent structures | Metadata and baseline competition limited gains. | [Report](research/phases/08-relationships.md) · [Code](lab/sxz-structural-relations/) |
| 09 — MSMC | Mathematical sequence mosaics | High raw match coverage; negligible independent savings. | [Report](research/phases/09-msmc.md) · [Code](lab/sxz-mathematical-mosaic/) |
| 10 — ASMC | Adaptive pseudorandom generators | Shared-seed synthetic gains; apparent real wins did not survive controls. | [Report](research/phases/10-asmc.md) · [Code](lab/sxz-adaptive-stochastic-mosaic/) |
| 11 — CGMC | Context-conditioned generators and decoder audit | No real file passed the predefined economic threshold. | [Report](research/phases/11-cgmc.md) · [Code](lab/sxz-cgmc/) |
| 12 — AMRD | Algebraic inference and cross-plane transforms | No nontrivial polynomial or affine spans in the tested real regions. | [Report](research/phases/12-amrd.md) · [Code](lab/sxz-amrd/) |
| 13 — Scaling | File size and description cost | Up to 100 MiB; rare affine hits, none cheaper than zstd-9 on the same span. | [Report](research/phases/13-scaling.md) · [Code](lab/sxz-scaling/) |
| 14 — Number theory | 2-adic rationals, coordinate functions, Boolean algebra | 12 real 2-adic spans, simplified to 16-bit progressions with carry; no archive gain. | [Report](research/phases/14-number-theory.md) · [Code](lab/sxz-2adic/) |
| 15 — Image math | Pixel functions, adaptive regions and compositional networks | Adaptive partition gains; isolated 9-byte crop win, no complete-image network win. | [Report](research/phases/15-image-math.md) · [Code](lab/sxz-image-math/) |

## Selected Experimental Findings

| Experiment | Measured result and interpretation |
|---|---|
| Synthetic second-order recurrence ([Phase 05](research/phases/05-sxz4.md)) | 256 KiB regenerated from an 84-byte description; a deliberately constructed input. |
| Real ECG ([Phase 06](research/phases/06-validation.md)) | Held-out sample: 116,004 → 83,791 B versus XZ (27.8% smaller); attributed to the ordinary shuffle/delta transform, not mathematical records. |
| Native scanning ([Phase 07](research/phases/07-next.md)) | 100 MB scanned in 0.68 s for one specific recurrence family; not a full general-model scan. |
| Mathematical mosaics ([Phase 09](research/phases/09-msmc.md)) | 74.44% average raw coverage on the five-file development panel; no comparable net compression gain. |
| Adaptive generators ([Phase 10](research/phases/10-asmc.md)) | Shared-seed synthetic mosaic: 2,048 → 1,002 B; real-file apparent gains did not survive the controls. |
| CGMC and AMRD ([11](research/phases/11-cgmc.md), [12](research/phases/12-amrd.md)) | 0/13 real held-out files passed the CGMC gate; no nontrivial polynomial/affine spans in AMRD's real panel. |
| Scaling ([Phase 13](research/phases/13-scaling.md)) | At 100 MiB, genuine affine coverage of the mixed archive was 13,692 B (0.013%); hybrid sizes were estimates and none improved on zstd-9. |
| 2-adic reconstruction ([Phase 14](research/phases/14-number-theory.md)) | Twelve selected real spans: 524 B of packed spans described in 229 B; a simpler arithmetic description was later found. No archive-level gain. |
| Image math ([Phase 15](research/phases/15-image-math.md)) | Adaptive logo: 3,529 B versus PNG's 4,157 B, also achieved by the non-geometric control. Network: isolated 9 B saving (0.0104%) on a gull crop; no complete-image win. Pixel-level only. |

These are results from different experiments, not a single comparative benchmark. Coverage is not compression savings; local savings are not whole-file savings. The linked reports document costs, settings, controls and limitations. See [selected figures](figures/README.md) and [consolidated findings](research/findings.md).

## Current Research Status

After fifteen phases, mathematical descriptions have proved useful when a recoverable law is present, and ordinary reversible transforms have sometimes improved compression. I have not yet established a meaningful, repeatable, independent mathematical compression gain on general real-world files. Every generator, parameter, address, residual and reconstruction cost matters. SXZ remains an open experimental project, not a product claim or a proposed way around the fundamental limits of lossless compression.

## Getting Started

Start with any phase in the table above, or follow the [reproduction guide](docs/reproduction.md) for setup, tests and benchmark commands. The [dataset guide](datasets/README.md) explains how to obtain available inputs; some historical inputs are not redistributable or publicly available, so exact reproduction is not guaranteed for every experiment. Historical measurements and executable research code are kept separate from new reproduction runs.

## Contributing

New mathematical hypotheses, alternative representations, number theory, machine learning, GPU-accelerated search, independent reproduction, new benchmarks and rigorous counterarguments are all welcome. Have an idea? [Open an issue](https://github.com/SinaPakmehr/SXZ/issues). Have a better approach? [Submit a pull request](https://github.com/SinaPakmehr/SXZ/pulls). See the [contribution guide](CONTRIBUTING.md), [authors](AUTHORS.md), [license](LICENSE) and [citation information](CITATION.cff). Disagreement and negative results are as valuable as successful implementations.

## The Bigger Picture

SXZ is not necessarily about making the current architecture work at all costs.

It is about exploring a question that I find genuinely fascinating: how much of the information we store can instead be described through mathematics, and how efficiently can we regenerate it?

Perhaps the most interesting solution has not been considered yet.

Let's explore it together.
