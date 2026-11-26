"""Fetch a single pinned public input; no archive extraction or execution."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def fetch(row):
    req = urllib.request.Request(row["url"], headers={"User-Agent": "Research-data verification"})
    with urllib.request.urlopen(req, timeout=35) as response:
        if not response.url.startswith("https://"):
            raise ValueError("unexpected transport")
        data = response.read(row["bytes"] + 1)
    if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise ValueError("Upstream bytes differ from the archived input; nothing written")
    out = ROOT / row["relative_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.read_bytes() != data:
        raise FileExistsError("Unrelated file at destination")
    out.write_bytes(data)
    print(f"Verified {row['id']} and saved {len(data):,} bytes.")

if __name__ == "__main__":
    rows = {r["id"]: r for r in json.loads((ROOT/"datasets/downloadable.json").read_text())}
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument("fixture", choices=sorted(rows))
    fetch(rows[arg.parse_args().fixture])
