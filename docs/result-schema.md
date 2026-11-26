# Raw result schema notes

The JSON is heterogeneous because phases evolved independently. Preserve it
as historical evidence; do not force it into one schema retroactively.

Common keys:

- `name` / `input.name`: fixture or experiment label. It is not a filesystem path.
- `input_bytes` / `file_bytes` / `bytes_in`: original byte count where labeled.
- `bytes`: archive byte count at the row's scope. Check surrounding `method`.
- `ratio`: archive bytes divided by the documented input bytes.
- `encode_s`, `decode_s`: seconds for the implementation and machine used.
- `decode_MBps` / `decode_MBs`: decimal MB/s, only when explicitly named.
- `exact`: byte-for-byte round trip passed.
- `coverage` / `raw_coverage`: exact match interval union, not final saving.
- `net_vs_direct` / `gain_*`: paired archive difference; sign convention is in
  the nearby report, normally positive means smaller.
- `model_bytes`, `meta_bytes`, `literals_bytes`, `header_bytes`: components of a
  final archive only where the schema explicitly defines them.
- `sources`, `seeds`, `trials`: finite search choices; rows are not independent
  files or independent statistical samples.

Fields such as `planted`, `root`, `span`, `chain`, `bank` and `mode` are
phase-specific. Read the phase protocol before aggregating. Machine paths and
environment descriptors were removed during publication; no scientific field
was regenerated to fill a missing input.
