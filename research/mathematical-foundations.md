# Mathematical foundations

For a discrete source with probabilities \(p(x)\), Shannon entropy is
\(H(X)=-\sum_x p(x)\log_2 p(x)\). For dependent streams the relevant quantity is
the joint entropy or entropy rate. A predictor with wrong probabilities pays
cross-entropy, not the source's optimal entropy. Reversible transforms do
not create information; they can expose structure to a restricted coder.

Kolmogorov complexity is the length of a shortest program producing a string
on a chosen universal machine, defined up to an additive constant across
universal machines and uncomputable in general. SXZ evaluates concrete finite
descriptions, not this optimum. The minimum-description-length (MDL) score
counts model, parameters, location map, output length, residual and any shared
side information. A recurrence \(x_t=\sum_i a_i x_{t-i}+b\bmod m\) has a short
description only when its coefficients, initial state and residual genuinely
encode more cheaply than the alternative. The same accounting applies to
number-theoretic sequences and pseudorandom output.

For independent uniform symbols in an alphabet of size \(B\), a given
length-\(k\) match has probability \(B^{-k}\). With \(T\) target and \(N\)
reference positions, linearity gives an expected \(TN B^{-k}\) matching pairs
when those assumptions apply; the same value is a union bound on any match.
The approximation \(1-\exp(-N/B^k)\) for one target start is not exact for
dependent or overlapping starts. Neither irrationality nor a finite matching
experiment proves normality of a constant. Resolving roughly \(B^k\)
equally likely addresses alone costs about \(k\log_2B\) bits.

For \(F\) generator choices, \(S\) seeds and \(P\) offsets, the ASMC count
becomes \(FSPT/B^k\). For \(r\) fixed independent slices totalling \(K\)
symbols sharing one seed, an upper bound is \(FSP^r/B^K\); selecting target
locations adds choices and overlap can violate the model. Seed reuse can
save roughly \((r-1)(\log_2 F+\log_2 S)\) bits without saving address costs.
Allowing up to \(h\) substitutions expands the match space by
\(\sum_{j=0}^h {k\choose j}(B-1)^j\), but the sufficient residual must be sent.
At most \(2^b-1\) distinct binary descriptions have length less than \(b\);
search time does not change that counting bound. See [ASMC bound](../lab/sxz-adaptive-stochastic-mosaic/BOUND.md).
