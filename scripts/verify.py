"""Local static publication checks. Findings print categories, never matched secrets."""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release-manifest.json"
CHECKS = {
    "absolute drive path": r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?!/)",
    "UNC path": r"\\\\[A-Za-z0-9_.-]+\\",
    "local home or system path": r"(?i)(?:^|[\"'` ])/(?:home|Users|tmp|private|mnt|var|etc)/",
    "local host or address": r"(?i)\blocalhost\b|\b(?:127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(?::\d+)?\b",
    "private credential": r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{24,}|AKIA[A-Z0-9]{16})\b",
    "local identity marker": r"(?i)\b(?:sina|pubblic|opencode)\b",
    "email": r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}",
    "untranslated text": "[\u0600-\u06ff]",
}
IGNORE = {".git", "__pycache__", ".venv", "target", "build", "dist", "corpus"}
AUTHORIZED_IDENTITY = {"AUTHORS.md", "CITATION.cff", "LICENSE", "pyproject.toml", "THIRD_PARTY_NOTICES.md"}
BILINGUAL_README = "README-fa.md"
SUFFIXES = {".py", ".rs", ".toml", ".md", ".json", ".jsonl", ".svg", ".csv", ".txt", ".yml", ".yaml", ".cff", ".bib", ".lock"}
files = []
issues = []
for p in sorted(ROOT.rglob("*")):
    rel = p.relative_to(ROOT)
    # Build outputs are never permitted in the release audit; CI may install normally.
    if "ci" in sys.argv and (any(x.endswith(".egg-info") for x in rel.parts) or set(rel.parts) & IGNORE):
        continue
    if rel.parts[0] == ".git":
        continue  # Git's own fresh metadata is not part of an export.
    if p.is_symlink():
        issues.append((rel, "symlink"))
    if not p.is_file() or p == MANIFEST:
        continue
    if p.suffix not in SUFFIXES and p.name not in ("LICENSE", ".gitignore", ".gitattributes"):
        issues.append((rel, "unexpected extension"))
        continue
    raw = p.read_bytes()
    try:
        s = raw.decode("utf-8")
    except UnicodeError:
        issues.append((rel, "not UTF-8 text"))
        continue
    if "\0" in s:
        issues.append((rel, "binary content"))
    for label, pattern in CHECKS.items():
        if p == Path(__file__).resolve() and label == "untranslated text":
            continue
        if rel.as_posix() == BILINGUAL_README and label == "untranslated text":
            continue  # owner-authorized Persian README
        if label == "local identity marker" and rel.as_posix() in AUTHORIZED_IDENTITY:
            continue  # owner-authorized public author identity
        for hit in re.finditer(pattern, s):
            if p == Path(__file__).resolve():
                continue
            # Rust syntax, numeric library identifiers, and historical paths
            # intentionally targeted by malformed-member tests are not PII.
            issues.append((rel, f"{label}, line {s.count(chr(10), 0, hit.start()) + 1}"))
            break
    if p.suffix == ".md":
        for dest in re.findall(r"\]\(([^ )]+)\)", s):
            target = dest.split("#")[0]
            if target and ":" not in target and not (p.parent / target).exists():
                issues.append((rel, "missing local link: " + target))
    files.append({"path": rel.as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
if issues:
    for i in issues[:80]:
        print(*i)
    raise SystemExit(1)
if "manifest" in sys.argv:
    MANIFEST.write_text(json.dumps({"excludes": ["release-manifest.json (self)"], "files": files}, indent=2)+"\n",encoding="utf-8")
print(f"Checked {len(files)} files; {sum(i['bytes'] for i in files):,} bytes.")
