# `sxz-2adic` - Number Theory and Algebraic Discovery

Historical Phase 14 diagnostics: exact 2-adic lattice reconstruction, coordinate
functions and quadratic GF(2) relations.

```text
cd lab/sxz-2adic
python -B scripts/run_phase14.py
python -B scripts/run_episode2.py
python -B scripts/run_episode3.py
```

The reviewed real files and offsets are not distributed; the scripts expect
them at the relative paths in source. No lattice scan is repeated for the
Episode 2 arithmetic-progression correction; it reads the preserved Episode 1
JSON. No Gröbner basis was computed.

Evidence:

- `results/phase14.json` - 20,208 windows, 63 exact models, 12 nontrivial.
- `results/episode2.json` - 16-bit AP+carry correction and coordinate results.
- `results/episode3.json` - quadratic/implicit diagnostics.

The shared denominator is `4294836225=(2^16-1)^2`; all 12 nontrivial records
are exact 16-bit word APs with at most one carry. Span-level savings are not
archive-level gains. See `research/phases/14-number-theory.md`.
