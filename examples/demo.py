"""Offline deterministic example; not a benchmark on general-purpose data."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lab/zip-protocol"))
from experiments.sxz4 import spans4
from experiments.sxz4.validate4 import order2

data = order2(64 * 1024)
direct, _ = spans4.pack(data, chain=(0,), spans_on=False)
model, stats = spans4.pack(data, chain=(0,), spans_on=True)
assert spans4.unpack(model) == data
assert len(model) < len(direct)
assert stats.spans
print(f"Exact planted recurrence: {len(data)} input bytes, {len(direct)} direct, {len(model)} modeled.")
