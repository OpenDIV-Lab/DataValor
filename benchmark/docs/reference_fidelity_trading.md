# Trading reference-fidelity audit: McAfee, Trade Reduction, and SBBA

> Audit date: 2026-10-02  
> Scope: homogeneous single-unit buyers and sellers in DataMechBench's
> `double_auction` case type. Multi-unit MUDA is outside this audit.

## Sources

- R. Preston McAfee, “A Dominant Strategy Double Auction,” *Journal of
  Economic Theory* 56(2), 1992, pp. 434--450,
  <https://doi.org/10.1016/0022-0531(92)90091-U>.
- Erel Segal-Halevi, Avinatan Hassidim, and Yonatan Aumann, “SBBA: a
  Strongly-Budget-Balanced Double-Auction Mechanism,” Section 3,
  <https://arxiv.org/abs/1607.05139>.
- Erel Segal-Halevi, author-maintained `auctions` implementation, commit
  `d1a55eaacb337ecebeaf5f57a67bcd6a9d4411eb`,
  <https://github.com/erelsgl/auctions>.
- Rica Gonen and Erel Segal-Halevi, “Strongly Budget Balanced Auctions for
  Multi-Sided Markets,” *AAAI 2020*, pp. 1998--2005,
  <https://doi.org/10.1609/aaai.v34i02.5571>. The paper explicitly presents the
  mechanism as a generalization of the 2016 two-sided SBBA setting.

The SBBA authors' TeX source was also inspected because it states both cases,
the sentinel convention, and the seller lottery without ambiguity.

## Shared ordering and efficient quantity

Both implementations sort buyer reports as

```text
b_1 >= b_2 >= ...
```

and seller reports as

```text
s_1 <= s_2 <= ...
```

with deterministic actor-ID tie-breaking. `k` is the largest matched index
with `b_k >= s_k`. Actor-ID tie-breaking only selects among equal reports and
does not alter allocation utility or payments.

## McAfee mapping

| Paper rule | Implementation | Golden evidence |
|---|---|---|
| Compute `p=(b_(k+1)+s_(k+1))/2` only when both reports exist | `McAfeeDoubleAuction.price`, `candidate_price` | `test_mcafee_matches_candidate_price_and_trade_reduction_rules` |
| If `s_k <= p <= b_k`, trade all `k` pairs at `p` | `candidate_price` branch | candidate market trades two units at price 7 |
| Otherwise cancel the marginal pair | `trade_reduction` branch uses `k-1` | reduction market trades one of two efficient units |
| Winning buyers pay `b_k`, winning sellers receive `s_k` in reduction branch | separate platform payments | buyer price 8 and seller price 7 |
| No `k+1` report implies reduction branch | `candidate_price is None` | existing all-profitable edge-case test |
| No efficient pair implies no trade | `no_trade` branch | existing edge-case test |

The benchmark adapter only converts the reusable DataValor outcome into the
benchmark's allocation/payment contract; it does not change clearing or price
formation.

### Official-code cross-check

The paper-derived tests are complemented by execution of the pinned
author-maintained implementation. Five fixtures cover candidate-price full
trade, rejected candidate price, exhausted-side reduction, zero-GFT inclusion,
and no trade. For each fixture the validator compares six hand-derived
observables: trade count, buyer price, seller receipt, realized gain from trade,
auctioneer surplus, and branch code. Both implementations match each other and
the fixture oracle exactly (`maximum_absolute_error = 0` and
`maximum_fixture_oracle_error = 0`).

The evidence record hash-binds `mcafee_protocol.py` and all three executed
dependency modules, rather than binding only the entrypoint. The upstream
`trade.py` lacks a terminal newline; text vendoring appends one byte. Both the
upstream and executed hashes and the semantic-null normalization are disclosed
in the result instead of calling the vendored tree byte-identical. This is an
official-code algorithm-core check, not an independent end-to-end reproduction.

## Standalone Trade Reduction mapping

The benchmark also exposes McAfee's trade-reduction outcome as a standalone
mechanism rather than only as the fallback branch of `mcafee`. Let `k` be the
efficient quantity. It executes the first `k-1` efficient pairs, charges every
winning buyer `b_k`, and pays every winning seller `s_k`. The platform keeps
`(k-1)(b_k-s_k)`, which is nonnegative because pair `k` is efficient.

| Source rule | Implementation | Golden evidence |
|---|---|---|
| Remove exactly the marginal efficient pair | `_trade_reduction` uses `max(0,k-1)` | `test_standalone_trade_reduction_matches_mcafee_marginal_prices` pins `k=3 -> 2` |
| Winning buyers pay `b_k`; winning sellers receive `s_k` | separate platform transfers at `buyer_price` and `seller_price` | the same test pins buyer price 8, seller price 7, and platform surplus 2 |
| `k=1` executes no trade but retains the marginal thresholds | zero-quantity branch records both prices and `efficient_trade_count=1` | `test_standalone_trade_reduction_audits_zero_quantity_boundaries` |
| `k=0` executes no trade and has no marginal reports | prices are `None`, quantity and surplus are zero | the same boundary test |
| Equal reports do not change the economic rule | actor IDs only break equal-report ordering | `test_standalone_trade_reduction_ties_use_actor_id_without_changing_rule` |

The diagnostics expose `allocation_rule`, `efficient_trade_count`,
`buyer_price`, `seller_price`, and platform surplus. This makes the standalone
rule auditable without inferring `k` from allocations after the marginal pair
has been removed.

## SBBA mapping and corrected discrepancy

SBBA fixes the price to `min(s_(k+1), b_k)`, using `s_(k+1)=infinity` when no
next seller exists.

| Paper Section 3 rule | Correct implementation | Golden evidence |
|---|---|---|
| Case 1: `s_(k+1) <= b_k`; price is `s_(k+1)` | first `k` buyers and first `k` sellers trade | all seeds trade `(b1,b2)` with `(s1,s2)` at 7 |
| The `s_(k+1)` price setter does not trade | seller slice is exactly `sellers[:k]` | test forbids `s3` from entering the lottery |
| Case 2: `s_(k+1) > b_k`; price is `b_k` | marginal buyer `b_k` is excluded | only `b1` trades when `k=2` |
| Case 2 excludes one of the first `k` sellers uniformly | seeded uniform excluded index | seeds cover exclusion of both `s1` and `s2` |
| Every executed deal uses one price and direct buyer-to-seller transfer | `_direct_uniform` | existing strong-budget-balance metric test |

The previous implementation inverted the rationing behavior: it randomized
over `k+1` sellers in Case 1 and retained all `k` pairs in Case 2. That version
was not paper-faithful. The corrected implementation records `branch`,
`price_setter`, `efficient_trade_count`, and `excluded_seller`, so future
results can be audited without reconstructing internal control flow.

### Author-code specialization cross-check

The author-maintained `trade_reduction_protocol.py` implements the later
multi-sided external-competition SBB mechanism. We execute that unchanged
source at commit `d1a55eaa` with recipe `[1,1]` and compare its two-category
specialization with the local 2016 SBBA rule. Five general-position fixtures
cover no trade, one- and two-unit full trade, and two- and three-seller lottery
supports. Nine hand-derived observables agree exactly: trade count, price,
buyer/seller candidate counts, randomized side, exact expected GFT over the
finite exclusion support, strong budget balance, and branch code.

This is deliberately not presented as unrestricted equivalence. At the
zero-external-competition tie `(bids=[12,10,8,1], asks=[2,4,7,8])`, the later
generalized source tests `best_containing_GFT > 0`, reduces to two trades, and
randomizes over three sellers. Section 3 SBBA uses `s_(k+1) <= b_k`, so the local
paper-exact rule executes all three trades at price 8. The fixture and both
oracle vectors are retained under `boundary_comparisons`, outside the five
validated-domain comparisons. Identity-level random-draw parity is also not
claimed because the upstream object represents candidate sets and expectations,
not a seeded identity draw.

## Fidelity conclusion

Within the declared single-unit homogeneous setting, `mcafee`,
`trade_reduction`, and `sbba` are classified `paper_exact`. This
classification does **not** extend to:

- multi-unit traders;
- heterogeneous goods;
- online arrival or spatial transit costs;
- the current `lottery_muda`/`vickrey_muda` specializations.

The KDD readiness contract counts these as three trading reference-grade
families. Raw results generated before the correction retain their old
`paper_variant` metadata and fail `result_provenance_alignment`; they must be
rerun rather than merely re-rendered. The 2026-10-02 full release was rerun
after the correction and now passes that alignment gate.
