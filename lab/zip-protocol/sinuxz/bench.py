"""Benchmark harness: SINUXZ vs zlib / bz2 / lzma on the sample set."""

from __future__ import annotations

import bz2
import lzma
import os
import time
import zlib

from .container import HEADER, Packer, inspect, unpack


def baselines(data: bytes) -> dict[str, int]:
    return {
        "raw": len(data) + HEADER.size,
        "zlib-9": len(zlib.compress(data, 9)) + HEADER.size,
        "bz2-9": len(bz2.compress(data, 9)) + HEADER.size,
        "lzma-9": len(lzma.compress(data, preset=9)) + HEADER.size,
    }


def run_one(path: str, **packer_kwargs) -> dict:
    with open(path, "rb") as fh:
        data = fh.read()
    packer = Packer(**packer_kwargs)
    t0 = time.perf_counter()
    blob = packer.pack(data)
    elapsed = time.perf_counter() - t0
    out = unpack(blob)
    if out != data:
        raise ValueError(f"roundtrip failed for {path}")
    info = inspect(blob)
    row = {
        "name": os.path.basename(path),
        "size": len(data),
        "sinuxz": len(blob),
        "seconds": elapsed,
        "probes": packer.probe_count,
        "scan_seconds": packer.scan_seconds,
        "predict_seconds": packer.predict_seconds,
        "ratio": len(blob) / len(data) if data else 0.0,
        "formula_percent": info.get("formula_ratio_percent", 0.0),
        "residual_bytes": info["residual_bytes"],
        "codecs": info["codec_counts"],
        "segments": info["segments"],
        "baselines": baselines(data),
    }
    return row


def run_dir(samples_dir: str, **packer_kwargs) -> list[dict]:
    rows = []
    for name in sorted(os.listdir(samples_dir)):
        if name == "README.txt":
            continue
        path = os.path.join(samples_dir, name)
        if os.path.isfile(path):
            rows.append(run_one(path, **packer_kwargs))
    return rows


def format_markdown(rows: list[dict]) -> str:
    lines = [
        "| sample | bytes | sinuxz | ratio | formula % | residual input B | zlib | bz2 | lzma | pack s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        b = r["baselines"]
        lines.append(
            f"| {r['name']} | {r['size']} | {r['sinuxz']} | {r['ratio']:.3f} | "
            f"{r['formula_percent']:.1f} | {r['residual_bytes']} | "
            f"{b['zlib-9']} | {b['bz2-9']} | {b['lzma-9']} | {r['seconds']:.2f} |"
        )
    total_raw = sum(r["size"] for r in rows)
    total_packed = sum(r["sinuxz"] for r in rows)
    lines.append(
        f"| **total** | {total_raw} | {total_packed} | {total_packed / max(total_raw, 1):.3f} | "
        f"{sum(r['formula_percent'] * r['size'] for r in rows) / max(total_raw, 1):.1f} | "
        f"{sum(r['residual_bytes'] for r in rows)} | "
        f"{sum(r['baselines']['zlib-9'] for r in rows)} | "
        f"{sum(r['baselines']['bz2-9'] for r in rows)} | "
        f"{sum(r['baselines']['lzma-9'] for r in rows)} | "
        f"{sum(r['seconds'] for r in rows):.2f} |"
    )
    return "\n".join(lines)
