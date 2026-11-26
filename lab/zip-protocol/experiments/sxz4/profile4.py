"""Profile SXZ4 on one item before any rewrite decision."""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
from pathlib import Path

from experiments.sxz4 import spans4, transforms4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("datasets/sxz4-corpus"))
    parser.add_argument("--item", default="ecg-train")
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_profile.txt"))
    args = parser.parse_args()
    manifest = {m["name"]: m for m in json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))}
    data = Path(manifest[args.item]["path"]).read_bytes()
    ranked = transforms4.screen(data, sample=32768)[:1]
    chain = ranked[0][1] if ranked else (0,)
    profile = cProfile.Profile()
    profile.enable()
    blob, stats = spans4.pack(data, chain=chain)
    profile.disable()
    assert spans4.unpack(blob) == data
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(25)
    report = (f"item={args.item} chain={chain} bytes={len(data)} archive={len(blob)} "
              f"spans={stats.spans} modelled={stats.modelled_bytes}\n\n" + stream.getvalue())
    args.save.write_text(report, encoding="utf-8")
    print(report.splitlines()[0])
    print(report.splitlines()[2:12])


if __name__ == "__main__":
    main()
