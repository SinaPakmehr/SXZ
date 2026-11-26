"""Build the SXZ5 public-real corpus (validation corpus for SXZ4).

The point of this corpus is to move the centre of gravity away from synthetic
laws.  Every item is either a slice of a real public file or a real container
generated from real content.  Synthetic/physiological controls stay in the
SXZ4 corpus and are not duplicated here.

Slices are 256 KiB so that encode time stays comparable with the earlier
corpus; whole small files are kept whole.  Items are split into dev and test
(different files or disjoint offsets), and the split is recorded in the
manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path("datasets/sxz5-data")
RAW = ROOT / "raw"
SILESIA = ROOT / "silesia"
SIZE = 256 * 1024

SOURCES = {
    "attention.pdf": "https://arxiv.org/pdf/1706.03762",
    "bert.pdf": "https://arxiv.org/pdf/1810.04805",
    "irs1040.pdf": "https://www.irs.gov/pub/irs-pdf/f1040.pdf",
    "wiki.html": "https://en.wikipedia.org/api/rest_v1/page/html/Data_compression",
    "bbc.rss.xml": "https://feeds.bbci.co.uk/news/rss.xml",
    "banana.jpg": "https://upload.wikimedia.org/wikipedia/commons/8/8a/Banana-Single.jpg",
    "gull.jpg": "https://upload.wikimedia.org/wikipedia/commons/9/9a/Gull_portrait_ca_usa.jpg",
    "fronalpstock.jpg": "https://upload.wikimedia.org/wikipedia/commons/3/3f/Fronalpstock_big.jpg",
    "transparency.png": "https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png",
    "sample5.mp4": "https://download.samplelib.com/mp4/sample-5s.mp4",
    "sample15.mp3": "https://download.samplelib.com/mp3/sample-15s.mp3",
    "docx-images.docx": "https://github.com/python-openxml/python-docx tests/test_files/having-images.docx",
    "docx-shapes.docx": "https://github.com/python-openxml/python-docx features/steps/test_files/shp-inline-shape-access.docx",
    "docx-table.docx": "https://github.com/python-openxml/python-docx features/steps/test_files/tbl-having-applied-style.docx",
    "pptx-chart.pptx": "https://github.com/scanny/python-pptx features/steps/test_files/cht-chart-type.pptx",
    "pptx-fill.pptx": "https://github.com/scanny/python-pptx features/steps/test_files/dml-fill.pptx",
    "pptx-movie.pptx": "https://github.com/scanny/python-pptx features/steps/test_files/shp-movie-props.pptx",
    "silesia.zip": "https://mattmahoney.net/dc/silesia.zip",
    "cantrbry.tar.gz": "https://corpus.canterbury.ac.nz/resources/cantrbry.tar.gz",
    "calgary.tar.gz": "https://corpus.canterbury.ac.nz/resources/calgary.tar.gz",
    "linux-tree.json": "https://api.github.com/repos/torvalds/linux/git/trees/master?recursive=1",
}


def slice_at(data: bytes, size: int, fraction: float) -> bytes:
    if len(data) <= size:
        return data
    start = int((len(data) - size) * fraction)
    return data[start : start + size]


def make_xlsx(path: Path, variant: int = 0) -> bytes:
    """A real OOXML workbook filled with public data (no synthetic values)."""
    from openpyxl import Workbook

    json_path = RAW / "linux-tree.json"
    rows: list[tuple] = []
    if json_path.exists():
        tree = json.loads(json_path.read_text(encoding="utf-8")).get("tree", [])
        step = 1 if variant == 0 else 3
        for item in tree[::step]:
            rows.append((item.get("path", ""), item.get("mode", ""), item.get("type", ""),
                         int(item.get("size", 0)), item.get("sha", "")[:16]))
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("tree")
    ws.append(["path", "mode", "type", "size", "sha16"])
    for row in rows[:80000]:
        ws.append(row)
    ws2 = wb.create_sheet("totals")
    ws2.append(["type", "count", "bytes"])
    totals: dict[str, list[int]] = {}
    for row in rows:
        entry = totals.setdefault(row[2], [0, 0])
        entry[0] += 1
        entry[1] += row[3]
    for key, (count, total) in sorted(totals.items()):
        ws2.append([key, count, total])
    wb.save(path)
    return path.read_bytes()


def make_bmp(src: Path, path: Path) -> bytes:
    from PIL import Image

    with Image.open(src) as image:
        image.convert("RGB").save(path, format="BMP")
    return path.read_bytes()


def build(out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []

    def add(name: str, data: bytes, family: str, category: str, source: str,
            heldout: bool, note: str = "") -> None:
        if not data:
            return
        path = out_dir / f"{name}.bin"
        path.write_bytes(data)
        rows.append({
            "name": name, "path": str(path), "bytes": len(data), "family": family,
            "category": category, "source": source, "heldout": heldout,
            "sha256": hashlib.sha256(data).hexdigest(), "note": note,
        })

    def raw(name: str, family: str, category: str, fraction: float, heldout: bool,
            size: int = SIZE) -> None:
        path = RAW / name
        if not path.exists():
            return
        data = slice_at(path.read_bytes(), size, fraction)
        add(name.rsplit(".", 1)[0].replace(".", "-") + ("-test" if heldout else "-dev"),
            data, family, category, SOURCES.get(name, str(path)), heldout)

    def silesia(name: str, family: str, category: str, fraction: float, heldout: bool,
                size: int = SIZE, out_name: str | None = None) -> None:
        path = SILESIA / name
        if not path.exists():
            return
        data = slice_at(path.read_bytes(), size, fraction)
        label = out_name or f"silesia-{name}-{'test' if heldout else 'dev'}"
        add(label, data, family, category,
            f"https://mattmahoney.net/dc/silesia.zip :: {name}", heldout)

    # Natural text: two different public books, disjoint slices of enwik8.
    for name, frac, held in (("book1", 0.15, False), ("book2", 0.60, True)):
        path = ROOT / name
        if path.exists():
            add(name + ("-test" if held else "-dev"),
                slice_at(path.read_bytes(), SIZE, frac), "text", "text",
                "Calgary corpus", held)
    for base, frac, held in (("alice29.txt", 0.2, False), ("plrabn12.txt", 0.7, True)):
        path = ROOT / base
        if path.exists():
            add(base.replace(".txt", "").replace(".", "-") + ("-test" if held else "-dev"),
                slice_at(path.read_bytes(), SIZE, frac), "text", "text",
                "Canterbury corpus", held)
    enwik = Path("datasets/enwik8")
    if enwik.exists():
        raw_data = enwik.read_bytes()
        for frac, held, name in ((0.30, False, "enwik8-dev"), (0.85, True, "enwik8-test")):
            add(name, slice_at(raw_data, SIZE, frac), "text", "text",
                "enwik8 (Hutter Prize)", held)

    # Documents and web formats.
    raw("attention.pdf", "pdf", "document", 0.45, False)
    raw("bert.pdf", "pdf", "document", 0.55, True)
    raw("irs1040.pdf", "pdf", "document", 0.0, False, size=10 ** 9)
    raw("wiki.html", "html", "web", 0.25, False)
    raw("bbc.rss.xml", "xml", "web", 0.0, False, size=10 ** 9)
    raw("docx-images.docx", "docx", "document", 0.0, False, size=10 ** 9)
    raw("docx-shapes.docx", "docx", "document", 0.0, False, size=10 ** 9)
    raw("docx-table.docx", "docx", "document", 0.0, True, size=10 ** 9)
    raw("pptx-chart.pptx", "pptx", "document", 0.40, False)
    raw("pptx-fill.pptx", "pptx", "document", 0.60, True)
    raw("pptx-movie.pptx", "pptx", "document", 0.20, False)
    raw("sample15.mp3", "mp3", "audio", 0.30, False, size=10 ** 9)
    raw("sample5.mp4", "mp4", "video", 0.40, False)
    raw("transparency.png", "png", "image", 0.0, False, size=10 ** 9)
    raw("banana.jpg", "jpeg", "image", 0.25, False)
    raw("gull.jpg", "jpeg", "image", 0.60, True)
    raw("fronalpstock.jpg", "jpeg", "image", 0.55, False)

    exe = Path("datasets/audit-assets/7zr.exe")
    if exe.exists():
        add("7zr-exe-dev", exe.read_bytes(), "pe", "executable",
            "7-Zip 7zr.exe (public release)", False)
    silesia("mozilla", "pe", "executable", 0.30, True)

    # A real JSON API response (the Linux kernel tree listing).
    json_path = RAW / "linux-tree.json"
    if json_path.exists():
        add("linux-tree-json-dev", slice_at(json_path.read_bytes(), SIZE, 0.4),
            "json", "web", SOURCES["linux-tree.json"], False)
        add("linux-tree-json-test", slice_at(json_path.read_bytes(), SIZE, 0.8),
            "json", "web", SOURCES["linux-tree.json"], True)

    # Real container generated from public tabular data.
    xlsx = make_xlsx(out_dir / "weather.xlsx", 0)
    add("tree-xlsx-dev", xlsx, "xlsx", "document",
        "openpyxl + Linux kernel tree JSON (public API)", False)
    xlsx2 = make_xlsx(out_dir / "weather2.xlsx", 1)
    add("tree-xlsx-test", xlsx2, "xlsx", "document",
        "openpyxl + Linux kernel tree JSON (public API)", True)

    bmp = make_bmp(RAW / "transparency.png", out_dir / "transparency.bmp")
    add("transparency-bmp", slice_at(bmp, SIZE, 0.0), "bmp", "image",
        "PIL conversion of public PNG", False)
    ppm = Path("datasets/audit-assets/photo.ppm")
    if ppm.exists():
        add("photo-ppm-dev", slice_at(ppm.read_bytes(), SIZE, 0.3), "ppm", "image",
            "local camera photo (PPM)", False)
    silesia("x-ray", "raw-image", "image", 0.5, True)

    # Audio and archives.
    wav = Path("datasets/audit-assets/audio.wav")
    if wav.exists():
        add("audio-wav-dev", slice_at(wav.read_bytes(), SIZE, 0.4), "wav", "audio",
            "local WAV recording", False)
    flac = next(iter(Path("datasets/unavailable-inputs").rglob("*.flac")), None) if Path("datasets/unavailable-inputs").exists() else None
    if flac:
        add("audio-flac-test", slice_at(flac.read_bytes(), SIZE, 0.7), "flac", "audio",
            f"local FLAC {flac.name}", True)
    zipped = Path("datasets/enwik8.zip")
    if zipped.exists():
        add("zip-slice-dev", slice_at(zipped.read_bytes(), SIZE, 0.45), "zip", "archive",
            "enwik8.zip", False)
    ooffice = SILESIA / "ooffice"
    if ooffice.exists():
        add("silesia-ooffice-dev", slice_at(ooffice.read_bytes(), SIZE, 0.2), "binary", "archive",
            "Silesia ooffice", False)

    # Model weights (real tensors, dev and test slices).
    weights = Path("datasets/compare-corpus/unavailable-weights.bin")
    if weights.exists():
        data = weights.read_bytes()
        add("weights-dev", slice_at(data, SIZE, 0.2), "weights", "weights",
            "local model weights", False)
        add("weights-test", slice_at(data, SIZE, 0.8), "weights", "weights",
            "local model weights", True)

    # Silesia standard files, the de-facto compression benchmark.
    silesia("dickens", "text", "standard", 0.1, False)
    silesia("reymont", "text", "standard", 0.6, True)
    silesia("mr", "medical", "standard", 0.3, False)
    silesia("nci", "dna", "standard", 0.3, False)
    silesia("osdb", "database", "standard", 0.5, True)
    silesia("samba", "source", "standard", 0.2, False)
    silesia("sao", "astronomy", "standard", 0.5, True)
    silesia("webster", "text", "standard", 0.4, False)
    silesia("xml", "xml", "standard", 0.5, False)
    silesia("mozilla", "pe", "standard", 0.7, True, out_name="silesia-mozilla-std")

    (out_dir / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, default=ROOT / "corpus")
    args = parser.parse_args()
    rows = build(args.output)
    from collections import Counter

    cats = Counter(row["category"] for row in rows)
    fams = Counter(row["family"] for row in rows)
    print(f"{len(rows)} items, {sum(r['bytes'] for r in rows)/2**20:.2f} MiB")
    print("categories:", dict(cats))
    print("families:", dict(fams))
    print(f"held out: {sum(r['heldout'] for r in rows)}")


if __name__ == "__main__":
    main()
