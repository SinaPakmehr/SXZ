"""Compare the shipped engine with two diagnostic variants on the same inputs.

Both the shipped packer and the extend-then-choose variant are run with
``extend_bytes=4096`` so that the only difference is *which* candidate gets the
extension test, not how far the winner may reach.
"""

from __future__ import annotations

import argparse
import json
import zlib
from pathlib import Path

import sinuxz.container as container
from sinuxz.container import CODEC_FORMULA, HEADER, Packer, unpack
from experiments.audit import planted, variants

# Cases where an expressiveness or selection defect is suspected.
CASES = ["affine-u16le", "affine-u32le", "affine-u64le", "timestamp-u64us",
         "stereo-u16le", "composite-sum-u16le", "quadratic-u16le"]


def overlap(a_start: int, a_len: int, b_start: int, b_len: int) -> int:
    return max(0, min(a_start + a_len, b_start + b_len) - max(a_start, b_start))


def run(data: bytes, case_start: int, case_len: int, *, extend: bool,
        minimum: int = 16, budget=None, extend_bytes: int = 4096) -> dict:
    cls = variants.ExtendThenChoosePacker if extend else Packer
    packer = cls(max_window=128, min_formula_bytes=minimum, extend_bytes=extend_bytes,
                 level=6, experimental_models=True, scan_budget=budget)
    packer.trace = []
    blob = packer.pack(data)
    if unpack(blob) != data:
        raise RuntimeError("round trip mismatch")
    formula = covered = 0
    offset = 0
    for seg in packer.segments:
        if seg.codec == CODEC_FORMULA:
            formula += seg.size
            covered += overlap(offset, seg.size, case_start, case_len)
        offset += seg.size
    baseline = HEADER.size + len(zlib.compress(data, 6))
    return {"archive_bytes": len(blob), "net": len(blob) - baseline,
            "formula_bytes": formula, "covered": covered,
            "coverage": covered / case_len if case_len else 0.0,
            "accepted": sum(1 for e in packer.trace if e["accepted"]),
            "probes": packer.probe_count, "scan_seconds": packer.scan_seconds}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", type=Path, default=Path("results/audit_variants.json"))
    parser.add_argument("--assets", type=Path, default=Path("datasets/audit-assets"))
    args = parser.parse_args()
    rows = []
    cases = [c for c in planted.build() if c.name in CASES]

    def record(kind: str, name: str, expected, variant: str, result: dict) -> None:
        rows.append({"kind": kind, "name": name, "expected": expected,
                     "variant": variant, **result})
        print(f"{name:<24} {variant:<14} cover={result['coverage']:6.1%} "
              f"net={result['net']:+7d} accept={result['accepted']:>3} "
              f"scan={result['scan_seconds']:.1f}s", flush=True)

    for case in cases:
        record("planted", case.name, case.expected, "shipped",
               run(case.data, case.start, case.length, extend=False))
    for variant, le, extend in (("le-model", True, False), ("extend-choose", False, True),
                                ("le+extend", True, True)):
        if le:
            variants.install_le()
        try:
            for case in cases:
                record("planted", case.name, case.expected, variant,
                       run(case.data, case.start, case.length, extend=extend))
        finally:
            if le:
                variants.uninstall_le()

    for minimum in (32, 64):
        for case in cases:
            record("planted", case.name, case.expected, f"min-{minimum}",
                   run(case.data, case.start, case.length, extend=False, minimum=minimum))

    for name in ("audio-wav", "sensor-csv"):
        path = args.assets / name
        if not path.exists():
            continue
        with path.open("rb") as handle:
            handle.seek(2 << 20)
            data = handle.read(1 << 20)
        for variant, le, extend in (("shipped", False, False), ("le+extend", True, True)):
            if le:
                variants.install_le()
            try:
                record("real", name, None, variant,
                       run(data, 0, len(data), extend=extend, budget=64))
            finally:
                if le:
                    variants.uninstall_le()

    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} rows to {args.save}")


if __name__ == "__main__":
    main()
