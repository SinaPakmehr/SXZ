# Plain ZIP baseline for real Windows folders

Deflate level 1, bytes counted in memory; no archive is kept.
ZIP bytes include its own headers and directory entries. Times only encode;
they do not read back or verify the archive.

| Folder | Files | ZIP bytes | Encode seconds |
|---|---:|---:|---:|
| desktop | 405 | 2001724778 | 114.47 |
| music-lessons | 446 | 3600120401 | 252.18 |
