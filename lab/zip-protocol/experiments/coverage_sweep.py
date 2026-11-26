"""Coverage sweep: how much of a file is exactly describable by a formula?

For each sample and each block granularity we run the same model bank the
container uses, block by block, and report the fraction of bytes that a
verified formula reproduces exactly.  This separates "is there structure?"
from "does the container win?".

Run from the repository root:

    python experiments/coverage_sweep.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sinuxz.container import Packer  # noqa: E402
from sinuxz.samples import build_samples  # noqa: E402
from sinuxz.transforms import BY_ID  # noqa: E402

BLOCKS = (16, 32, 64, 128, 256, 512, 1024)
SAMPLES = (
    "zeros_4k.bin",
    "pattern_4k.bin",
    "counter_4k.bin",
    "lfsr_4k.bin",
    "xorshift_4k.bin",
    "mixed_4k.bin",
    "text_1k.txt",
    "gradient_32x32.png",
    "random_1k.bin",
)


def sweep(data: bytes, block: int) -> tuple[float, dict[str, int]]:
    packer = Packer(max_window=block, min_formula_bytes=min(16, block), extend_bytes=0)
    covered = 0
    families: dict[str, int] = {}
    for pos in range(0, len(data), block):
        chunk = data[pos : pos + block]
        cand = packer.find_formula(chunk)
        if cand is None:
            continue
        covered += cand.cover_bytes
        key = f"{cand.model.name}/{BY_ID[cand.transform_id].name}"
        families[key] = families.get(key, 0) + 1
    return (100.0 * covered / len(data) if data else 0.0), families


def main() -> None:
    samples_dir = os.path.join(ROOT, "samples")
    build_samples(samples_dir)
    results_dir = os.path.join(ROOT, "results")
    os.makedirs(results_dir, exist_ok=True)

    lines = [
        "# Formula coverage sweep",
        "",
        "Percentage of bytes reproduced *exactly* by at least one formula in the",
        "model bank, scanning aligned blocks. 100% means the whole file could be",
        "regenerated from parameters; 0% means no closed form was found.",
        "This measures describability only; the container additionally requires a",
        "formula segment to be smaller than deflate for the same span.",
        "",
        "| sample | " + " | ".join(f"{b} B" for b in BLOCKS) + " |",
        "|---|" + "---:|" * len(BLOCKS),
    ]
    details: list[str] = []
    for name in SAMPLES:
        path = os.path.join(samples_dir, name)
        with open(path, "rb") as fh:
            data = fh.read()
        cells = []
        per_sample: list[str] = []
        for block in BLOCKS:
            if block > len(data):
                cells.append("-")
                continue
            pct, fams = sweep(data, block)
            cells.append(f"{pct:.1f}")
            top = ", ".join(f"{k} x{v}" for k, v in sorted(fams.items(), key=lambda kv: -kv[1])[:3])
            per_sample.append(f"  - {block} B: {pct:.1f}%  ({top or 'none'})")
        line = f"| {name} | " + " | ".join(cells) + " |"
        lines.append(line)
        details.append(f"### {name}\n" + "\n".join(per_sample))
        print(line)

    out = os.path.join(results_dir, "coverage.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
        fh.write("\n\n## Family breakdown\n\n")
        fh.write("\n\n".join(details))
        fh.write("\n")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
