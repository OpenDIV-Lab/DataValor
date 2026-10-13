# Exact-Shapley external implementation audit

> Audit date: 2026-10-04  
> Scope: finite characteristic games and the `shapley_exact` headline core.

## Independently authored implementation

The comparison executes `ApproxMethods/GroundTruth/ExhaustiveSearch.py` from
the S-SVARM authors' MIT-licensed repository at commit
`c4e30395b14b8bf9a8687d839d5b406f825bb23d`. The file is an exact ground-truth
enumerator used by that project; it is not represented as official Data
Shapley code. The validation record therefore uses origin
`independent_reimplementation`.

The pinned GitHub archive has SHA-256
`72a62cb98ac15816b5185b8c6b3d03d7bd2ee176b468eb80cf251b840aa66f2a`.
The exact enumerator, abstract method base, experiment storage, utility module,
license, fixtures, runner, and outputs are separately hash-bound in
`benchmark/evidence/external_svarm_exact_shapley_v1.json`. All four upstream
Python files execute unchanged; import shims provide only package namespaces
and the abstract game type required by their absolute imports.

## Shared agreement domain

Five hand-derived games cover distinct failure modes:

| Fixture | Players | Structure tested |
|---|---:|---|
| additive-three-owner | 3 | additive recovery and efficiency |
| unanimity-three-owner | 3 | pure three-way complementarity |
| asymmetric-four-owner | 4 | mixed positive/negative interactions and asymmetry |
| negative-marginal-three-owner | 3 | negative scores and substitutability |
| zero-four-owner | 4 | zero-game and dummy behavior |

All have `v(empty)=0`, matching the upstream domain convention. Local and
external vectors agree within tolerance `1e-12`; the observed maximum absolute
difference is `4.440892098500626e-16`. Both implementations are also checked
against fixture oracles, so mutual agreement alone cannot certify a shared
mistake.

## Retained semantic boundary

The upstream enumerator loops over nonempty coalitions and omits the standard
empty-coalition subtraction. Its own lookup-game adapter normalizes the empty
coalition to zero. On a deliberately non-normalized additive game with
`v(empty)=5` and three players, the local definition returns `(1,2,4)` while
the upstream code returns `(1,2,4) + 5/3` componentwise. The observed
difference exactly matches that derivation.

This case is stored under `boundary_comparisons`, not counted among agreement
fixtures. The result supports equivalence only for normalized games; it also
demonstrates that the benchmark's external-validation contract can preserve a
source assumption rather than silently preprocessing it away.

## Native reproduction

```bash
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_shapley_validation.py --build
PYTHONPATH=benchmark/src:src python \
  benchmark/scripts/run_external_shapley_validation.py --verify
```

The path uses Python, NumPy, and SciPy only. No container image, VM image, or
service dependency is part of the comparison.
