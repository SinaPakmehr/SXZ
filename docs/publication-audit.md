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

The Phase 16-20 additions include only English syntheses, bounded source,
frozen protocols and compact JSON evidence. Windows EXE/DLL fixtures, the
private 7zr/ECG and other nonredistributable inputs, local absolute paths and
machine environment strings are excluded. Public copies of historical results
replace path roots with repository-relative or `SystemRoot/...` references;
scientific fields and fixture hashes are retained. The systematic Phase 20
audit is a value-set cost audit and is not presented as a new production codec.
