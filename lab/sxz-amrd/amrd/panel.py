"""Fixed Episode 1 real-file panel.

Paths are project-relative.  The panel intentionally reuses existing SXZ
datasets; no new third-party data is downloaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import PROJECT_ROOT, SAMPLE_LIMIT


@dataclass(frozen=True)
class PanelFile:
    name: str
    category: str
    path: str
    source: str

    @property
    def full_path(self) -> Path:
        return PROJECT_ROOT / self.path


PANEL = (
    PanelFile(
        "alice29.txt",
        "plain text",
        "data/06-sxz5-data/alice29.txt",
        "Canterbury corpus",
    ),
    PanelFile(
        "bbc.rss.xml",
        "JSON/XML",
        "data/06-sxz5-data/raw/bbc.rss.xml",
        "public RSS sample",
    ),
    PanelFile(
        "7zr.exe",
        "executable",
        "data/03-audit-assets/7zr.exe",
        "7-Zip standalone executable",
    ),
    PanelFile(
        "bert.pdf",
        "PDF",
        "data/06-sxz5-data/raw/bert.pdf",
        "public PDF sample",
    ),
    PanelFile(
        "transparency.bmp",
        "BMP",
        "data/06-sxz5-data/corpus/transparency.bmp",
        "public BMP sample",
    ),
    PanelFile(
        "ecg-train.bin",
        "ECG",
        "data/05-sxz4-corpus/ecg-train.bin",
        "MIT-BIH record 100, 20% slice (SXZ4 corpus)",
    ),
    PanelFile(
        "banana.jpg",
        "JPEG/PNG",
        "data/06-sxz5-data/raw/banana.jpg",
        "public JPEG sample",
    ),
    PanelFile(
        "docx-shapes.docx",
        "ZIP/DOCX",
        "data/06-sxz5-data/raw/docx-shapes.docx",
        "public DOCX sample",
    ),
)


def load_sample(item: PanelFile) -> tuple[bytes, bool, int]:
    raw = item.full_path.read_bytes()
    original = len(raw)
    if original > SAMPLE_LIMIT:
        return raw[:SAMPLE_LIMIT], False, original
    return raw, True, original
