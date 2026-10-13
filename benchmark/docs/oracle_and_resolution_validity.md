# Reference-oracle and resolution validity

This protocol closes two measurement gaps in the market-track leaderboards.

## Exact finite-case oracle certificates

`oracle_ratio` and `gain_from_trade_ratio` are meaningful only when their
reference denominators are correct.  Evaluator-side outcome recomputation
checks arithmetic consistency, but it cannot by itself prove that a persisted
oracle outcome is optimal.  DataMechBench therefore uses a second code path:

- procurement enumerates every seller subset, recomputes reported cost and
  case utility, filters by the hard budget, and applies the declared canonical
  tie rule;
- homogeneous unit trading recomputes the sorted buyer/seller frontier for
  every feasible trade cardinality and selects maximum gain from trade.

The certificates retain the entire finite frontier, the persisted oracle
allocation, the independently certified optimum, and the raw-results hash.
They fail closed on missing cases, incomplete domains, infeasible allocations,
arithmetic disagreement, or outcome disagreement.  Across held-out v1,
held-out v2, and the diagnostic challenge panel, 29 market cases pass: 14
procurement cases cover 2,624 subset candidates and 15 trading cases cover 150
cardinality candidates.

This is exact evidence for the frozen finite cases.  It is not a theorem about
arbitrary instances or an independent author implementation of a mechanism.

## Fixed-grid resolution sensitivity

The primary practical tolerance remains 0.01.  The post-freeze sensitivity
protocol additionally evaluates every headline pair at
`[0, 0.005, 0.01, 0.02, 0.05]`.  The grid is stored in
`catalog/resolution_sensitivity.yaml` and cannot be selected after inspecting a
particular pair.

Held-out scores aggregate seeds within cases, cases within source blocks, and
source blocks with equal weight.  A challenge pair is separable when at least
one prospectively registered theory-boundary case exceeds the tolerance.  All
pair/tolerance cells are emitted and semantically recomputed from their bound
raw inputs.

| Panel | Valuation separable @ .01 / .05 | Procurement @ .01 / .05 | Trading @ .01 / .05 |
|---|---:|---:|---:|
| held-out v1 | 15 / 14 | 5 / 0 | 6 / 6 |
| held-out v2 | 13 / 11 | 5 / 0 | 6 / 6 |
| theory-boundary challenge | n/a | 14 / 14 | 10 / 10 |

The v2 procurement count already falls from 5 to 0 at tolerance 0.02.  This
distinguishes small-effect separation in the natural procurement panels from
the trading track's six tolerance-robust pairs and four exact/stable ties.  The
challenge panel demonstrates branch-level discriminability; it remains outside
held-out population inference.

## Reproduction

```bash
PYTHONPATH=benchmark/src:src python benchmark/scripts/run_kdd_heldout_confirmation.py --reuse-results
PYTHONPATH=benchmark/src:src python benchmark/scripts/run_diagnostic_challenge_panel.py
PYTHONPATH=benchmark/src:src python benchmark/scripts/build_resolution_envelope.py
```

Machine-readable artifacts are under
`outputs/kdd_{heldout_confirmatory,heldout_replication_v2,diagnostic_challenge}`
and `outputs/kdd_resolution_envelope`.
