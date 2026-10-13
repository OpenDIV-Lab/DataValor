# Procurement reference-fidelity audit: CGL, Jalaly--Tardos, and Triple Eagle

> Audit date: 2026-10-02  
> Scope: offline, single-parameter sellers; one indivisible item/data-owner
> bundle per seller; nonnegative reported costs; a public monotone submodular
> buyer utility; and a hard buyer budget.

## Primary sources

- Ning Chen, Nick Gravin, and Pinyan Lu, “On the Approximability of Budget
  Feasible Mechanisms,” SODA 2011, <https://arxiv.org/abs/1007.3801>.
- Pooya Jalaly and Eva Tardos, “Simple and Efficient Budget Feasible
  Mechanisms for Monotone Submodular Valuations,” WINE 2018,
  <https://arxiv.org/abs/1703.10681>.
- Kai Han, You Wu, He Huang, and Shuang Cui, “Triple Eagle: Simple, Fast and
  Practical Budget-Feasible Mechanisms,” NeurIPS 2023,
  <https://papers.neurips.cc/paper_files/paper/2023/hash/6af779991368999ab3da0d366c208fba-Abstract-Conference.html>.

The public source/official proceedings artifacts, rather than a secondary description, were used to map
the pseudocode, constants, probability branches, and threshold-payment
semantics below.

Triple Eagle's offer-price mechanisms have a different payment construction
from the threshold-payment mechanisms below. Their complete algorithm and
claim mapping is audited separately in
[`reference_fidelity_triple_eagle.md`](reference_fidelity_triple_eagle.md).
The absence of an eligible official implementation for all four searched
procurement works is documented in
[`procurement_external_implementation_search.md`](procurement_external_implementation_search.md).

## Shared interpretation and numerical payment contract

Both papers work in a single-parameter procurement domain. A deterministic
allocation rule is truthful when it is monotone in each seller's declared
cost and a winner receives the critical bid

```text
inf { c_i : i is no longer selected at (c_i, c_-i) }.
```

The implementation evaluates this paper-defined threshold by 64 iterations
of `Decimal` bisection on `[reported_cost, B]`, rerunning the complete
deterministic allocation rule at every candidate bid. Its absolute interval
width is at most `B / 2^64`; it is a numerical evaluation of the paper rule,
not a pay-as-bid replacement. Randomized mechanisms first freeze the seeded
paper branch, so each realized deterministic mechanism has its own threshold
payment, as required by universal truthfulness.

Tie-breaking among equal marginal-density or singleton values uses seller ID.
The papers leave ties unspecified; this deterministic convention does not
change the stated value, budget, or threshold rule.

Both sources use normalized valuations with `v(empty)=0`. For ML utilities
that expose a nonzero baseline accuracy, `_utility_gain` and the exact oracle
subtract `v(empty)` before every singleton/optimum comparison. The allocation
is therefore invariant to adding a constant baseline; this is pinned by
`test_cgl_deterministic_normalizes_nonzero_empty_set_utility`.

## CGL 2011 mapping

### Random-Mechanism-SM

| Paper rule | Implementation | Golden evidence |
|---|---|---|
| Filter to `A={i:c_i<=B}` and choose the largest eligible singleton `i*` | `_best_singleton_rule` | above-budget sellers cannot become `i*` through the shared rule |
| With probability `2/5`, return `i*` and pay threshold `B` | `_cgl_randomized`, `best_singleton` diagnostic | `test_cgl_random_sm_uses_paper_three_fifths_mixture` |
| With probability `3/5`, return Greedy-SM with budget fraction `B/2` | `_cgl_randomized`, `_proportional(..., half_budget=True)` | seeded branch test plus `test_cgl_random_sm_seeded_branch_frequency_matches_paper_probability` |
| Greedy-SM adds the next marginal-density seller while `c_k <= (B/2)m_k/v(S_k)` | `_marginal_greedy_rule(..., budget_factor=0.5)` | greedy branch selects the paper-feasible prefix |
| Winners receive their threshold bids | `_threshold_payments` | existing IR/budget/monotonicity tests and the shared numerical contract above |

The pre-audit implementation used a 1/2--1/2 mixture. It was corrected to the
paper's 3/5 greedy and 2/5 singleton mixture before promotion.

### Mechanism-SM (deterministic)

Let

```text
x = (1 + 4e + sqrt(1 + 24e^2)) / (2(e - 1)).
```

| Paper rule | Implementation | Golden evidence |
|---|---|---|
| Compute `i*` and the exact `opt(A \ {i*}, B)` | `_best_singleton_rule`, `_exact_optimum_value(..., excluded={i*})` | singleton and greedy branch cases |
| Return `i*` iff `x v(i*) >= opt(A \ {i*},B)` | `_cgl_deterministic_rule` | `test_cgl_deterministic_uses_paper_singleton_branch_and_threshold_payment` |
| Otherwise return Greedy-SM(`A,B/2`) | `_cgl_deterministic_rule` | `test_cgl_deterministic_uses_paper_greedy_sm_branch` |
| Recompute the full branch rule for the winner's critical bid | `_threshold_payments(..., _cgl_deterministic_rule)` | singleton threshold is exactly `B`; strategic metric tests exercise branch changes |

The exact subset oracle makes this reference mechanism exponential, exactly
as declared by CGL for general submodular utilities. DataMechBench therefore
uses it only on the benchmark's small owner markets and reports runtime.

## Jalaly--Tardos 2018 mapping

| Paper mechanism | Source rule | Implementation and parity evidence |
|---|---|---|
| Greedy-TM(`0.5`) | marginal-density order; continue while `c_k/m_k <= 0.5 B/v(S_k)` | `_jt_greedy_tm_rule`; `test_greedy_tm_matches_paper_tight_additive_example` reproduces the paper's `B=4` tight example |
| Random-TM(`0.5`) | probability `3/5` Greedy-TM, otherwise largest singleton | `_jt_mechanism`; `test_random_tm_fixes_the_paper_mixture_branch_from_seed` |
| Greedy-EOM(`0.5`) | use exact `opt(A,B)` and return the prefix before `v(S_k)>0.5 opt` | `_jt_greedy_eom_rule`; exact-oracle branch tests |
| Random-EOM(`0.5`) | probability `1/2` Greedy-EOM, otherwise largest singleton | `_jt_mechanism`; `test_eom_variants_cover_singleton_and_exact_oracle_branches` records branch and probability |
| Deterministic-EOM | return singleton iff `v(i*) >= ((sqrt(17)-3)/4) opt(A\{i*},B)`, else Greedy-EOM(`0.5`) | `_jt_mechanism`; `test_deterministic_eom_uses_published_branch_constant_near_boundary` checks both sides of the boundary |
| Threshold payments | maximum winning report with other reports fixed | `test_jalaly_tardos_winner_payment_is_critical_threshold` checks winning just below and losing just above every returned payment |

## Classification and boundaries

Within the declared domain, `cgl_deterministic`, `cgl_randomized`,
`jt_greedy_tm`, `jt_random_tm`, `jt_random_eom`, and
`jt_deterministic_eom`, `triple_eagle_randomized`, and
`triple_eagle_deterministic` are classified `paper_exact`.

This classification does not extend to multi-parameter sellers, online
arrival, nonmonotone utilities, negative costs, large instances where the
exact optimum oracle is replaced, or strategic collusion. Empirical sampled
misreport metrics remain audits rather than proofs of DSIC.

`generalized_proportional_share` remains `paper_variant`: it implements a
useful proportional-share allocation core, but it is not Singer's complete
randomized mechanism with the paper's market partition, modified winner set,
payment caps, and singleton mixture. It is intentionally not promoted by
this audit.
