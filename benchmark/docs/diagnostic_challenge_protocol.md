# Diagnostic challenge protocol

The diagnostic challenge panel is a deliberately small companion to the
source-backed held-out panels. Its membership is determined by theoretical
branch, payment, thin-market, tie, and side-asymmetry conditions in
`catalog/diagnostic_challenge_panel.yaml`, not by observed leaderboard output.

The procurement cells use public additive utility and complete single-parameter
costs. The trading cells use complete single-unit bids and asks. Every case is
its own diagnostic block; seeds are repetitions of a stochastic mechanism and
are averaged within the case. The primary metrics are procurement oracle ratio
and trading gain-from-trade ratio, with a fixed 0.01 practical tolerance.

These cases answer whether two mechanisms can be distinguished at a registered
theoretical boundary. They do not estimate prevalence, deployment performance,
or superiority over an institution or population. Their rows must never be
pooled with held-out v1/v2 source blocks. A method that performs well here may
still transfer poorly; a tie here does not prove equivalence.

The generated report discloses both panel-wide pair coverage and case-level
resolution. In v1, the four procurement cases distinguish 14/15 headline
method pairs on at least one registered boundary, and the five trading cases
distinguish 10/10. The procurement threshold-boundary cell separates 14/15
pairs by itself; the strongest trading cells separate 9/10. This does not add
population evidence. It shows that a low-resolution held-out leaderboard need
not mean the implementations are behaviorally equivalent, and supplies a
reproducible diagnostic for choosing future evidence-generating settings.

```bash
PYTHONPATH=benchmark/src:src python benchmark/scripts/run_diagnostic_challenge_panel.py
PYTHONPATH=benchmark/src:src python benchmark/scripts/run_diagnostic_challenge_panel.py --verify
```
