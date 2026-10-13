# Triple Eagle reference-fidelity audit

> Audit date: 2026-10-03  
> Implemented source: Kai Han, You Wu, He Huang, and Shuang Cui, “Triple
> Eagle: Simple, Fast and Practical Budget-Feasible Mechanisms,” NeurIPS
> 2023, <https://papers.neurips.cc/paper_files/paper/2023/hash/6af779991368999ab3da0d366c208fba-Abstract-Conference.html>.

## Claim boundary

`triple_eagle_randomized` and `triple_eagle_deterministic` are native,
paper-exact translations of Algorithms 1--3 for an offline single-parameter
procurement market with a nonnegative normalized monotone-submodular value
oracle and hard budget `B`. They are not official-code adapters: the source
paper and public author/repository searches exposed no eligible implementation
to execute. The separate search audit records that negative result.

The implementation fixes the otherwise arbitrary seller order to
`case.seller_ids`, breaks equal singleton values by seller ID, and uses a
seeded NumPy generator only for Algorithm 1's published mixture. These are
reproducibility conventions, not changes to the mechanism.

## Shared LSDPricing mapping (Algorithm 2)

For every considered seller `u`, let `A` be the accepted prefix and let
`eta=f(u* | empty)` be the largest eligible singleton marginal. The offered
price is implemented literally as

```text
p_u = B f(u | A) / (f(A) + eta).
```

The seller is appended only when its reported cost is no larger than this
offer. From the accepted insertion sequence, the mechanism returns the largest
suffix whose offered prices sum to at most `B`; each returned seller receives
its recorded offer. `test_triple_eagle_randomized_matches_lsd_pricing_and_suffix_free_branch`
checks all offers on a hand-computed additive instance, while
`test_triple_eagle_returns_largest_budget_feasible_insertion_suffix` forces the
suffix operation to discard an accepted prefix.

The paper assumes `f(empty)=0`. The adapter caches `f(empty)` and subtracts it
from every set value. A constant ML baseline therefore cannot alter an
allocation or price; the baseline-shift golden test enforces this contract.
Sellers with `c_u>B` are removed before choosing `u*`, following the paper's
extension for dropping the simplifying `c_u<=B` assumption.

## TripleEagleRan mapping (Algorithm 1)

The implementation uses

```text
alpha = (sqrt(13)+1)/2,
Pr[singleton] = alpha/(alpha+2),
Pr[best effort] = 2/(alpha+2).
```

It first executes LSDPricing. When the accepted set has enough value, the
budget-feasible insertion suffix is returned. Otherwise the mechanism draws
the published mixture between the best singleton paid `B` and the best-effort
LSD suffix. Literal branch, price, and 100-seed probability-panel tests pin
these behaviors.

Theorem 1's approximation factor is `(sqrt(13)+5)/2`; hence the benchmark's
claim-aligned welfare floor is
`2/(sqrt(13)+5)=0.2324081207560018`. This is an expectation-over-randomness
claim. It is deliberately marked `assumptions_unmet` on a single random seed
unless the evaluation record explicitly represents an internal-randomness
aggregate.

## TripleEagleDet mapping (Algorithm 3)

The implementation uses `alpha=sqrt(6)`. In phase one it scans the fixed
seller order and offers

```text
p_u = B f(u | K) / (alpha f(u*))
```

until `f(K)>=f(u*)`. It then invokes Algorithm 2 on the remaining sellers with
the current set and the same best singleton. When phase one cannot reach that
condition, it returns the best singleton paid `B`. The two golden branch tests
check both paths and the exact phase-one and LSD prices.

Theorem 2's deterministic factor is `2+sqrt(6)`; the corresponding welfare
floor is `1/(2+sqrt(6))=0.22474487139158905`.

## Machine-checkable claims

The catalog scopes expectations by both shared family `triple_eagle` and
specific `method_id`, so the two theorem constants cannot be silently
interchanged. For each method it records budget feasibility, zero seller IR
violations, and the theorem-specific oracle-ratio floor. The approximation
claims apply only when all cataloged assumptions hold; measured ML utility is
an explicitly labeled empirical transfer rather than theorem evidence.

The output diagnostics expose branch, alpha, accepted and processed order,
offers, suffix truncation, above-budget filtering, total payment, and value
oracle query count. They support audits and efficiency analysis but do not
expand the paper's theoretical domain.

## Deliberate non-claims

This audit does not claim official-code parity, nonmonotone guarantees,
online arrivals, multi-parameter truthfulness, collusion resistance, or a
theorem for measured ML utilities. `paper_exact` describes the audited
Algorithms 1--3 translation only. Empirical sampled deviation tests remain
diagnostics rather than proofs.
