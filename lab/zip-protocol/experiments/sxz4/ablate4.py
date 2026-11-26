"""Controlled ablations of SXZ4 search decisions.

Four questions, each answered by measurement:

1. Does the transform screen (Deflate on a sample) hide a chain that the law
   engine would have used?
2. How much does the 12% expansion tolerance cost, and what does relaxing it buy?
3. How much work does the cheap gate save, and does it ever skip real structure?
4. Does replacing greedy first-fit with global weighted-interval selection
   improve the archive?
"""

from __future__ import annotations

import argparse
import ast
import bisect
import json
import lzma
import time
import zlib
from pathlib import Path

from experiments.sxz4 import spans4, transforms4

CORPUS4 = Path("datasets/sxz4-corpus")


def measure(data: bytes, chain, **kwargs):
    start = time.perf_counter()
    blob, stats = spans4.pack(data, chain=chain, **kwargs)
    elapsed = time.perf_counter() - start
    assert spans4.unpack(blob) == data
    return len(blob), stats, elapsed


# ---------------------------------------------------------------------------
# 1. Transform screen vs law exposure
# ---------------------------------------------------------------------------
def law_score(tdata: bytes) -> int:
    """Savings of the best single probe at offset zero (0 when nothing fits)."""
    span = spans4.try_at(tdata, 0, False)
    return int(span["savings"]) if span else 0


def suite_transforms(out: list[dict], files: list[tuple[str, Path]], sample: int = 65536) -> None:
    for name, path in files:
        full = path.read_bytes()
        data = full[:sample]
        rows = []
        for chain in transforms4.CHAINS:
            try:
                tdata, _ = transforms4.apply_chain(data, chain)
            except Exception:
                continue
            deflate = len(zlib.compress(tdata, 6))
            rows.append({"chain": list(chain), "deflate": deflate, "law": law_score(tdata)})
        by_deflate = sorted(rows, key=lambda r: r["deflate"])
        by_law = sorted(rows, key=lambda r: (-r["law"], r["deflate"]))
        candidates = [tuple(by_deflate[0]["chain"]), tuple(by_law[0]["chain"]),
                      tuple(max(rows, key=lambda r: r["law"])["chain"])]
        candidates = list(dict.fromkeys(candidates))
        results = {}
        for chain in candidates:
            size, stats, enc = measure(data, chain, max_probes=64)
            results[str(chain)] = {"bytes": size, "spans": stats.spans,
                                   "modelled": stats.modelled_bytes, "encode": enc}
        best_chain = min(results, key=lambda c: results[c]["bytes"])
        best_tuple = ast.literal_eval(best_chain)
        record = {
            "suite": "transforms", "name": name, "sample": sample,
            "deflate_top1": by_deflate[0]["chain"],
            "deflate_top1_bytes": results[str(tuple(by_deflate[0]["chain"]))]["bytes"],
            "law_top1": by_law[0]["chain"],
            "law_top1_bytes": results[str(tuple(by_law[0]["chain"]))]["bytes"],
            "best_tried": best_chain, "best_bytes": results[best_chain]["bytes"],
            "rank_of_best_by_deflate": next((i for i, r in enumerate(by_deflate, 1)
                                             if list(r["chain"]) == list(best_tuple)), 0),
            "rank_of_best_by_law": next((i for i, r in enumerate(by_law, 1)
                                         if list(r["chain"]) == list(best_tuple)), 0),
            "results": results, "top10_by_deflate": by_deflate[:10],
        }
        out.append(record)
        print(f"transforms {name:<14} deflateTop1={by_deflate[0]['chain']} "
              f"({record['deflate_top1_bytes']}) best={best_chain} ({record['best_bytes']}) "
              f"rank_deflate={record['rank_of_best_by_deflate']}", flush=True)


# ---------------------------------------------------------------------------
# 2. Expansion tolerance
# ---------------------------------------------------------------------------
def suite_tolerance(out: list[dict]) -> None:
    manifest = {m["name"]: Path(m["path"]) for m in
                json.loads((CORPUS4 / "manifest.json").read_text(encoding="utf-8"))}
    files = [
        ("order2-u32", manifest["order2-u32"]),
        ("order2-noise3", manifest["order2-u32-noise3"]),
        ("ecg-train", manifest["ecg-train"]),
        ("eeg-train", manifest["eeg-train"]),
        ("composite-sum", manifest["composite-sum"]),
        ("piecewise", manifest["piecewise"]),
    ]
    for name, path in files:
        data = path.read_bytes()
        chain = transforms4.screen(data, sample=32768)[0][1]
        for tol in (0.0, 0.02, 0.12, 0.25, 0.50):
            best = None
            for option in dict.fromkeys([chain, (0,)]):
                size, stats, enc = measure(data, option, tolerance=tol, max_probes=600)
                if best is None or size < best[0]:
                    best = (size, stats, enc, option)
            size, stats, enc, used = best
            out.append({"suite": "tolerance", "name": name, "tolerance": tol,
                        "chain": list(used), "bytes": size, "spans": stats.spans,
                        "modelled": stats.modelled_bytes, "encode": enc,
                        "modes": stats.modes})
            print(f"tolerance {name:<16} tol={tol:<5} bytes={size:>8} spans={stats.spans:<3} "
                  f"modelled={stats.modelled_bytes:>7} enc={enc:5.2f}s", flush=True)


# ---------------------------------------------------------------------------
# 3. Cheap gate
# ---------------------------------------------------------------------------
def suite_gate(out: list[dict]) -> None:
    files = [
        ("text-train", CORPUS4 / "text-train.bin"),
        ("weights-train", CORPUS4 / "weights-train.bin"),
        ("eeg-train", CORPUS4 / "eeg-train.bin"),
        ("jpeg-slice", CORPUS4 / "jpeg-slice.bin"),
        ("ecg-train", CORPUS4 / "ecg-train.bin"),
        ("order2-u32", CORPUS4 / "order2-u32.bin"),
        ("csv-numeric", CORPUS4 / "csv-numeric.bin"),
    ]
    for name, path in files:
        data = path.read_bytes()
        chain = transforms4.screen(data, sample=32768)[0][1]
        row = {"suite": "gate", "name": name, "chain": list(chain)}
        for label, gate in (("on", True), ("off", False)):
            best = None
            for option in dict.fromkeys([chain, (0,)]):
                size, stats, enc = measure(data, option, gate=gate, max_probes=300,
                                           time_budget=120.0)
                if best is None or size < best[0]:
                    best = (size, stats, enc, option)
            size, stats, enc, used = best
            row[label] = {"bytes": size, "encode": enc, "spans": stats.spans,
                          "modelled": stats.modelled_bytes, "models": stats.models,
                          "probes": stats.probes, "chain": list(used)}
            print(f"gate {name:<14} gate={label:<3} bytes={size:>8} spans={stats.spans:<3} "
                  f"modelled={stats.modelled_bytes:>7} enc={enc:6.2f}s", flush=True)
        out.append(row)


# ---------------------------------------------------------------------------
# 4. Greedy first-fit vs global weighted interval selection
# ---------------------------------------------------------------------------
def collect_candidates(tdata: bytes, step: int = 256) -> list[dict]:
    found = {}
    pos = 0
    while pos + spans4.MIN_SPAN <= len(tdata):
        span = spans4.try_at(tdata, pos, False)
        if span is not None:
            key = (span["start"], span["length"])
            if key not in found or span["savings"] > found[key]["savings"]:
                found[key] = span
        pos += step
    return list(found.values())


def select_global(candidates: list[dict]) -> list[dict]:
    """Maximum total savings with non-overlapping spans (weighted interval DP)."""
    items = sorted(candidates, key=lambda s: (s["start"] + s["length"], s["start"]))
    if not items:
        return []
    ends = [s["start"] + s["length"] for s in items]
    dp = [0] * (len(items) + 1)
    take = [False] * (len(items) + 1)
    for i, span in enumerate(items, 1):
        j = bisect.bisect_right(ends, span["start"], 0, i - 1)
        with_span = span["savings"] + dp[j]
        if with_span > dp[i - 1]:
            dp[i] = with_span
            take[i] = True
        else:
            dp[i] = dp[i - 1]
    chosen = []
    i = len(items)
    while i > 0:
        if take[i]:
            chosen.append(items[i - 1])
            i = bisect.bisect_right(ends, items[i - 1]["start"], 0, i - 1)
        else:
            i -= 1
    return list(reversed(chosen))


def suite_global(out: list[dict]) -> None:
    rng_data = __import__("random").Random(31).randbytes(32768)
    law = __import__("experiments.sxz4.validate4", fromlist=["order2"]).order2(32768)
    cases = {
        "piecewise-64k": (CORPUS4 / "piecewise.bin").read_bytes()[:65536],
        "two-laws-64k": law[:24576] + rng_data[:8192] + law[24576:32768] + rng_data[:8192],
        "cross-64k": (CORPUS4 / "cross-3x-u16.bin").read_bytes()[:65536],
    }
    for name, data in cases.items():
        tdata, metas = transforms4.apply_chain(data, (0,))
        chain_blob = transforms4.encode_chain((0,), metas)
        start = time.perf_counter()
        greedy, gstats = spans4.find_spans(tdata, False, max_probes=400)
        greedy_time = time.perf_counter() - start
        start = time.perf_counter()
        candidates = collect_candidates(tdata)
        collect_time = time.perf_counter() - start
        chosen = select_global(candidates)
        row = {"suite": "global", "name": name, "candidates": len(candidates),
               "greedy_spans": len(greedy), "greedy_savings": sum(s["savings"] for s in greedy),
               "global_spans": len(chosen), "global_savings": sum(s["savings"] for s in chosen),
               "collect_time": collect_time, "greedy_time": greedy_time}
        for label, spans in (("greedy", greedy), ("global", chosen)):
            blob = spans4.build_container(data, (0,), tdata, chain_blob, spans,
                                          spans4.BACKEND_DEFLATE)
            assert spans4.unpack(blob) == data
            row[label + "_bytes"] = len(blob)
        out.append(row)
        print(f"global {name:<14} greedy={row['greedy_bytes']:>7} ({len(greedy)} spans) "
              f"global={row['global_bytes']:>7} ({len(chosen)} spans) "
              f"cands={len(candidates)}", flush=True)


SUITES = {"transforms": suite_transforms, "tolerance": suite_tolerance,
          "gate": suite_gate, "global": suite_global}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", choices=sorted(SUITES))
    parser.add_argument("--save", type=Path, default=Path("results/sxz4_ablate.json"))
    args = parser.parse_args()
    rows = json.loads(args.save.read_text(encoding="utf-8")) if args.save.exists() else []
    rows = [r for r in rows if r.get("suite") != args.suite]
    if args.suite == "transforms":
        files = [("order2-u32", CORPUS4 / "order2-u32.bin"),
                 ("cross-3x-u16", CORPUS4 / "cross-3x-u16.bin"),
                 ("ecg-train", CORPUS4 / "ecg-train.bin"),
                 ("csv-numeric", CORPUS4 / "csv-numeric.bin"),
                 ("affine-u24be", CORPUS4 / "affine-u24be.bin"),
                 ("random-walk-f32", CORPUS4 / "random-walk-f32.bin")]
        suite_transforms(rows, files)
    else:
        SUITES[args.suite](rows)
    args.save.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print("saved", args.save, "rows", len(rows))


if __name__ == "__main__":
    main()
