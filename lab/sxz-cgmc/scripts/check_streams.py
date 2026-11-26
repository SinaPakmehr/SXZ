"""Parity tests between the vectorised analysis path and scalar decoder path."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cgmc.context import ctx_hash, ctx_hash_batch, lzp_offsets
from cgmc.streams import LZP_KS, STREAM_SPECS, gen_batch, gen_scalar


def main() -> None:
    rng = np.random.default_rng(20261126)
    data = np.concatenate([
        rng.integers(0, 256, 6000, dtype=np.uint8),
        np.zeros(200, dtype=np.uint8),
        np.tile(np.frombuffer(b"the quick brown fox ", dtype=np.uint8), 40),
    ])
    raw = data.tobytes()
    positions = np.array(sorted(set(rng.integers(20, len(data) - 300, 97).tolist())), dtype=np.int64)
    offs = lzp_offsets(data, positions)

    hb = ctx_hash_batch(data, positions)
    for i, p in enumerate(positions.tolist()):
        assert int(hb[i]) == ctx_hash(raw, p), (i, p)

    checked = 0
    for sid, (name, family, variant, param) in enumerate(STREAM_SPECS):
        n = 256
        cand, valid = gen_batch(sid, data, positions, n, offs.get(param) if family == "lzp" else None)
        for i, p in enumerate(positions.tolist()):
            off = int(offs[param][i]) if family == "lzp" else None
            got = gen_scalar(sid, raw[:p], p, n, off)
            if family == "lzp" and off < 0:
                assert len(got) == 0, (name, p)
                continue
            exp = cand[i, : len(got)].tobytes()
            assert got == exp, (name, p, got[:8], exp[:8], len(got), len(exp))
            checked += 1
    print("ctx hash parity ok; stream parity ok;", checked, "scalar/candidate comparisons")


if __name__ == "__main__":
    main()
