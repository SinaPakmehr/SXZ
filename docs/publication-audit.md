# Publication audit summary

The local candidate is assembled from an explicit allowlist of research source,
protocols, English documentation and machine-readable results. It excludes
compiled binaries, caches, virtual environments, downloaded corpora, private
logs, historical Git metadata, the private Persian-language reports, and
unrelated neighboring projects.

The automated check looks for drive/UNC paths, home paths, local host/address
patterns, local identity markers, e-mail addresses, private-key/token patterns,
non-English text (with the owner-authorized Persian `README-fa.md` exception),
unexpected file types and broken local Markdown links. It reports categories and
file locations, never matched secret values.

Limitations: a scanner cannot prove negative absence. Binary, archive, model
and downloaded-file formats are excluded from the public tree. The owner should
repeat the audit after any post-publication edit. The approved public author
identity is recorded in `AUTHORS.md` and `CITATION.cff`; no source-machine path,
credential, private email or private handover material has been included here.
Phase 11-15 additions were scanned for the same patterns; unavailable source
corpora and image files remain outside the repository.
