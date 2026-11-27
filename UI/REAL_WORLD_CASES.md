# Source-grounded applications

The workbench ships four applications that connect a real data source to a concrete data procurement decision. They do not claim to reproduce observed market prices. Source records and derived features are identified in each product's provenance; budgets, reserves, service levels, and behavioral parameters remain editable assumptions.

## 1. NYC mobility demand data procurement

**Decision.** A fleet-planning team chooses a bundle that can improve hourly zone-demand forecasts over its history-only baseline and can be delivered with auditable updates and zone mappings.

| Element | Included in the application |
| --- | --- |
| Source data | Twelve 2024 Yellow Taxi trip records and eight TLC taxi-zone lookup records |
| Derived product | Trip duration, speed, unit-fare, and zone-demand features computed from the trip records |
| Participants | Fleet-planning buyer; raw-trip provider; geographic-reference provider; feature-curation seller |
| Demand | Lower forecast WMAPE, better peak recall, stable zone coverage, usable delivery cadence |
| Quality dimensions | Required-field completeness, valid-trip ratio, zone coverage, outlier rate, freshness |
| Valuation and pricing | Counterfactual task gain followed by subscription pricing |
| Market decision | Bundle matching across complementary trip, zone, and feature products |

The operational sequence is rights screening → schema and trip validation → zone/quality assessment → incremental forecast-value estimation → subscription quote → bundle selection → post-use forecast review.

Sources: [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page), [2024 Yellow Taxi Trip Data](https://data.cityofnewyork.us/d/rwwi-khbc), and [Taxi Zone Lookup](https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv). TLC documents that trip records contain pickup/drop-off time and location, distance, fares, payment type, and passenger counts, and also states that records are supplied by technology providers without a completeness warranty. Provenance and quality checks are therefore part of the procurement process rather than decorative metadata.

## 2. PJM hourly-load data subscription

**Decision.** A day-ahead load desk selects data services that improve load forecasts and peak/ramp detection while controlling update-delay and delivery risk.

| Element | Included in the application |
| --- | --- |
| Source data | Twelve observed hourly PJM demand values obtained from the EIA API |
| Derived products | Hourly ramp/peak features and three-hour rolling update windows |
| Participants | Day-ahead buyer; public-feed integrator; grid-feature vendor; continuous-update vendor |
| Demand | Lower MAPE and imbalance exposure, higher peak capture, continuous delivery |
| Quality dimensions | Timestamp continuity, unit consistency, numerical validity, peak coverage, delivery reliability |
| Valuation and pricing | Discounted update-stream value followed by expected-revenue pricing |
| Market decision | Quality-aware procurement under a fixed acquisition budget |

The operational sequence is redistribution-right review → timestamp and unit checks → peak/ramp coverage → update-stream valuation → price comparison → quality-cost procurement → SLA monitoring.

Sources: [EIA Open Data API](https://www.eia.gov/opendata/v1/) and [PJM Data Miner](https://www.pjm.com/markets-and-operations/etools/data-miner-2). EIA exposes actual and forecast demand, generation, and interchange at hourly resolution. PJM provides operational feeds and an API subject to its access and redistribution terms, so the case models the value of integration, derived features, continuity, and service guarantees—not the resale of a nominally free number.

## 3. Clinical real-world-evidence data licensing

**Decision.** A drug-safety study team selects a versioned admissions/diagnosis/laboratory combination that is fit for its protocol and whose permitted use can be audited before database lock.

| Element | Included in the application |
| --- | --- |
| Source data | Official de-identified records from MIMIC-IV Demo 2.2 admissions, diagnoses, and laboratory tables |
| Participants | RWE study buyer; EHR-license provider; coding service; laboratory-data provider |
| Demand | Cohort coverage, key-element completeness, cross-table linkage, temporal validity, rights fit |
| Quality dimensions | Missingness, schema consistency, linkage rate, event timing, unit/flag validity |
| Valuation and pricing | Risk-adjusted task value followed by rights-differentiated pricing |
| Market decision | Multi-attribute matching over price, quality, freshness, reputation, and rights |

The operational sequence is protocol/use review → critical-element profiling → linkage and temporal validation → uncertainty/rights-risk valuation → rights-specific quote → multi-attribute selection → evidence retention.

Sources: [MIMIC-IV Clinical Database Demo 2.2](https://physionet.org/content/mimic-iv-demo/2.2/) and [FDA Real-World Evidence](https://www.fda.gov/science-research/science-and-research-special-topics/real-world-evidence). FDA materials identify EHR, claims, and registry data as common RWD sources and emphasize fit-for-purpose considerations such as relevance, reliability, completeness, timing, validation, and linkage. The included records are de-identified demo records under ODbL 1.0. The scenario's prices are not PhysioNet prices.

## 4. Financial research data procurement

**Decision.** A multi-asset research and risk team procures a point-in-time data bundle for issuer screening, portfolio review, and downside surveillance. A product is useful only if historical runs can be reproduced without later filings, restatements, or observations leaking into an earlier decision date.

| Element | Included in the application |
| --- | --- |
| Source data | AAPL/MSFT assets and revenue facts with SEC filing dates and accession identifiers; daily FRED DFF observations |
| Derived product | An issuer-rate panel built only from filings available on each as-of date, with filing age and balance-sheet/revenue change signals |
| Participants | Buy-side research desk; filing-normalization seller; macro-feed seller; point-in-time factor seller |
| Demand | Reproducible issuer ranking, downside-alert coverage, fast filing availability, revision traceability |
| Quality dimensions | Point-in-time integrity, filing latency, issuer-period coverage, restatement lineage, delivery reliability |
| Valuation and pricing | Counterfactual shadow-research gain followed by subscription pricing |
| Market decision | Bundle matching across complementary fundamentals, macro context, and derived signals |

The operational sequence is access/use review → accession and version retention → issuer-period quality checks → no-look-ahead shadow dataset → incremental research-value estimation → subscription quote and bundle procurement → latency/revision/value monitoring.

Sources: [SEC EDGAR data APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) and [FRED Effective Federal Funds Rate](https://fred.stlouisfed.org/series/DFF). The SEC API exposes JSON XBRL facts and filing metadata without an API key and updates extracted XBRL data as filings are disseminated. FRED supplies the macro observation series. The application prices the normalization, point-in-time processing, integration, and delivery service; it does not imply that access to the underlying public record itself has the scenario price, and it does not provide investment advice.

## Commercial assumptions

All four cases keep commercial terms separate from observations:

- `metadata.provenance.sample_kind` states whether records are official or derived from official records;
- `sources` lists the publisher, dataset, source URL, and terms;
- `assumptions.prices_are_observed` is `false` for every application;
- budget, reserve, subscription, usage, rights-premium, and agent-strategy fields are editable before execution.

The contract shapes follow established data-market patterns rather than asserting vendor-specific quotes. [AWS Data Exchange subscriptions](https://docs.aws.amazon.com/data-exchange/latest/userguide/product-subscriptions.html) combine price, duration, payment schedule, and data subscription agreements, while [Snowflake paid listings](https://docs.snowflake.com/en/user-guide/collaboration/listings/pricing-plans-offers/providers-create-manage-pricing-plans) support flat-fee and usage-based plans. DataValor uses these recognizable structures to evaluate valuation, pricing, and allocation decisions on a reproducible local case.
