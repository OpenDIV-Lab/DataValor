# Benchmark discriminability protocol

The audit asks whether the frozen cases and metrics separate mechanisms, rather
than assuming that a large run count implies an informative benchmark.  Seeds
are averaged within a case, cases within a registered block, and blocks within a
wave before method comparisons.

For every track and wave it reports complete method coverage, exact and
practical ties, winner-set size, between-method and within-method block
variance, metric-bound saturation, and market-constraint activation.  Practical
tie tolerances are fixed before reading results: `0.01` for the three primary
metrics.  Missing values remain missing.

These diagnostics are descriptive.  They may motivate a future, independently
frozen case-bank revision, but cases in the current release are never selected
or removed based on this report.

The companion [`pairwise_transfer_protocol.md`](pairwise_transfer_protocol.md)
applies the same fixed tolerances to every headline method pair in v1 and v2.
It separates persistent low resolution (`stable_tie`) from ordered relations
that remain stable, attenuate to a tie, emerge only in v2, or reverse.  The two
audits are intentionally distinct: this document measures within-wave
resolution, while the transfer audit measures whether that resolution carries
across the separately frozen wave.
