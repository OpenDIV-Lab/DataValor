# Prospective selection and independent-validity protocol

Prospective selection freezes three policy families using only v1: raw mean
performance, guardrail-qualified mean performance, and guardrail-qualified
worst-block performance. It preserves exact ties and applies every frozen
selection to v2. Qualification requires budget feasibility and seller IR for
procurement, and participant IR plus weak budget balance for trading. A
qualification loss is reported directly; constraint-aware and robust policies
do not assign it a favorable numerical regret. The v1 and v2 waves are never
pooled for confirmatory inference. The separate source-hierarchy audit decides
whether the transfer is temporal, cross-dataset, or cross-institution; v2
membership alone never makes a block source-disjoint.

The independent-validity inventory keeps three notions separate: local
paper/official-output parity, comparisons against independently sourced
implementations, and diversity of held-out data sources. It deduplicates source
URIs, rejects duplicate external validation IDs, and publishes every uncovered
method and track. Passing this audit means the disclosure is structurally sound;
it does not mean every mechanism has external implementation coverage.

```bash
PYTHONPATH=benchmark/src python benchmark/scripts/build_independent_validity.py
PYTHONPATH=benchmark/src python benchmark/scripts/build_independent_validity.py --verify
```
