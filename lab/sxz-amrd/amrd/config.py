"""Phase 12 AMRD Episode 1 settings and paths.

The phase is deliberately self-contained.  It reads shared SXZ datasets but
never writes outside ``phases/12-amrd``.
"""

from __future__ import annotations

from pathlib import Path

PHASE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PHASE_ROOT.parents[1]
RESULTS = PHASE_ROOT / "results"
DATA = PHASE_ROOT / "data"
SYNTHETIC = DATA / "synthetic"

# Experimental geometry.
WINDOWS = (64, 256)
HALF_STRIDE = True                 # stride = window // 2
SAMPLE_LIMIT = 256 * 1024          # bytes for files larger than this
MAX_SPAN_SYMBOLS = 1 << 20         # per word representation
MAX_SPAN_BITS = 1 << 21            # per bit plane
BM_MAX_ORDER = 64
AFFINE_BUDGET = 16                 # equation subsets, not coefficient search
PERIOD_MAX = 32
POLY_MAX_ORDER = 3

# Economics.
ZSTD_LEVEL = 19
LZMA_PRESET = 9
SIMPLE_MAX_PERIOD = 64

# Read-only reuse for parity checks.
OLD_LAB = PROJECT_ROOT / "phases" / "00-06-sinuxz"


def rel(path: Path) -> str:
    """Project-relative POSIX path for reports and JSON."""
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name
