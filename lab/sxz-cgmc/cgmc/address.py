"""Address-description accounting for history references.

Every scheme includes the length cost; only the offset description differs.
Predictions come from the decoder-visible LZP context table, never from future
bytes.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from .codec import varint_len


def zigzag(v: int) -> int:
    return 2 * v if v >= 0 else -2 * v - 1


def order0_entropy(values: list[int]) -> float:
    if not values:
        return 0.0
    c = Counter(values)
    n = len(values)
    return -sum((k / n) * np.log2(k / n) for k in c.values())


def report(refs: list[tuple[int, int, int]], lzp8: np.ndarray | None,
           stride: int = 8) -> dict:
    """refs: (start, offset, length) in token order."""
    if not refs:
        return {"refs": 0, "covered": 0}
    starts = [r[0] for r in refs]
    offs = [r[1] for r in refs]
    lens = [r[2] for r in refs]
    n = len(refs)
    len_bits = sum(8 * varint_len(x) for x in lens)
    fixed = n * 32 + len_bits
    var = sum(8 * (varint_len(o) + varint_len(l)) for o, l in zip(offs, lens))
    deltas = []
    prev = 0
    for o in offs:
        deltas.append(o - prev)
        prev = o
    delta_bits = sum(8 * (varint_len(zigzag(d)) + varint_len(l)) for d, l in zip(deltas, lens))
    h = order0_entropy(offs)
    entropy_bits = n * h + len_bits + 8  # 8 bits for the table size/framing
    pred_hits = 0
    pred_bits = 0
    pred_errors = []
    if lzp8 is not None:
        for p, o, l in zip(starts, offs, lens):
            pred = -1
            if p % stride == 0 and p // stride < len(lzp8):
                pred = int(lzp8[p // stride])
            if pred == o and o > 0:
                pred_hits += 1
                pred_bits += 1 + 8 * varint_len(l)
            else:
                pred_bits += 1 + 8 * (varint_len(o) + varint_len(l))
                if pred > 0:
                    pred_errors.append(o - pred)
    reuse = 0
    seen: set[int] = set()
    for o in offs:
        if o in seen:
            reuse += 1
        seen.add(o)
    return {
        "refs": n,
        "covered": int(sum(lens)),
        "mean_len": float(np.mean(lens)),
        "fixed32_bits": fixed,
        "varint_bits": var,
        "delta_varint_bits": delta_bits,
        "entropy_offset_bits": float(entropy_bits),
        "entropy_offset_order0": float(h),
        "lzp_hit_rate": pred_hits / n,
        "lzp_predicted_bits": pred_bits,
        "lzp_correction_mean": float(np.mean(np.abs(pred_errors))) if pred_errors else 0.0,
        "offset_reuse_rate": reuse / n,
        "mean_bits_varint": var / n,
        "mean_bits_fixed32": fixed / n,
        "mean_bits_delta": delta_bits / n,
        "mean_bits_entropy": entropy_bits / n,
        "mean_bits_lzp": pred_bits / n,
        "best_scheme": min(
            (("varint", var), ("fixed32", fixed), ("delta", delta_bits),
             ("entropy", entropy_bits), ("lzp", pred_bits)),
            key=lambda kv: kv[1])[0],
    }
