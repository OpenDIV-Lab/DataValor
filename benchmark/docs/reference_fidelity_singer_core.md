# Singer proportional-share source-core audit

> Audit date: 2026-10-02  
> Scope: offline single-parameter procurement with one item/data-owner bundle
> per seller, nonnegative costs, a public normalized monotone submodular value
> oracle, and a hard buyer budget.

## Primary source

Yaron Singer, “Budget Feasible Mechanisms,” *FOCS 2010*,
<https://arxiv.org/abs/1002.2334>. The allocation condition and additive
threshold formula below were checked against the arXiv TeX source, not a
secondary implementation.

The catalog name `generalized_proportional_share` denotes a reusable source
core, not Singer's complete randomized approximation mechanism. The distinction
is intentional: parity evidence can establish that a documented component is
faithful without relabeling a larger benchmark adaptation `paper_exact`.

## Allocation core

Starting from the empty set, the proportional-share allocation rule repeatedly
recomputes every remaining seller's marginal contribution, orders by marginal
value divided by reported cost, and accepts the next seller `i` while

```text
c_i <= B * V_i / V(S_i),
```

where `V_i` is the marginal contribution at that step and `S_i` is the prefix
including `i`. `_marginal_greedy_rule(..., budget_factor=1)` implements these
operations. Equal ratios are resolved by marginal value and seller ID; the
source leaves exact ties unspecified.

Payments are critical reports for this complete allocation core. For each
winner, `_threshold_payments` fixes every other report and bisects `[c_i,B]`
for 64 iterations, rerunning the allocation rule. The interval width is at
most `B/2^64`; the procedure evaluates the source threshold rather than paying
the submitted cost.

## Additive golden fixture

For additive values `(v_a,v_b,v_c)=(6,3,1)`, reports `(2,2,2)`, and budget
`B=6`, dynamic density order is `a,b,c`. The proportional-share test accepts
`a` and `b` and rejects `c`:

```text
a: 2 <= 6 * 6/6
b: 2 <= 6 * 3/9
c: 2 >  6 * 1/10.
```

Singer gives the additive winner threshold

```text
theta_i = min(v_i B / sum_{j in S} v_j,
              v_i c_{k+1} / v_{k+1}).
```

With winning set `S={a,b}` and first excluded seller `c`, this yields
`theta_a=min(4,12)=4` and `theta_b=min(2,6)=2`. The literal allocation and
both payments are pinned by
`test_generalized_proportional_share_matches_singer_additive_core` in
`benchmark/tests/test_procurement_fidelity.py`.

## Source-to-code evidence

| Source rule | Implementation | Evidence |
|---|---|---|
| recompute marginal value at each prefix | `_marginal_greedy_rule` | additive winner order and existing submodular settings |
| order by marginal value/cost | `_marginal_greedy_rule` candidate key | golden order `a,b,c` |
| proportional-share stopping inequality | `allowed = B * marginal / total_value` | `c` is rejected at `2 > 0.6` |
| winner critical report | `_threshold_payments` over the complete rule | payments `4` and `2`, tolerance `1e-12` |
| hard ex-post budget | `_proportional` diagnostic | total payment `6=B` |

## Why the method remains `paper_variant`

Singer's complete submodular mechanism is not this allocation core alone. The
paper filters a designated cost range, invokes a modified proportional-share
construction with a scaled budget
`B'=(e-1)/(12e-4) B`, compares/combines it with the best singleton, and uses a
random mixture. Those mechanism-level branches, winner-set modification, and
payment caps are absent from `generalized_proportional_share`. Moreover, the
closed-form threshold fixture above proves the additive specialization; the
general-submodular threshold is evaluated numerically rather than reproduced
from a separate official implementation.

Accordingly the catalog deviation is:

```text
proportional-share allocation/payment core only; Singer singleton mixture,
modified mechanism, and budget scaling omitted
```

This evidence supports source-core comparisons and ablations. It does not
support claims that the benchmark method inherits the approximation ratio or
universal-truthfulness theorem of Singer's full randomized mechanism.

