# Counting before search

Let `F` be the number of distinct generator selections (including parameters
not already encoded in the seed), `S=2^s` seeds, `P` possible offsets per seed,
`T` file starts and `k` matched byte length. For independent uniform bytes,
the expected number of seed/address/file-start triples of length `k` is at
most `F S P T / 256^k`; the same quantity is a union bound on seeing any.
For fixed target locations and `r` non-overlapping *independent* slices of
declared lengths totalling `K`, the union bound for one common seed is
`FS P^r 256^-K`. Discovering the target locations adds a factor no larger
than `binom(T,r)` for equal-order slots (and lengths are not free).
Dependence, overlapping source slices, and low entropy targets require
another model; counts are not proofs of independence for a specific PRNG.

For a particular seed sharing saves roughly `(r-1)(s+log2 F)` against
independent references, before address, position, length, and residual costs.
However the chance compatibility with a fixed seed decreases jointly with `K`.
At 4096×96 positions, a 3-byte hit for a fixed uniform target start is expected
with probability about 2.3%; a 7-byte hit is about 5.5e-12 per start. At
65536×96 it is still only about 8.7e-11. These formulas count generated
positions generously (starts at the end of each seed may not hold `k` bytes).

An adaptive low-description generator is useful only when the file is itself
compatible with that much smaller generative class (or residual is unusually
small). For any lossless prefix/unique description the count of descriptions
shorter than `b` bits is <2^b. Search cannot change this counting bound.
Learning a target histogram does not invalidate it: its table, and any
residual/error positions, must be counted. For a fixed ideal source
distribution `p(x)` ordinary entropy coding assigns length near `-log2 p(x)`;
sampling independently until `x` appears typically costs about `1/p(x)`
draws. A draw index alone then costs about the same number of bits, before
model and framing.
