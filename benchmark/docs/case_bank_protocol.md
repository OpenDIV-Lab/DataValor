# Independent case-bank protocol

## Purpose

This protocol makes the unit of benchmark evidence explicit. It prevents a parameter sweep, repeated seed, or method-by-case Cartesian product from being reported as independent empirical breadth. It supports the KDD 2027 Datasets & Benchmarks review criteria on benchmark quality, documentation, reproducibility, and quantified evidence for synthetic generators.

Official criteria: <https://kdd2027.kdd.org/datasets-and-benchmarks-track-call-for-papers/>.

The current manifest is `benchmark/evidence/case_bank_development_v1.json`. It is a **development** bank, not held-out evidence.

## Independence rules

- A block is independent only at one declared unit: `base_dataset`, `generator_family`, or `market_source`.
- Cases produced by varying budgets, market sizes, corruption levels, overlap, or random seeds inside one source family remain in the same block.
- Repeated seeds improve uncertainty estimation but never increase the independent-block count.
- A generator family counts once per track even when it produces many settings or cases.
- Every block lists its cases explicitly; aggregate claims such as `independent_blocks: 7` are rejected.
- Every listed case must have at least one completed row with the same track and setting in the hash-bound result file.
- Duplicate cases, missing completed results, setting mismatches, invalid hashes, and malformed blocks fail the affected track closed.

## Frozen development bank

| Track | Independent blocks | Generator families | Evidence composition |
|---|---:|---:|---|
| Valuation | 7 | 3 | Three open datasets under replication stress, the same three datasets under corruption stress, and one analytic axiom-game family |
| Procurement | 4 | 4 | Concentration, additive correlation, weighted coverage, and real-dataset ML acquisition families |
| Trading | 4 | 4 | Thickness/margin, independent double auction, correlated double auction, and bilateral-prior families |

Open-data blocks name the upstream loader, license, and content hash. Controlled generators name the repository source file, repository license, and file hash. The result artifact is independently SHA-256 bound by the manifest.

The counts are intentionally conservative. For example, the 20 market-thickness cases form one generator-family block, and the nine replication cases for each dataset form one base-dataset block.

## Development/held-out firewall

All cases in this manifest were available during benchmark development or inspected in existing reports. They are permanently labeled `development` and must never be relabeled as held-out.

A future held-out bank must:

1. use newly acquired datasets, market sources, or generator families not exposed during method or metric development;
2. freeze a separate manifest, source/license metadata, and hashes before the confirmation run is revealed;
3. keep benchmark maintainers blind to labels or outcomes where feasible, with an external custodian or timestamped release record;
4. run the prespecified primary comparisons without tuning on held-out outcomes; and
5. publish the manifest and raw results after the evaluation policy permits disclosure.

Passing `independent_case_blocks` therefore establishes audited development breadth only. It does not establish real-market representativeness, held-out generalization, external reproduction, or a paper-ready causal claim. Those remain separate fail-closed gates.

## Manifest contract

The validator accepts schema version `1.0` and requires:

- a repository-relative result path and SHA-256 digest;
- one explicit block list for each track;
- block ID, cohort, setting ID, generator family, independence unit, source kind/URI, license identifier, input hash, and explicit case IDs; and
- completed result rows matching each block's track and setting.

Readiness is computed from validated manifests and raw results. No count stored in prose or YAML is trusted as evidence.
