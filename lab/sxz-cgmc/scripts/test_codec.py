"""Correctness, determinism and malformed-input tests for the CGMC codec."""
from __future__ import annotations

import hashlib
import json
import random
import struct
import sys
import time
from pathlib import Path

import numpy as np
import zstandard as zstd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cgmc.codec import (CONFIGS, HEADER, LIT, MAGIC, REF, VERSION, build_container, compress,
                        decode_container, plan_dp, varint)
from cgmc.scan import scan_file

OUT = ROOT / "results" / "tests.json"


def craft(payload: bytes, meta: bytes, cfg: str = "allmixed24", mode: int = 0,
          stride: int = 8, orig: int = 0, ntok: int = 0) -> bytes:
    pc = compress(payload)
    mc = compress(meta)
    cfg_id = sorted(CONFIGS).index(cfg) if cfg in CONFIGS else 255
    return HEADER.pack(MAGIC, VERSION, cfg_id, mode, stride, orig, ntok,
                       len(payload), len(meta), len(pc), len(mc)) + pc + mc


def outcome(fn) -> str:
    try:
        fn()
        return "accepted"
    except ValueError:
        return "valueerror"
    except Exception as e:  # noqa: BLE001
        return type(e).__name__


def main() -> None:
    source_map = ROOT / "data" / "sources.local.json"
    if source_map.exists():
        sources = json.loads(source_map.read_text(encoding="utf8"))
        data = Path(sources["alice29.txt"]).read_bytes()[:20000]
    else:
        # Dependency-light correctness fixture; not a research-panel result.
        rng = random.Random(20261126)
        data = bytes(rng.randrange(256) for _ in range(20000))
    arr = np.frombuffer(data, dtype=np.uint8)
    scan = scan_file(arr)
    plan = plan_dp(scan.best_len["allmixed24"], scan.best_sid["allmixed24"], scan.positions, len(data))
    digest = hashlib.sha256(data).hexdigest()
    results = {"roundtrip": [], "determinism": True, "mutations": {}, "crafted": {}}

    for mode in ("gen", "ctrl", "lzref"):
        blob = build_container(data, plan, "allmixed24", mode, version=2)
        out, st = decode_container(blob, max_output=len(data))
        results["roundtrip"].append({
            "mode": mode, "archive": len(blob), "verified": hashlib.sha256(out).hexdigest() == digest,
            "decode_s": st.sec, "tokens": st.tokens,
        })
        blob2 = build_container(data, plan, "allmixed24", mode, version=2)
        results["determinism"] &= blob == blob2

    gen = build_container(data, plan, "allmixed24", "gen")
    rng = random.Random(11)
    counts = {"accepted": 0, "valueerror": 0, "other": 0}
    wrong = 0
    for _ in range(200):
        b = bytearray(gen)
        i = rng.randrange(len(b))
        b[i] ^= 1 << rng.randrange(8)
        try:
            out, _ = decode_container(bytes(b), max_output=len(data))
            counts["accepted"] += 1
            if hashlib.sha256(out).hexdigest() != digest:
                wrong += 1
        except ValueError:
            counts["valueerror"] += 1
        except Exception:
            counts["other"] += 1
    for _ in range(50):
        b = gen[: rng.randrange(len(gen))]
        try:
            decode_container(b, max_output=len(data))
            counts["accepted"] += 1
        except ValueError:
            counts["valueerror"] += 1
        except Exception:
            counts["other"] += 1
    for _ in range(20):
        b = gen + bytes(rng.randrange(256) for _ in range(16))
        try:
            decode_container(b, max_output=len(data))
            counts["accepted"] += 1
        except ValueError:
            counts["valueerror"] += 1
        except Exception:
            counts["other"] += 1
    results["mutations"] = {**counts, "accepted_but_wrong": wrong, "trials": 270}

    crafted = {
        "bad_config": (craft(b"", b"", cfg="nope"), len(data)),
        "unknown_tag": (craft(b"", bytes([0xFC]), ntok=1), len(data)),
        "ref_zero_offset": (craft(b"", bytes([REF]) + varint(0) + varint(8), ntok=1), len(data)),
        "gen_zero_length": (craft(b"", bytes([1]) + varint(0), ntok=1), len(data)),
        "too_many_tokens": (craft(b"", bytes([LIT]) + varint(0), ntok=5), len(data)),
        "trailing_meta": (craft(b"", bytes([LIT]) + varint(0) + b"X", ntok=1), len(data)),
        "huge_declared_output": (craft(b"", bytes([LIT]) + varint(0), ntok=1), 10),
        "payload_length_lie": (craft(b"ABC", bytes([LIT]) + varint(99), ntok=1), len(data)),
    }
    for name, (blob, cap) in crafted.items():
        results["crafted"][name] = outcome(lambda b=blob, c=cap: decode_container(b, max_output=c))

    OUT.write_text(json.dumps(results, indent=1) + "\n", encoding="utf8")
    print(json.dumps(results, indent=1))
    ok = (all(r["verified"] for r in results["roundtrip"]) and results["determinism"]
          and results["mutations"]["other"] == 0 and wrong == 0
          and all(v in ("valueerror",) for k, v in results["crafted"].items()
                  if k not in ("huge_declared_output",)))
    print("TESTS_OK" if ok else "TESTS_FAILED")


if __name__ == "__main__":
    main()
