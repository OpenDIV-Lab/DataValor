# KDD held-out source cards

These cards document the sources frozen in `kdd_heldout_confirmatory.yaml`. They are evidence inputs, not claims that the source institutions are data markets.

## OpenML/UCI classification blocks

The valuation blocks use immutable OpenML IDs 44 (Spambase), 31 (German Credit), and 1461 (Bank Marketing). OpenML exposes machine-readable descriptions, targets, download locations, and source checksums. The corresponding UCI records provide upstream provenance; UCI's current repository policy assigns CC BY 4.0 to donated datasets.

Primary links:

- <https://www.openml.org/api/v1/json/data/44>
- <https://www.openml.org/api/v1/json/data/31>
- <https://www.openml.org/api/v1/json/data/1461>
- <https://archive.ics.uci.edu/>

Risks and limitations:

- Spambase is a historical, partly personalized email collection and is not a modern general-purpose spam population.
- German Credit contains sensitive socioeconomic attributes and an asymmetric decision cost; it must not be used here to recommend individual credit decisions.
- Bank Marketing records a historical campaign and contains demographic/economic attributes; labels reflect subscription outcomes, not welfare.
- The benchmark measures mechanism response to owner-partitioned prediction utility, not fairness or deployability of these classifiers.

## ChileCompra procurement calibration

The Open Contracting Data Registry describes the official ChileCompra publisher, coverage, formats, known quality limitations, and CC0 dedication. The current protocol uses the registry's immutable 2024 JSONL bulk snapshot. It retains every positive CLP award value whose OCDS release date matches one of three prespecified dates. Process identifiers and organization identities are discarded from processed artifacts.

Revision history: v1 named the registry's 2024 bulk archive. An initial single-stream access check appeared impractical, so v2 tried the official daily list/detail API. That API's rate limit was itself unsuitable for clean-room reproduction. Before any mechanism outcomes were computed, v3 returned to the immutable bulk file using supported parallel HTTP byte ranges. Pre-run validation then found two non-existent metric aliases; v4 changes only those identifiers to registered metrics. A second pre-run validator showed the frozen Jalaly-Tardos transfer methods were blocked by their compatibility declarations; v5 changes only those declarations and explicitly labels the theorem-assumption gap. Finally, a schema-only pass found that the registry snapshot exposes award values/release dates rather than bid values/tender-start dates; v6 freezes the actual OCDS field mapping before inspecting any selected date or running any mechanism. The inspected 2024-03-15 and 2024-04-12 access pilots are excluded from all held-out evidence. Every signed marker remains in `evidence/`, and v6 binds the complete amendment chain.

Primary links:

- <https://data.open-contracting.org/es/publication/144>
- <https://datos-abiertos.chilecompra.cl/descargas/procesos-ocds>
- <https://api.mercadopublico.cl/servicios/v1/publico/ordenesdecompra.json>
- <https://standard.open-contracting.org/latest/en/>

Risks and limitations:

- Observed award values are procurement-spend proxies, not latent supplier costs.
- Currency, lot composition, procurement method, and sector affect comparability; the extractor must retain only internally comparable positive amounts and report coverage.
- The source registry notes that some multi-supplier awards cannot be allocated to individual suppliers.
- Linking these distributions to ML data owners is a cross-domain calibration, not evidence about data sellers' reservation prices.

## Elexon Balancing Mechanism calibration

Elexon Insights publishes historic GB electricity Bid Offer Data through a public REST API. The open-data licence grants worldwide, royalty-free, perpetual, non-exclusive use subject to attribution. The benchmark freezes nine settlement periods and removes BM-unit identities before producing type vectors.

Primary links:

- <https://data.elexon.co.uk/bmrs/api/v1/balancing/bid-offer/all>
- <https://github.com/elexon-data/insights-docs/blob/main/docs/insights_data_platform.md>
- <https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/>

Required attribution: “Contains BMRS data © Elexon Limited copyright and database right 2024.”

Risks and limitations:

- Bid and offer prices are market submissions, not directly observed private values or marginal costs.
- The benchmark discards power quantities, ramping constraints, unit commitment, network constraints, and the original settlement rule.
- The transformation preserves ordering, spread, tail behavior, and concentration only. Results therefore test transfer to empirical economic profiles, not fidelity to electricity-market operation.

## Four realism dimensions

Every block must separately state:

- **data realism:** whether the feature/transaction payload is observed;
- **utility realism:** whether utility is trained/evaluated on an actual task or remains a proxy;
- **participant/type realism:** whether types are observed submissions, calibrated proxies, or synthetic;
- **institutional realism:** how closely the original institution matches a data market.

These dimensions remain separate. The benchmark forbids an arbitrary single realism score.

## Machine-checkable economic-observable contract

Every released held-out block now carries an `economic_observable` record in
the v1 and v2 evidence manifests.  The record names the observed measure, its
benchmark role, the claims it supports, and the claims it explicitly forbids.
The fail-closed evidence auditor recognizes five semantics:

- `task_utility`: a measured downstream-task utility, not a market price;
- `proxy`: an observed quantity used only to calibrate a type-distribution
  shape;
- `listing_ask`: a public asking price, with no implication that it was paid;
- `settlement`: an executed payment or settlement, with no implication that it
  equals a participant's private value; and
- `elicited_reservation`: an incentive-compatible elicited reservation value,
  with no implication that it is an executed market price.

The present confirmatory blocks use only `task_utility` (OpenML) and `proxy`
(ChileCompra and Elexon).  A missing record, an unsupported claim, an omitted
mandatory prohibition, or a claim marked both supported and forbidden makes
the corresponding track fail audit.  In particular, a `listing_ask` cannot
support `transaction_price`, and neither a proxy nor a settlement can support
`reservation_value` or `buyer_value`.  These checks affect evidence
eligibility, not mechanism scores or rankings.

## Exploratory DaDaDa direct-listing support (not held out)

DaDaDa is a 2026 snapshot of 16,147 data products from nine data marketplaces.
It is not part of the frozen v6 confirmatory bank.  DataMechBench uses it only
for an exploratory procurement price-support transfer check.  The source is
pinned at commit `ead4f7f88f22933fcdc3a8bf2f239294a6cb6c3c`; the raw CSV SHA-256
is `da52984717826792ec0f69db83f1eaf831b4c5c127fc15771a0a74153b32469a`.
The raw CSV is a rebuild input, not a release member.  The released derivative
contains only platform, price mode, counts, aggregate statistics, and anonymous
quantiles.

Primary links:

- <https://arxiv.org/abs/2607.08785>
- <https://github.com/ZJU-DIVER/DaDaDa>

The transform first separates subscription, one-off, and usage-based prices;
raw monetary values are never pooled across those semantics.  Within each
platform-by-mode cohort having at least 64 positive explicit prices, it
winsorizes at 2.5/97.5 percent, applies `log1p`, selects eight mid-quantiles,
and divides them by their selected median.  This yields eight descriptive
cohorts from 4,929 eligible positive prices.  The configuration, source receipt,
and anonymous profiles are respectively
`catalog/dadada_market_calibration.yaml`,
`data/market_calibration/dadada_source_receipt.json`, and
`data/market_calibration/dadada_price_profiles.json`.

Risks and limitations:

- Prices are public listed asks, not transactions, negotiated discounts,
  reservation costs, or buyer values.
- Marketplace and price-mode cohorts are descriptive supports, not independent
  samples from a target population; no population interval is reported.
- The normalized quantiles preserve within-cohort support geometry but discard
  currency scale and do not model product quality or contract terms.
- The mechanism study therefore tests sensitivity to direct data-market listing
  support; it does not estimate a deployed data-market equilibrium or replace
  the frozen ChileCompra held-out blocks.

A dated audit of stronger transaction and reservation-price candidates is
available in
[`direct_market_transaction_source_audit_2026-10-04.md`](direct_market_transaction_source_audit_2026-10-04.md).
The Ocean chain scan is additionally frozen as a machine-readable negative
eligibility record in
[`../evidence/ocean_settlement_source_audit_v1.json`](../evidence/ocean_settlement_source_audit_v1.json).
It keeps listing asks, executed settlements, and incentive-compatible elicited
reservation prices as separate observables. No new source passed the complete
access, licence, privacy, and semantic eligibility contract in that audit, so
the frozen DaDaDa interpretation is unchanged.
