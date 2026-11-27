# Data provenance

[Provenance](provenance.json) records historical corpus labels, sizes, digests
where retained, and public sources where known. Some labels denote derived
fixtures or slices, not exact upstream objects. A null source is not permission
to infer or substitute an input. Corpus makers carry exact synthetic recipes.

Phase 11-15 entries include the real panels, image samples, enwik8, model weights and the mixed desktop tar. Large model/binary corpora are private/local and are not downloadable. Offsets and scanned sizes are recorded in the phase reports and `lab/*/results/`; files are never redistributed. The Phase 15 images are third-party samples and require rights review before redistribution.

[Direct downloads](downloadable.json) are a limited, checksum-pinned subset;
obtain an exact version manually when an upstream mutable URL changes.
See [reproduction](../docs/reproduction.md). Do not redistribute source papers,
photos, audio, executables, models or corpus archives without checking their
rights. RFC documents have IETF Trust publication terms; PEP and Pillow inputs
are subject to upstream material-specific terms. No historical input file is
included, and the download command never runs retrieved content.

Phases 16-20 reuse the existing `book1`, `bbc.rss.xml`, `7zr.exe`,
`irs1040.pdf`, `hopper.bmp` and `ecg-holdout.bin` entries. Phase 20 additionally
samples named Windows executables/DLLs from the local system; their names,
build hashes, section offsets and measurements are retained, but the binaries
are not redistributed and are not a fixed downloadable corpus. Obtain any such
file from an installation you are entitled to use. See
[`lab/sxz-attribution`](../lab/sxz-attribution/) and the phase reports for exact
offsets and hashes.
