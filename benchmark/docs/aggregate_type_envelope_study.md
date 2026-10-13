# Aggregate-compatible economic types: CNIL envelope study

## Benchmark question

Public evidence about data prices is often released as grouped acceptance
curves rather than transaction-level bids and asks. A benchmark that replaces
every group by one midpoint can make a mechanism ranking look much more stable
than the source permits. This study asks a narrower, operational question:

> If every published supply and demand anchor is held fixed, can admissible
> within-bin type placement change the ranking of double-auction mechanisms?

The study is `T-AGGREGATE-TYPE-ENVELOPE`. It compares every registered
market-wide double-auction comparator with allocation and payment semantics on
this homogeneous single-unit domain: eleven methods in four evidence groups.

| Comparison group | Methods | Interpretation |
|---|---|---|
| headline reference | McAfee, Trade Reduction, SBBA, Lottery-MUDA, Vickrey-MUDA | Primary paper-mechanism sensitivity comparison; MUDA remains a disclosed single-unit specialization |
| canonical guardrail | VCG double auction | Efficient-allocation reference whose deficit risk must remain visible |
| pricing baseline | pay-as-bid; seller-, midpoint-, and buyer-price k-double variants | Common or source-linked pricing comparators, not equivalent truthfulness claims |
| diagnostic reference | random-sampling double auction | Split-market diagnostic; not claimed as the SBBA paper mechanism |

The groups prevent a classical baseline or allocation oracle from acquiring the
same source-fidelity interpretation as a headline paper mechanism merely
because it appears in the same output table.

## Source and observable

The source is the official CNIL report, *Monetisation of personal data: how
much is our data worth?* The survey covered 2,082 French residents from
December 18--23, 2024. Its accessible figure publishes six monthly-price
anchors for seller acceptance and six for buyer acceptance:

| EUR/month | 1.00 | 4.30 | 10.75 | 37.84 | 73.10 | 148.78 |
|---:|---:|---:|---:|---:|---:|---:|
| seller share accepting | 0.04 | 0.20 | 0.38 | 0.51 | 0.64 | 0.69 |
| buyer share accepting | 0.99 | 0.90 | 0.75 | 0.50 | 0.25 | 0.10 |

These are aggregate stated-price curves. They are not auction bids, observed
settlements, or respondent-level reservation values. The report separately
states that 35% of respondents would never sell. That statement is retained as
source context; it is not forced to equal the 31% unresolved above the largest
plotted seller anchor. The two quantities can differ because the public page
does not expose the respondent-level coding or weighting needed to reconcile
them.

## Type-envelope construction

The benchmark converts percentages to a 100-quantile audit grid without
claiming that the quantiles are observed people. Seller intervals contain
4, 16, 18, 13, 13, and 5 active units, exactly reproducing the six cumulative
seller anchors. The remaining 31 units are unresolved above the published
support and are excluded from the active market. Buyer intervals reproduce all
six decreasing demand anchors; the top 10 units are right-censored and fixed
only at the published lower bound EUR 148.78.

For each bounded interval, its units are evenly spread under three declared
placements:

- `lower`: evenly spaced over the lower half of the interval;
- `midpoint`: evenly spaced over the full open interval; and
- `upper`: evenly spaced over the upper half of the interval.

Crossing the three seller placements with the three buyer placements creates
nine profiles. This construction deliberately avoids assigning an entire bin
to one point, which would introduce artificial ties and test tie-breaking more
than economic support. Every generated profile is checked against all twelve
published aggregate anchors. The resulting active markets contain 69 distinct
seller asks and 91 distinct buyer bids; the only remaining buyer ties are the
10 observations imposed by right censoring at the largest public anchor.

The nine profiles are a transparent sensitivity grid. They are **not** sharp
partial-identification bounds, confidence intervals, draws from a population,
or reconstructed respondent microdata.

## Evaluation protocol

Each mechanism is evaluated by gain-from-trade (GFT) divided by the efficient
GFT of the same profile. The seven deterministic mechanisms run once per
profile. SBBA, random sampling, and both MUDA variants are evaluated on seeds
0--31; their per-profile estimand is expected GFT over that fixed seed panel.
Seeds measure only mechanism randomization within a profile and are never
treated as independent markets.

The study reports:

- macro expected GFT: equal-weight mean across the nine profiles;
- worst and best profile GFT;
- aggregate-type sensitivity range: best minus worst profile GFT;
- pairwise rank reversal: the signed expected-GFT difference takes both signs
  over the nine profiles;
- point-profile selection transfer regret: select the best headline mechanism
  on one profile, hold that choice fixed, and measure its regret on every other
  compatible profile; tied source winners are reported under optimistic and
  pessimistic tie-breaking;
- minimum empirical individual-rationality, weak-budget-balance, and
  strong-budget-balance pass rates.

No cross-track score is formed. The primary reversal table is restricted to the
five headline references; a second table reports all eleven comparators without
pretending they share one evidence tier. A reversal is computed from
profile-level expected GFT, not individual random seeds.

## Results

The frozen run contains 1,215 mechanism executions and 99 profile--method
cells.

| Mechanism | Group | Runs | Macro GFT | Worst | Range | Min WBB | Min SBB |
|---|---|---:|---:|---:|---:|---:|---:|
| Buyer-price double | pricing baseline | 9 | 1.000000 | 1.000000 | 0.000000 | 1.000 | 1.000 |
| Midpoint double | pricing baseline | 9 | 1.000000 | 1.000000 | 0.000000 | 1.000 | 1.000 |
| Pay-as-bid double | pricing baseline | 9 | 1.000000 | 1.000000 | 0.000000 | 1.000 | 0.000 |
| Seller-price double | pricing baseline | 9 | 1.000000 | 1.000000 | 0.000000 | 1.000 | 1.000 |
| VCG double auction | canonical guardrail | 9 | 1.000000 | 1.000000 | 0.000000 | 0.000 | 0.000 |
| McAfee | headline reference | 9 | 0.999102 | 0.996789 | 0.003211 | 1.000 | 0.000 |
| Trade Reduction | headline reference | 9 | 0.999038 | 0.996789 | 0.003155 | 1.000 | 0.000 |
| SBBA | headline reference | 288 | 0.996317 | 0.993327 | 0.006673 | 1.000 | 1.000 |
| Random-sampling double | diagnostic reference | 288 | 0.964230 | 0.956071 | 0.019642 | 1.000 | 1.000 |
| Vickrey-MUDA | headline reference | 288 | 0.958842 | 0.950389 | 0.016791 | 1.000 | 0.000 |
| Lottery-MUDA | headline reference | 288 | 0.856053 | 0.846624 | 0.020406 | 1.000 | 1.000 |

The macro ordering alone hides the central result. Two pairwise orderings
reverse while all published anchors remain unchanged:

- McAfee minus SBBA ranges from -0.000973 under
  `TAGG-smidpoint-blower` to 0.005967 under
  `TAGG-smidpoint-bmidpoint`.
- SBBA minus Trade Reduction ranges from -0.005967 under
  `TAGG-smidpoint-bmidpoint` to 0.000973 under
  `TAGG-smidpoint-blower`.

McAfee, Trade Reduction, and SBBA are all near-efficient on these profiles, so
the reversals are small in absolute welfare. Their scientific importance is
different: a grouped public price curve does not identify even the pairwise
ordering of closely matched mechanisms. By contrast, the larger sensitivity
ranges of the split-market MUDA variants show that within-bin geometry also
matters materially when a mechanism uses random partitions and cross-market
prices.

The expanded comparison exposes why GFT cannot be a stand-alone leaderboard.
VCG and the four pricing baselines allocate all efficient trades and therefore
score `1.0` on every profile. VCG nevertheless fails weak budget balance on
every profile. Pay-as-bid is weakly but never strongly budget balanced here.
The three uniform k-double pricing variants are strongly balanced on this
truthful-report replay, but that empirical fact does not turn their multi-unit
extensions into truthful reference mechanisms. Constraint and provenance
labels therefore change which conclusions are admissible even when raw GFT is
tied.

Across all eleven methods there is one additional reversal:
random-sampling double auction minus Vickrey-MUDA ranges from `-0.000058` to
`0.016419`. It is reported as diagnostic evidence, not promoted into the
headline-reference claim.

### Robust recommendation under grouped-type uncertainty

For each profile, the benchmark computes each headline mechanism's expected-GFT
shortfall from the best headline reference on that same profile, then takes the
maximum across profiles. This minimax-regret analysis does not erase the rank
reversals; it answers the complementary decision question of how costly a
mechanism choice can become over the declared envelope.

| Headline mechanism | Mean profile regret | Worst profile regret | Minimax set |
|---|---:|---:|---:|
| McAfee | 0.000170 | 0.000973 | yes |
| Trade Reduction | 0.000234 | 0.000973 | yes |
| SBBA | 0.002955 | 0.005967 | no |
| Vickrey-MUDA | 0.040431 | 0.049555 | no |
| Lottery-MUDA | 0.143219 | 0.153320 | no |

McAfee and Trade Reduction therefore form the tolerance-tied minimax set.
McAfee has the smaller mean regret, but the benchmark does not break the
worst-case tie post hoc. This recommendation is relative only to the five
headline references and nine declared profiles; it does not compare against
pricing baselines or VCG and does not supersede payment or strategic
guardrails.

### Cost of choosing from one imputation

The benchmark also simulates the common workflow that the envelope is designed
to diagnose: choose the expected-GFT winner using only one imputed profile,
then transfer that fixed recommendation to all other profiles preserving the
same twelve public anchors. Two of nine selection profiles are worse than the
global minimax choice even under optimistic handling of tied winners. Under
pessimistic handling, three of nine are worse because
`TAGG-supper-bmidpoint` ties McAfee and SBBA at selection time but those methods
do not transfer equally.

The worst case selects SBBA from `TAGG-smidpoint-blower` or
`TAGG-supper-blower` and then evaluates it on
`TAGG-smidpoint-bmidpoint`. Its transferred regret is `0.005967`, which is
`6.133` times the minimax regret `0.000973`. This is not a probability of
deployment failure—the profiles are not sampled. It is a decision-fragility
certificate: a single permissible point imputation can turn a robust
near-efficient choice into an avoidably weaker one while all observable source
anchors stay fixed.

### Constraint--fidelity selection frontier

A raw leaderboard and a deployable recommendation answer different questions.
The study therefore evaluates five nested, declarative selection views. An
empirical constraint is checked on each profile; provenance filters distinguish
headline paper mechanisms from allocation oracles, pricing baselines, and
diagnostic adaptations. No weighted composite score is introduced.

| Selection view | Methods eligible on every profile | Winner union | Winner intersection | Maximum GFT shortfall from unrestricted best |
|---|---:|---|---|---:|
| unrestricted all comparators | 11 | buyer-price, McAfee, midpoint, pay-as-bid, SBBA, seller-price, VCG | buyer-price, midpoint, pay-as-bid, seller-price, VCG | 0.000000 |
| observed IR + WBB | 10 | buyer-price, McAfee, midpoint, pay-as-bid, SBBA, seller-price | buyer-price, midpoint, pay-as-bid, seller-price | 0.000000 |
| headline IR + WBB | 5 | McAfee, SBBA, Trade Reduction | none | 0.003211 |
| paper-exact headline IR + WBB | 3 | McAfee, SBBA, Trade Reduction | none | 0.003211 |
| paper-exact headline IR + WBB + SBB | 1 | McAfee, SBBA | SBBA | 0.006673 |

The final row needs careful reading. SBBA is the only method eligible on every
profile and the only winner appearing in every profile; McAfee becomes
empirically strongly balanced and co-wins only on a subset. Requiring SBB thus
removes the apparent type-profile instability but doubles the maximum raw-GFT
shortfall relative to the headline IR/WBB view, from `0.003211` to `0.006673`.
This is not automatically a stronger recommendation: the separate finite
report-domain audit retains 174 fixed-seed SBBA deviation witnesses, including
24 tie-free witnesses. Those witnesses diagnose an implementation, domain, or
estimand boundary rather than automatically refuting the source theorem, but
they prevent the stable SBB winner from being advertised as generally
strategyproof.

This creates a useful benchmark finding: narrowing a leaderboard by observable
constraints can make its winner set look more stable while moving the unresolved
uncertainty into another claim dimension. DataMechBench therefore reports the
frontier, its efficiency cost, and the separate incentive evidence instead of
awarding a universal badge.

### Joint claim-aligned admissibility

The selection frontier still evaluates each evidence layer separately. For an
actionable recommendation, the benchmark additionally joins those layers by
mechanism ID and requires all of them simultaneously: paper-exact provenance,
IR/WBB/SBB on all nine profiles, and no counterexample on the mechanism's
separately declared finite-audit estimand.

| Method | Paper exact | IR all | WBB all | SBB all | Finite no-counterexample | Joint pass | Blocking dimension(s) |
|---|---:|---:|---:|---:|---:|---:|---|
| McAfee | yes | yes | yes | no | yes | no | strong budget balance |
| Trade Reduction | yes | yes | yes | no | yes | no | strong budget balance |
| SBBA | yes | yes | yes | yes | no | no | finite counterexample |
| Lottery-MUDA | no | yes | yes | yes | no | no | source fidelity; finite counterexample |
| Vickrey-MUDA | no | yes | yes | no | yes | no | source fidelity; strong budget balance |

No headline method passes the joint gate. This empty intersection is more
informative than declaring SBBA the constrained winner: every component has
plausible candidates, but the currently implemented mechanisms do not combine
all required properties. The three one-failure near misses also give concrete
development targets instead of a vague leaderboard loss. The finite audit is
method-specific: deterministic mechanisms enumerate their declared finite
domain, whereas randomized mechanisms use a fixed-seed panel. Consequently,
`finite no-counterexample` is evidence on that estimand only, never a theorem;
the SBBA witnesses likewise remain implementation/domain/estimand diagnostics
rather than an automatic refutation of the source claim.

### Which requirement makes the gate empty?

An empty conjunctive gate is actionable only if the blocking requirements can
be located. We therefore remove exactly one requirement at a time while keeping
the other four unchanged, then evaluate the admitted set against both the best
headline reference and the unrestricted comparator on every profile.

| Relaxed requirement | Admitted methods | Maximum regret vs headline best | Maximum shortfall vs unrestricted best |
|---|---|---:|---:|
| none | none | N/A | N/A |
| source fidelity | none | N/A | N/A |
| individual rationality | none | N/A | N/A |
| weak budget balance | none | N/A | N/A |
| strong budget balance | McAfee; Trade Reduction | 0.000973 | 0.003211 |
| finite no-counterexample | SBBA | 0.005967 | 0.006673 |

Only SBB and finite no-counterexample evidence are active single relaxations.
More importantly, they do not provide interchangeable escape routes. Ignoring
SBB admits the two minimax-regret mechanisms; ignoring the retained finite
counterexamples admits only SBBA, whose worst headline-relative regret is
`6.133` times larger. Thus a benchmark that omits one property does not merely
change a certification label—it can change the selected mechanism and its
robust welfare loss. This remains a diagnostic counterfactual, not a recommendation
to discard budget balance or strategic evidence. Multi-requirement relaxations
are deliberately excluded because they would turn the analysis into arbitrary
post-hoc model selection.

## What the benchmark establishes

The finding supports a concrete evaluation rule: a mechanism recommendation
based on grouped price evidence must report aggregate-compatible sensitivity,
not just one midpoint-imputed leaderboard. It does not establish population
welfare, a universal winner, or behavior in a deployed data market. A future
licensed respondent-level release can replace this sensitivity setting with a
held-out empirical cohort; until then, the aggregate envelope is useful
precisely because its inferential boundary is explicit and executable.

## Reproduction

From the repository root:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_aggregate_type_envelope.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_aggregate_type_envelope.py --verify
```

The source contract is
`benchmark/catalog/aggregate_type_envelope.yaml`. Machine-readable results are
under `benchmark/outputs/kdd_aggregate_type_envelope/`; `raw_runs.jsonl`, the
profile and method summary CSVs, `headline_regret_summary.csv`,
`point_selection_transfer.csv`, the headline
`rank_reversals.csv`, the expanded
`all_method_rank_reversals.csv`, `selection_view_profile.csv`,
`selection_view_summary.csv`, `joint_admissibility.csv`,
`admissibility_relaxation_frontier.csv`, `findings.json`, and `manifest.json` bind the
result at progressively higher aggregation levels.
