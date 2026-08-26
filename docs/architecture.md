# DataValor architecture

## 1. Scope

DataValor is an umbrella research toolkit, not a monolithic pipeline. A module may be used alone, but modules should exchange versioned artifacts so that an experiment can be reproduced without importing every optional dependency.

| Stage | Module | Primary question | Candidate output |
|---|---|---|---|
| Value Discovery | DataGov | Is the data governed, authorized, traceable and safe to process? | governance manifest, policy decisions, lineage |
| Value Discovery | DataProf | What is in the data? | schema and statistical profile |
| Value Discovery | DataEval | How good is the data under stated dimensions and tasks? | quality/evaluation vector and evidence |
| Value Discovery | DataValue | What contribution or utility does it have for a user/task/model? | value estimates with uncertainty and explanation |
| Value Circulation | DataMarket | How do suppliers, buyers and platforms interact? | allocation/outcome/strategy traces |
| Value Circulation | DataPrice | What payment or price follows from value, rights and market rules? | prices, payments, revenue and mechanism diagnostics |
| Value Realization | DataQuery | How can authorized users consume and act on the data? | governed query/agent traces and answers |

## 2. Critical semantic boundaries

The following quantities must not be silently collapsed into one score:

```text
profile facts
  -> evaluation metrics
  -> buyer/task-specific utility or contribution
  -> bids and market context
  -> allocation and transaction payment
  -> realized downstream outcome
```

- A profile is descriptive; it is not a quality judgment.
- Quality is multi-dimensional and may be task-conditioned; it is not a monetary value.
- Valuation models utility or contribution; it is not necessarily an observed bid.
- Price/payment is a mechanism outcome and may differ from value.
- Realized value requires downstream evidence and can differ from ex-ante valuation.

## 3. Planned extension contract

Before adding concrete algorithms, each module should agree on four small concepts:

1. `Component`: named, versioned implementation with declared capabilities;
2. `RunContext`: seed, configuration, rights/policy decision and environment metadata;
3. `Artifact`: versioned payload plus lineage, checksums and diagnostics;
4. `Registry`: explicit component discovery without importing heavy optional dependencies eagerly.

External third-party libraries should normally be wrapped behind adapters that translate their native results into DataValor artifacts. The adapter records the external package/version and preserves native details rather than flattening all outputs prematurely. DVMK is a deliberate exception because it is an existing in-scope codebase: selected DVMK source will be ported, attributed, and substantially refactored into native `datavalor.*` modules, with no runtime dependency on `dvmk`.

## 4. Data and output policy

- `data/examples`: tiny synthetic or clearly redistributable inputs only;
- `data/dataflow_data`: small schema fixtures connecting modules;
- `outputs`: generated local results, ignored by default;
- benchmark downloads and user datasets: external cache locations, never committed automatically;
- all commercial data-market examples: explicit rights, consent, retention and resale checks.

## 5. Near-term implementation sequence

1. Freeze common artifact schemas and terminology.
2. Freeze a DVMK source snapshot, then selectively port and refactor evaluation, valuation, pricing, market simulation, and shared research utilities into native DataValor modules.
3. Add OpenDataVal/pyDVL benchmark adapters without making them core dependencies.
4. Select one governance/profile stack and one query stack through thin integrations.
5. Build the Web UI only after CLI/API artifacts are stable.
