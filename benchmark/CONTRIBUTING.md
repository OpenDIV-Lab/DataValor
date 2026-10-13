# Contributing to DataMechBench

DataMechBench accepts mechanism adapters, evaluation settings, metrics, source
audits, and reproducibility fixes.  A contribution must state which benchmark
contract it changes and include tests that fail before the change.

## Mechanism contributions

Provide the paper or repository URL, an immutable version/commit when code is
available, the license, the implemented algorithm location, supported setting
types, assumptions, and every deviation from the cited method.  Add the method
to `catalog/mechanisms.yaml` and its source to `catalog/references.yaml`.
Paper-exact and official-adapter labels require a parity fixture or a retained
official output; otherwise use `paper_variant` or `project_implementation`.

## Setting and metric contributions

Document the decision question, construction or data source, redistribution
status, valid scope, expected failure modes, and statistical unit.  Metrics
must define direction, units, applicability, aggregation, and companion
guardrails in `catalog/metrics.yaml`.

## Required checks

Run:

```bash
PYTHONPATH=benchmark/src:src pytest -q benchmark/tests
PYTHONPATH=benchmark/src:src python benchmark/scripts/reproduce_kdd_core.py \
  --verify-only --report /tmp/datamechbench-reproduction.json
```

Do not refresh frozen hashes merely to silence a failure.  Use
`refresh_kdd_manifest.py` only after reviewing the scientific and source diff,
then run the independent verifier above.

## Compatibility and review

Result, submission, case, catalog, and release schemas are versioned.  Breaking
changes require a migration note in `CHANGELOG.md`.  New research-paper
experiments should live outside the benchmark package unless they implement a
general benchmark method, setting, or evaluator.

