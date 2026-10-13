# Maintenance and lifecycle policy

The Data Intelligence and Valorization Laboratory maintains the benchmark via
the repository issue tracker and code review.  Security or undisclosed-data
concerns should be reported through the repository's private security advisory
channel rather than a public issue.

## Decision policy

- Two-person review is required for frozen protocol, result-schema, metric,
  qualification, or KDD reproduction-manifest changes.
- Method fidelity labels may only be upgraded when new parity evidence is
  committed and reviewed.
- A benchmark release never rewrites a published archive; corrections receive
  a new release ID and changelog entry.
- Public leaderboard results must come from evaluator-recomputed outcomes.

## Deprecation and retirement

A method or setting is first marked deprecated with a replacement and at least
one release of notice.  Immediate removal is reserved for licensing, privacy,
security, or invalid-evidence failures.  Retired paper-specific studies are not
kept inside the benchmark distribution.

