# Benchmark metrology protocol

DataMechBench validates its evaluator as a measurement instrument rather than
assuming that deterministic execution implies valid measurement.

The method-complete mutation panel covers all 17 frozen headline mechanisms.
Each of the six valuation methods receives score perturbation and stored-metric
tampering. Each of the six procurement and five trading methods receives
allocation deletion, payment perturbation, an unknown allocation actor, and
stored-metric tampering. Every method also receives runtime-only and canonical
JSON-mapping reordering controls. The resulting matrix contains 56 scientific
corruptions and 34 benign controls. Missing methods, inapplicable outcome
shapes, missed corruptions, false alarms, and incomplete per-track operator
coverage all fail closed.

Verification checks both hashes and matrix semantics. The CSV must contain
exactly one row for every declared method/operator cell, each expectation must
agree with its operator class and audit result, and recomputed totals must
match `summary.json`. Updating a manifest hash therefore cannot legitimize a
truncated or internally inconsistent matrix.

The compact probe uses one controlled supported case per track and retains the
market oracles needed for evaluator recomputation. Therefore its sensitivity
and specificity describe only this declared 90-cell matrix. They are not
general software-security, implementation-correctness, theorem, or population
guarantees.

The reliability analysis treats registered evidence blocks—not seeds or rows—as
the sampling units. It combines the separately frozen v1 and v2 waves only for
descriptive subset stability. It enumerates block subsets, preserves ties, and
reports exact winner-set recovery, winner-set Jaccard overlap, and Kendall rank
agreement. It does not pool confirmatory intervals or revise either wave's
registered decision.

```bash
PYTHONPATH=benchmark/src python benchmark/scripts/build_benchmark_metrology.py
PYTHONPATH=benchmark/src python benchmark/scripts/build_benchmark_metrology.py --verify
```
