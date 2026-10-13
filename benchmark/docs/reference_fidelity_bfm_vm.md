# BFM-VM reference-fidelity and source-code audit

## Scope

This note covers the deterministic BFM-VM mechanism from Cui, Huang, Sun,
and Xue, *Budget-Feasible Mechanisms for Submodular Welfare Maximization in
Procurement Auctions* (ICML 2026). The authoritative paper record is the
[PMLR publication](https://proceedings.mlr.press/v306/cui26b.html); BFM-VM is
Algorithm 2 in its appendix. The authors also publish an experimental
[BFM-SWM repository](https://github.com/xue74193-dot/BFM-SWM).

BFM-VM is evaluated only as a post-freeze procurement extension. It does not
change the KDD headline family set, the v1/v2 held-out protocols, or their
confirmatory decisions.

## Paper claim and implemented estimand

The paper studies a single-parameter procurement auction with a hard payment
budget and a nonnegative, normalized, possibly non-monotone submodular buyer
valuation. With two candidate-set sequences and
`alpha = 1 + sqrt(3)`, Theorem 5.4 gives the source claim
`v(S*) >= v(O)/(12 + 4 sqrt(3))` and `O(n log n)` running time. The paper also
states truthfulness, individual rationality, and budget feasibility under its
assumptions.

DataMechBench implements the paper pseudocode rather than inferring behavior
from the experiment figure:

| Paper Algorithm 2 element | Local implementation | Boundary |
|---|---|---|
| active set `R = {u: c_u <= B}` | filters nonnegative reported costs at or below the budget | sellers outside `R` cannot initialize or enter a candidate |
| `rho_1 = max_{u in R} v(u)` | normalized set oracle and best singleton over `R` | empty or nonpositive-singleton inputs return an explicit out-of-domain branch |
| two candidate sequences | two insertion-ordered lists | input order resolves unspecified iteration and `argmax` ties |
| persistent `owner(u)` | first accepted sequence is retained across later rounds | this is present even though the released C++ omits it |
| descending price `min(p_u, B v(u|S)/rho_t)` | `Decimal` payment update from the oracle marginal | no clipping is used to manufacture budget feasibility |
| final best set from rounds `M-1,M` | stable paper-order candidate comparison | ties retain the first candidate in declared order |

The implementation is in
`benchmark/src/datamechbench/methods/bfm_vm.py`. Utility is normalized by
subtracting `v(empty)`; this preserves marginals but is recorded as a benchmark
deviation. Measured ML utility is an assumption-transfer stress because its
submodularity is not established.

## Author-source audit

The downloadable repository archive is pinned to commit
`82f97be91f4404a9f943c5ebf3d60a272a76a13d`. The archive SHA-256 is
`3700290cedf2d99d56cdbe188a33e11c7c95fb1989e85990b752562ec239b44e`; the
`Crowdsourcing/BFM-VM.h` member SHA-256 is
`4b377288e5c817349602c6426644a3b9c5a07403284de3350daae5ee326bc61c`.
The machine record is
[`bfm_vm_source_audit_v1.json`](../evidence/bfm_vm_source_audit_v1.json).

Two paper/source differences are retained rather than normalized away:

1. Algorithm 2 selects its initial singleton from `R`; the released C++ loops
   over all `node_num` entries without an active-set guard. A seller whose cost
   exceeds the budget can therefore initialize the source implementation.
2. Algorithm 2 records and later reuses `owner(u)`; the released BFM-VM header
   has no owner bookkeeping and recomputes the best candidate sequence.

The repository archive contains no `LICENSE`, `LICENCE`, `COPYING`, or
`NOTICE` file. DataMechBench therefore does not vendor the C++ source and does
not label this audit official-code output parity. The audit establishes source
identity and structural discrepancies only; it does not establish theorem
validity or behavior on every input.

To rebuild the audit from a separately downloaded archive:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/audit_bfm_vm_source.py \
  --source-archive /path/to/BFM-SWM-main.zip \
  --output benchmark/evidence/bfm_vm_source_audit_v1.json
```

## Post-freeze evaluation

The extension reuses the 34 development cases already used by the Triple Eagle
study: 6 additive, 5 controlled submodular, 3 measured-ML, and 20 concentration
cases. It adds no new setting. All 34 BFM-VM rows completed.

| Setting | Cases | Mean oracle ratio | Budget violations | Seller IR violations | Max sampled deviation gain |
|---|---:|---:|---:|---:|---:|
| P-ADDITIVE | 6 | 0.5581 | 0 | 0 | 0 |
| P-SUBMODULAR | 5 | 0.8773 | 0 | 0 | 0 |
| P-ML-ACQUISITION | 3 | 0.9822 | 0 | 0 | 0 |
| P-MARKET-CONCENTRATION | 20 | 0.6459 | 0 | 0 | 0 |

The paired artifact contains 36 comparisons against nine existing paper
mechanisms; seeds of randomized comparators are averaged within case before
case-level effects. Twelve case-bootstrap intervals exclude zero after a
`1e-12` equality tolerance. The pattern is not a universal win: BFM-VM trails
generalized proportional share on additive and concentration cases, beats
Random-EOM on all four setting summaries, ties several deterministic rules on
the controlled submodular/ML surfaces, and is slightly below randomized Triple
Eagle on those same surfaces. This identifies a mechanism-choice boundary,
not a new dominance claim.

Build and verify the complete post-freeze artifact with native Python:

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_bfm_vm_extension.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_bfm_vm_extension.py --verify
```

The authoritative outputs are under
`benchmark/outputs/kdd_bfm_vm_extension/analysis/`. Zero observed finite-grid
violations remain empirical evidence only and are not written as a proof of
truthfulness, IR, or budget feasibility.
