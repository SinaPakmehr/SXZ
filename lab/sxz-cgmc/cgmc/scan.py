"""Vectorised candidate scan and per-configuration best-match bookkeeping."""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .context import lzp_offsets
from .streams import CONFIGS, MAXLEN, STREAM_SPECS, gen_batch, longest_prefix, stream_class


@dataclass
class ScanResult:
    positions: np.ndarray
    best_len: dict[str, np.ndarray]
    best_sid: dict[str, np.ndarray]
    streams: list[dict]
    seconds: float
    lzp_offsets: dict[int, np.ndarray]


def scan_file(data: np.ndarray, stride: int = 8, maxlen: int = MAXLEN,
              batch: int = 4096, configs: dict[str, list[int]] | None = None) -> ScanResult:
    configs = configs or CONFIGS
    n_total = len(data)
    positions = np.arange(0, max(0, n_total - 8) + 1, stride, dtype=np.int64)
    npos = positions.size
    best_len = {k: np.zeros(npos, dtype=np.int32) for k in configs}
    best_sid = {k: np.full(npos, -1, dtype=np.int32) for k in configs}
    start = time.perf_counter()
    all_offs = lzp_offsets(data, positions, stride=stride)
    padded = np.concatenate([data, np.zeros(maxlen, dtype=np.uint8)])
    arange = np.arange(maxlen, dtype=np.int64)
    ml_by_stream = np.zeros((len(STREAM_SPECS), npos), dtype=np.int32)

    for s in range(0, npos, batch):
        e = min(s + batch, npos)
        p = positions[s:e]
        target = padded[p[:, None] + arange[None, :]]
        cap_end = n_total - p
        for sid, (name, family, variant, param) in enumerate(STREAM_SPECS):
            off = all_offs[param][s:e] if family == "lzp" else None
            cand, valid = gen_batch(sid, data, p, maxlen, off)
            ml = longest_prefix(cand, target, np.minimum(valid, cap_end))
            ml_by_stream[sid, s:e] = ml
            for cfg, ids in configs.items():
                if sid in ids:
                    cur = best_len[cfg][s:e]
                    better = ml > cur
                    if better.any():
                        cur[better] = ml[better]
                        best_sid[cfg][s:e][better] = sid

    stream_rows: list[dict] = []
    for sid, (name, family, variant, param) in enumerate(STREAM_SPECS):
        ml = ml_by_stream[sid]
        hit = ml >= 8
        stream_rows.append({
            "id": sid,
            "name": name,
            "class": stream_class(sid),
            "probed": int(npos),
            "hits8": int(hit.sum()),
            "bytes8": int(ml[hit].sum()),
            "max": int(ml.max(initial=0)),
            "hits32": int((ml >= 32).sum()),
            "bytes32": int(ml[ml >= 32].sum()),
        })
    return ScanResult(positions, best_len, best_sid, stream_rows, time.perf_counter() - start, all_offs)
