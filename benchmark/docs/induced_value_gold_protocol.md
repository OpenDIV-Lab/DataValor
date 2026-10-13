# Controlled induced-value gold protocol

This suite supplies complete evaluator-known costs and values for six
procurement and five two-sided-trading headline mechanism families. Every run
persists allocation and payment outcomes, so welfare, individual rationality,
budget balance, and group incidence can be replayed without rerunning a
mechanism.

The evidence scope is `controlled_induced_value`. Types are assigned by the
protocol and are direct inputs to the finite mechanism problem. They are not
observed preferences, bids from a deployed data market, human-subject evidence,
or estimates of a population distribution. Consequently, this suite does not
change the six-layer real-market audit: that audit continues to report no
observed private-type or deployed mechanism-outcome layer.

Run and verify:

```bash
PYTHONPATH=benchmark/src python benchmark/scripts/run_induced_value_gold.py
PYTHONPATH=benchmark/src python benchmark/scripts/run_induced_value_gold.py --verify
```

`cases.json` binds every induced type and provider-size group;
`raw_results.jsonl` stores schema-1.2 outcomes; `method_profiles.csv` reports
track-specific primary performance; and `semantic_receipt.json` states the
allowed and forbidden interpretations.
