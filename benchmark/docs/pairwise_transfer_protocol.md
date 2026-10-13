# Pairwise ordering-transfer protocol

This audit asks how much of the headline leaderboard's pairwise resolution
survives from frozen v1 selection evidence to the separately frozen v2 wave.
It complements the six preregistered claim contrasts: every one of the 40
headline method pairs is included, but no new confirmatory hypothesis test is
created.

## Estimand and aggregation

For each track, seeds are averaged within case, cases within registered block,
and blocks with equal weight. The primary metric and direction are unchanged:

| Track | Metric | Better | Practical tolerance |
|---|---|---|---:|
| valuation | `replication_owner_rank_change` | lower | 0.01 |
| procurement | `oracle_ratio` | higher | 0.01 |
| trading | `gain_from_trade_ratio` | higher | 0.01 |

For a canonical `(left, right)` pair, positive oriented advantage always means
that `left` is better. Each wave is classified as `left_better`,
`right_better`, or `practical_tie`. The cross-wave category is then one of
`stable_order`, `stable_tie`, `attenuation_to_tie`, `emerging_order`, or
`reversal`.

The tolerance was fixed by the existing discriminability protocol before this
audit. It is not selected per pair or adjusted after inspecting v2.

## Fail-closed coverage

The artifact is valid only when it contains all 15 valuation, 15 procurement,
and 10 trading pairs. Missing methods, blocks, cases, finite measurements, or
duplicate method/block/case/seed keys invalidate the audit rather than silently
reducing a denominator.

## Interpretation boundary

A stable order is evidence that the measured primary-metric relation survived
these two registered waves. It is not a theorem check, significance test,
cross-source guarantee, or population ranking. A practical tie means only that
the primary-metric difference is within the declared tolerance; mechanisms can
still differ in allocation, payment, constraints, fidelity, resource use, or
participant incidence.
