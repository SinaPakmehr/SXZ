"""Targeted Phase 11 security/regression tests.

The original Appendix J entry ``huge_declared_output | accepted`` is preserved
and explained here: that test called ``craft(..., ntok=1)`` without setting
``orig``, so the header declared orig_len=0, not a huge output.  The corrected
test below declares a huge output and verifies rejection before any frame is
decompressed.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import zstandard as zstd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cgmc.codec import (CTRL, HEADER, HEADER3, LIT, MAGIC, MAGIC3, REF, VERSION, VERSION3,
                        build_container, compress, decode_container, archive_info, varint)
from cgmc.scan import scan_file
from cgmc.codec import plan_dp

OUT = ROOT / "results" / "audit-tests.json"


def frame(b: bytes) -> bytes:
    return compress(b)


def craft_v2(orig: int, ntok: int, payload: bytes, meta: bytes, *,
             config: str = "allmixed24", cfg_id: int | None = None, mode: int = 0,
             stride: int = 8, pc: bytes | None = None, mc: bytes | None = None) -> bytes:
    pc = frame(payload) if pc is None else pc
    mc = frame(meta) if mc is None else mc
    ids = sorted(__import__("cgmc.streams", fromlist=["CONFIGS"]).CONFIGS)
    cfg_id = ids.index(config) if cfg_id is None else cfg_id
    return HEADER.pack(MAGIC, VERSION, cfg_id, mode, stride, orig, ntok,
                       len(payload), len(meta), len(pc), len(mc)) + pc + mc


def craft_v3(orig: int, ntok: int, payload: bytes, meta: bytes, *,
             config: str = "allmixed24", cfg_id: int | None = None, mode: int = 0,
             stride: int = 8, selected: bytes = b"", digest: bytes | None = None,
             pc: bytes | None = None, mc: bytes | None = None,
             sc: bytes | None = None) -> bytes:
    pc = frame(payload) if pc is None else pc
    mc = frame(meta) if mc is None else mc
    scf = (frame(selected) if sc is None else sc) if mode == 3 else b""
    ids = sorted(__import__("cgmc.streams", fromlist=["CONFIGS"]).CONFIGS)
    cfg_id = ids.index(config) if cfg_id is None else cfg_id
    if digest is None:
        digest = hashlib.sha256(b"x" * orig).digest()
    return HEADER3.pack(MAGIC3, VERSION3, cfg_id, mode, stride, orig, ntok,
                        len(payload), len(meta), len(selected) if mode == 3 else 0,
                        len(pc), len(mc), len(scf), digest) + pc + mc + scf


def result(fn) -> dict:
    t = time.perf_counter()
    try:
        fn()
        return {"outcome": "accepted", "sec": time.perf_counter() - t}
    except ValueError as e:
        return {"outcome": "valueerror", "message": str(e), "sec": time.perf_counter() - t}
    except Exception as e:  # noqa: BLE001
        return {"outcome": type(e).__name__, "message": str(e)[:200],
                "sec": time.perf_counter() - t}


def main() -> None:
    # The original test's exact construction: craft(..., ntok=1) with default
    # orig=0.  It is accepted because it declares an empty output, not a huge one.
    original_blob = craft_v2(0, 1, b"", bytes([LIT]) + varint(0))
    hardened_original = result(lambda: decode_container(original_blob, max_output=10))
    historical = json.loads((ROOT / "audit" / "original-tests.json").read_text(encoding="utf8"))

    # Corrected huge-output test: reject before touching an intentionally
    # invalid payload frame.
    huge_blob = craft_v2(10**9, 1, b"", bytes([LIT]) + varint(0), pc=b"not-zstd")
    huge = result(lambda: decode_container(huge_blob, max_output=10))

    cases = {
        "original_construction_under_hardened_v2": hardened_original,
        "corrected_huge_declared_output": huge,
        "payload_longer_than_output": result(lambda: decode_container(
            craft_v2(1, 1, b"A" * 100, bytes([LIT]) + varint(100)), max_output=10)),
        "metadata_over_token_bound": result(lambda: decode_container(
            craft_v2(1, 1, b"A", bytes([LIT]) + varint(1) + b"Z" * 100), max_output=10)),
        "tokens_exceed_output": result(lambda: decode_container(
            craft_v2(1, 100, b"A", bytes([LIT]) + varint(1)), max_output=10)),
        "zero_length_literal": result(lambda: decode_container(
            craft_v2(1, 1, b"", bytes([LIT]) + varint(0)), max_output=10)),
        "zero_length_control": result(lambda: decode_container(
            craft_v2(1, 1, b"", bytes([CTRL]) + varint(0), mode=1), max_output=10)),
        "zero_length_generator": result(lambda: decode_container(
            craft_v2(1, 1, b"", bytes([1]) + varint(0)), max_output=10)),
        "reference_too_long": result(lambda: decode_container(
            craft_v2(1, 1, b"", bytes([REF]) + varint(1) + varint(1 << 20 + 1)), max_output=10)),
        "reference_offset_zero": result(lambda: decode_container(
            craft_v2(1, 1, b"", bytes([REF]) + varint(0) + varint(1)), max_output=10)),
        "truncated_frame": result(lambda: decode_container(
            craft_v2(10, 1, b"A", bytes([LIT]) + varint(1), pc=b"\x28\xb5\x2f\xfd"), max_output=10)),
        "trailing_bytes": result(lambda: decode_container(
            craft_v2(1, 1, b"A", bytes([LIT]) + varint(1)) + b"trailing", max_output=10)),
        "bad_config": result(lambda: decode_container(
            craft_v2(1, 1, b"A", bytes([LIT]) + varint(1), cfg_id=255), max_output=10)),
        "v3_good": result(lambda: decode_container(
            craft_v3(1, 1, b"A", bytes([LIT]) + varint(1),
                     digest=hashlib.sha256(b"A").digest()), max_output=10)),
        "v3_bad_checksum": result(lambda: decode_container(
            craft_v3(1, 1, b"A", bytes([LIT]) + varint(1),
                     digest=hashlib.sha256(b"B").digest()), max_output=10)),
        "v3_strict_requires_selected": result(lambda: decode_container(
            craft_v3(1, 1, b"", bytes([1]) + varint(1), mode=3, selected=b"",
                     digest=hashlib.sha256(b"A").digest()), max_output=10)),
        "v2_large_payload_frame_bomb": result(lambda: decode_container(
            craft_v2(1, 1, b"A", bytes([LIT]) + varint(1),
                     pc=frame(b"A" * 10000)), max_output=10)),
        "v3_large_payload_frame_bomb": result(lambda: decode_container(
            craft_v3(1, 1, b"A", bytes([LIT]) + varint(1),
                     pc=frame(b"A" * 10000), digest=hashlib.sha256(b"A").digest()),
            max_output=10)),
    }

    # A real strict archive: its literal frame must be byte-identical to gen.
    data = Path(ROOT / "data" / "slices" / "dickens-1m.bin").read_bytes()[:20000] \
        if (ROOT / "data" / "slices" / "dickens-1m.bin").exists() else b""
    if not data:
        data = b"the quick brown fox jumps over the lazy dog " * 500
    arr = np.frombuffer(data, dtype=np.uint8)
    scan = scan_file(arr)
    plan = plan_dp(scan.best_len["allmixed24"], scan.best_sid["allmixed24"], scan.positions, len(data))
    gen = build_container(data, plan, "allmixed24", "gen", version=3)
    strict = build_container(data, plan, "allmixed24", "strict", version=3)
    gi, si = archive_info(gen), archive_info(strict)
    hb = HEADER3.size
    gen_pc = gen[hb:hb + gi["payload_c"]]
    strict_pc = strict[hb:hb + si["payload_c"]]
    gen_mc = gen[hb + gi["payload_c"]:hb + gi["payload_c"] + gi["meta_c"]]
    strict_mc = strict[hb + si["payload_c"]:hb + si["payload_c"] + si["meta_c"]]
    strict_out, strict_stats = decode_container(strict, max_output=len(data))
    strict_record = {
        "gen_bytes": len(gen), "strict_bytes": len(strict),
        "literal_frame_identical": gen_pc == strict_pc,
        "meta_frame_identical": gen_mc == strict_mc,
        "selected_bytes": si["selected_len"],
        "strict_minus_gen": len(strict) - len(gen),
        "verified": strict_out == data,
        "checksum_ok": strict_stats.checksum_ok,
    }

    report = {
        "original_test_explanation": (
            "The original 'huge_declared_output' case called craft() with the default "
            "orig=0, so it declared an empty output and was accepted. It did not test a "
            "huge declared output. The historical original-tests.json outcome is "
            + str(historical.get("crafted", {}).get("huge_declared_output")) + "."),
        "historical_original_test": historical.get("crafted", {}).get("huge_declared_output"),
        "resource_gap_found": (
            "The v2 decoder bounded orig_len by max_output but did not bound payload_len, "
            "ntok or meta_len before decompression; a malicious header could request a "
            "multi-gigabyte payload frame even with a small output cap. v3 and the hardened "
            "v2 path now reject payload_len > orig_len, ntok > orig_len, meta_len > 11*ntok, "
            "and enforce absolute token/meta caps before decompression."),
        "cases": cases,
        "strict_container": strict_record,
        "versions": {"zstd": zstd.__version__, "numpy": np.__version__},
        "all_rejected": all(v["outcome"] == "valueerror" for k, v in cases.items()
                            if k not in ("v3_good",)),
        "v3_good_accepted": cases["v3_good"]["outcome"] == "accepted",
    }
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf8")
    for k, v in cases.items():
        print(f"{k:42s} {v['outcome']:10s} {v.get('message','')[:80]}")
    print("strict", json.dumps(strict_record, indent=1))
    print("wrote", OUT)


if __name__ == "__main__":
    main()
