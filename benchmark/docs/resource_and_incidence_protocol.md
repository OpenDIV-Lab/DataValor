# Resource frontier and distributive-incidence protocol

The valuation resource frontier compares downstream top-k test utility against
reported coalition-utility calls. Each independent dataset block receives equal weight.
A method is Pareto dominated only when another method is no worse on both axes
and strictly better on at least one; exact ties remain on the frontier. A
missing call counter yields `not_auditable`, not zero cost.

Procurement and trading use a separate track-native resource-vector audit.
Procurement reports utility-oracle calls made during mechanism execution.
Trading reports submitted messages, clearing passes, and realized algorithmic
randomization events. These units are aggregated seed-within-case,
case-within-source-block, then equally across blocks. They are not wall-clock
proxies and are never collapsed into a cross-track resource score.

The incidence analysis uses the controlled induced-value cases and reports, for
each declared provider-size group, selection rate, payment share, and seller
surplus per member. Selection-rate denominators are all sellers in the group.
Payment shares use total seller payment; zero-payment outcomes receive a finite
zero share plus the explicit status `zero_total_payment`. These diagnostics do
not measure protected-class fairness and do not identify deployed-market causal
effects.

```bash
PYTHONPATH=benchmark/src python benchmark/scripts/build_resource_and_incidence.py
PYTHONPATH=benchmark/src python benchmark/scripts/build_resource_and_incidence.py --verify
```
