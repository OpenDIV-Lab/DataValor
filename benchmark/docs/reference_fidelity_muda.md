# MUDA single-unit reference-fidelity audit

> Audit date: 2026-10-02  
> Scope: one homogeneous good, one unit per real buyer or seller, quasilinear
> utility, nonnegative reports, and an offline centralized market.

## Primary source

Erel Segal-Halevi, Avinatan Hassidim, and Yonatan Aumann, “MUDA: A Truthful
Multi-Unit Double-Auction Mechanism,” *AAAI 2018*,
<https://doi.org/10.1609/aaai.v32i1.11450>. The implementation was audited
against the publisher paper (local SHA-256
`82ec3c8ddf8cf89536078fba5b70ed76f477a8dff18204e910a8f43a9eac0d60`).

MUDA is a multi-unit mechanism expressed through virtual traders. A market in
which every real trader owns or wants one unit is a proper restricted domain:
each real trader contributes exactly one virtual trader. DataMechBench
implements that restriction, not an approximation that changes the unit-domain
rule. It remains classified `paper_variant` because the benchmark does not
implement multi-unit marginal-value schedules or the paper's real-trader
aggregation over multiple virtual traders.

## Shared random-market and price rule

For both variants, each real buyer and seller is assigned independently to the
left market with probability `1/2`; all other traders form the right market.
Each sampled market computes a Walrasian price `p` satisfying

```text
#{buyers with bid > p} = #{sellers with ask < p}.
```

The left market trades at the right market's price and the right market trades
at the left market's price. `_equilibrium_price` tests every report boundary
and every midpoint between adjacent reports, maximizes the equal demand/supply
quantity, and then selects the candidate with maximum distance from a report.
The last rule is a deterministic convention for a non-unique equilibrium
interval; it leaves demand, supply, allocation, and the source theorem
unchanged. Exact equality is non-willing, matching the paper's generic-value
formulation.

| Source operation | Implementation | Golden evidence |
|---|---|---|
| independent `1/2` partition of real traders | `_muda` with one seeded RNG draw per buyer and seller | seed `1` fixes left buyers `{b3}` and left sellers `{s1,s2,s4}` |
| within-market Walrasian price | `_equilibrium_price` | left price `12.5`; right price `70` |
| cross-market price independence | `_muda` passes the opposite price into `_muda_submarket` | both golden trades use the other sample's price |
| strict willingness | `bid > p`, `ask < p` | equal bid/ask fixture returns no trades |

## Lottery-MUDA mapping

When cross-price demand and supply differ, the source lets every short-side
trader trade and orders **real traders** on the long side uniformly at random.
In the single-unit domain this is exactly a shuffle of the willing long-side
IDs followed by truncation to the short-side quantity. Every matched buyer pays
the seller the cross price, so the mechanism is strongly budget balanced.

The seed-1 golden market has excess supply on the left and excess demand on the
right. The continued RNG stream selects `s2` and `b2`, producing trades
`b3-s2 @ 70` and `b2-s3 @ 12.5`. This pins both rationing directions, use of
real-trader lotteries, short-side exhaustion, and direct transfers in
`test_lottery_muda_uses_cross_market_equilibrium_prices_and_long_side_lotteries`.

## Vickrey-MUDA mapping

Vickrey-MUDA retains the highest-gain virtual traders on an over-demanded side
or the lowest-ask virtual traders on an over-supplied side. A retained
long-side trader pays the gain of the first displaced trader. In the unit
domain this yields the following exact thresholds:

- excess demand: the selected buyers pay the `(q+1)`-st willing bid and each
  seller receives the cross price;
- excess supply: every buyer pays the cross price and selected sellers receive
  the `(q+1)`-st willing ask;
- balanced willing sets: buyers transfer the cross price directly to sellers.

For the same seed-1 fixture, the left trade is `b3-s1`: `b3` pays `70`, `s1`
receives displaced ask `15`, and the platform retains `55`. The right trade is
`b1-s3`: `b1` pays displaced bid `40`, `s3` receives `12.5`, and the platform
retains `27.5`. Total auctioneer surplus is therefore `82.5`, proving weak but
not strong budget balance. The literal values and payment directions are
pinned by
`test_vickrey_muda_uses_displaced_long_side_reports_as_thresholds`.

## Code and evidence boundary

- Implementation: `benchmark/src/datamechbench/methods/trading_double.py`,
  functions `_equilibrium_price`, `_muda_submarket`, and `_muda`.
- Behavioral parity: `benchmark/tests/test_trading_fidelity.py`.
- Provenance: `benchmark/catalog/mechanisms.yaml`.
- The pre-existing `random_sampling_double` uses a benchmark midpoint-price
  heuristic. It is deliberately kept separate and is not MUDA evidence.
- Excluded domains: multiple units per real trader, decreasing marginal-return
  schedules, virtual-trader aggregation, online arrival, heterogeneous goods,
  and collusion. Claims or leaderboard interpretations must not extrapolate
  the unit-domain evidence to those domains.

