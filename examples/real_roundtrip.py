"""Small real input round trip with a paired Deflate-only baseline."""
from pathlib import Path
import sys

from sinuxz import Packer, unpack

data = Path(sys.argv[1]).read_bytes()
direct = Packer(scan_budget=0).pack(data)
model = Packer(scan_budget=8).pack(data)
assert unpack(direct) == unpack(model) == data
print(f"{len(data):,} input bytes; {len(direct):,} direct; {len(model):,} with model search.")
