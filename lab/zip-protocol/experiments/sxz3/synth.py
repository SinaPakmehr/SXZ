"""Bounded, deterministic program synthesis over 32-bit recurrences.

Grammar (depth is exactly two operations, one input: the previous word):

    y = op2(p2, op1(p1, x))

Operations are modular addition, xor, multiplication by an odd constant,
rotate left/right, ``x ^ (x >> k)`` and ``x + (x << k)``.  Constants are drawn
from a small fixed set plus values observed in the data's first differences.
The search is bounded by construction: no unbounded enumeration, no generated
code, and the program is stored as four small integers.
"""

from __future__ import annotations

import itertools
import time
from collections import Counter
from dataclasses import dataclass

M32 = 0xFFFFFFFF
OPS = ("add", "xor", "mul", "rotl", "rotr", "xorshr", "xorshl")
FIXED = (0, 1, 2, 3, 5, 7, 17, 255, 256, 0xFFFF, 0x5A5A, 0x1234)
ROTATIONS = (1, 2, 3, 4, 5, 7, 8, 11, 13, 16, 17, 24, 31)


def apply_op(op: str, param: int, value: int) -> int:
    if op == "add":
        return (value + param) & M32
    if op == "xor":
        return value ^ param
    if op == "mul":
        return (value * param) & M32
    if op == "rotl":
        return ((value << param) | (value >> (32 - param))) & M32
    if op == "rotr":
        return ((value >> param) | (value << (32 - param))) & M32
    if op == "xorshr":
        return (value ^ (value >> param)) & M32
    if op == "xorshl":
        return (value + ((value << param) & M32)) & M32
    raise ValueError(op)


@dataclass(frozen=True)
class Program:
    op1: str
    p1: int
    op2: str
    p2: int

    def step(self, value: int) -> int:
        return apply_op(self.op2, self.p2, apply_op(self.op1, self.p1, value))

    def describe(self) -> str:
        return f"{self.op2}({self.p2}, {self.op1}({self.p1}, x))"


def _params(op: str, words: list[int]) -> tuple[int, ...]:
    if op in ("add", "xor"):
        observed = Counter((words[i + 1] - words[i]) & M32
                           for i in range(min(64, len(words) - 1)))
        return tuple(dict.fromkeys(FIXED + tuple(v for v, _ in observed.most_common(4))))
    if op == "mul":
        return tuple(c for c in FIXED if c % 2 == 1)
    return ROTATIONS


def synthesize(words: list[int], verify: int = 64) -> tuple[Program | None, int, float]:
    """Return (program, matched_words, seconds) for the best depth-2 program."""
    if len(words) < verify + 2:
        return None, 0, 0.0
    sample = words[: verify + 1]
    best: tuple[int, Program | None] = (0, None)
    start = time.perf_counter()
    first = sample[0]
    for op1 in OPS:
        for p1 in _params(op1, words):
            stage1 = [apply_op(op1, p1, value) for value in sample]
            for op2 in OPS:
                for p2 in _params(op2, words):
                    matched = 0
                    for i in range(verify):
                        if apply_op(op2, p2, stage1[i]) != sample[i + 1]:
                            break
                        matched += 1
                    if matched > best[0]:
                        best = (matched, Program(op1, p1, op2, p2))
                        if matched == verify:
                            return best[1], matched, time.perf_counter() - start
    return best[1], best[0], time.perf_counter() - start


def generators() -> dict[str, bytes]:
    """Small, deliberately compositional sequences with known laws."""
    import struct

    def words(seed: int, step, count: int = 1024) -> bytes:
        value, out = seed, bytearray()
        for _ in range(count):
            out += struct.pack("<I", value)
            value = step(value)
        return bytes(out)

    return {
        "lcg": words(12345, lambda x: (1664525 * x + 1013904223) & M32),
        "xorrot": words(0x12345678, lambda x: ((((x ^ 0x00FF) << 5) | ((x ^ 0x00FF) >> 27)) & M32)),
        "xor-add": words(0x12345678, lambda x: ((x ^ 0x5A5A) + 7) & M32),
        "rot-add": words(0xDEADBEEF, lambda x: ((((x >> 5) | (x << 27)) + 3) & M32)),
        "mul-xor": words(0x0BADF00D, lambda x: (((x * 5) & M32) ^ 0x1234)),
        "xorshr-add": words(0xCAFEBABE, lambda x: ((x ^ (x >> 7)) + 1) & M32),
        "random": bytes(__import__("random").Random(5).randbytes(4096)),
    }


def main() -> None:
    for name, data in generators().items():
        words = [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data) - 4, 4)]
        program, matched, seconds = synthesize(words)
        print(f"{name:<12} matched={matched:3d}/64 program={program.describe() if program else '—'}"
              f"  {seconds:.2f}s")


if __name__ == "__main__":
    main()
