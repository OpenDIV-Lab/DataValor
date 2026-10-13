# DataMechBench governance and ethics contract

This document defines how the public benchmark is versioned, extended,
corrected, and interpreted. It is a release contract rather than evidence that
external publication or independent reproduction has already happened.

## Intended use and claim boundary

DataMechBench compares data-valuation, budget-feasible procurement, and
double-auction mechanisms under explicit economic and statistical settings. It
is intended for mechanism implementation audits, controlled method comparison,
failure analysis, and reproducible benchmark research. Scores summarize the
declared cases, type/report domains, random seeds, estimands, and metrics only.

The benchmark must not be used as an automatic price setter, procurement award
system, worker-compensation rule, or market-access decision system. In
particular, an empirical zero-regret observation is not a DSIC/BIC proof, a
finite-domain counterexample is not automatically a refutation of a theorem,
and a leaderboard rank is not evidence that a mechanism is safe or fair in a
new market. The included economic types are measured or calibrated proxies,
not declarations of any person's intrinsic worth.

## Versions and immutable releases

- Release IDs identify a frozen case bank, protocol, implementation tree, and
  result digest. Published releases are never silently replaced.
- A patch release may correct documentation without changing scientific
  inputs. Any change to cases, mechanisms, metrics, estimands, or result rows
  requires a new scientific release ID and a fresh manifest.
- Every archival release must include the deterministic candidate sidecar,
  reproduction manifest, source/data licences, archive digest, and changelog.
- Superseded releases remain discoverable. Retraction notices explain the
  affected claims and point to the replacement without erasing prior evidence.

## Method submissions and leaderboard updates

Submissions must name the source paper or repository, licence, mechanism family,
implemented variant, fidelity class, assumptions, and unsupported features.
Reference-grade status requires a paper-derived golden case or comparison with
official output; a smoke test is insufficient. Common baselines without a
specific source are accepted only when their conventional definition and role
are documented, and they cannot be presented as a new research method.

Maintainers rerun accepted methods in the frozen environment. Untrusted code is
not executed in the public reporting process without isolation, dependency
review, resource limits, and network denial. Public tables distinguish
reference-grade, faithful variant, and benchmark-native baseline results.
Leaderboard updates are versioned; development results do not unlock held-out
cases, and repeated adaptive submissions may be rate-limited or moved to a new
held-out cohort to reduce contamination.

## Corrections, appeals, and conflicts

An issue should identify the release, method, case, metric, expected behavior,
and minimal evidence. Maintainers publish a triage outcome and, for scientific
changes, a regression test and new release. Mechanism authors may appeal a
fidelity label or interpretation by supplying source-linked evidence. A
maintainer with a direct authorship or competitive conflict does not make the
final fidelity decision alone; the decision record names the evidence reviewed
without requiring disclosure of personal information.

## Licences, provenance, privacy, and security

Each external dataset or implementation must have a recorded source, licence,
content hash, and transformation receipt. The core release contains only data
that its recorded terms permit redistribution. It does not require direct
personal identifiers. New data with people-related attributes require a
documented necessity assessment, minimization, licence/privacy review, and an
analysis of whether subgroup reporting itself could create disclosure risk.

Release archives reject absolute paths, traversal components, links, devices,
duplicate entries, and hash mismatches without extraction. Published archives
are referenced by an archival DOI and byte-level SHA-256, not only by a mutable
branch or release label.

## Economic and fairness risks

Mechanism benchmarks can legitimize harmful payment, exclusion, or bargaining
rules when efficiency is reported without incidence. Each applicable setting
therefore reports feasibility, budget behavior, welfare/utility incidence, and
failure or manipulation evidence alongside aggregate performance. Future
extensions should add subgroup or role-conditional incidence only when the
underlying attributes are meaningful, lawful, adequately supported, and not
privacy-invasive. No composite score may hide a hard constraint violation.

The release additionally carries one machine-readable risk card for each of
the 17 frozen headline mechanisms. Each card names affected roles, plausible
beneficiaries and burdened roles, prohibited deployment uses, and the exact
scope of seven evidence dimensions. `audited_scope` means only that the named
metrics and artifacts cover the stated finite scope. `not_auditable` denotes a
known evidence gap and must never be interpreted as zero risk; `not_applicable`
is reserved for a dimension that the benchmark output itself does not define.
`audited_scope` is likewise not a completeness claim: the generated dimension
audit records applicable/total method rows and every observed missingness reason
per metric. In the frozen release this exposes partial payment-derived coverage
for JT Random-EOM (12/18 runs) and both MUDA variants (3/18 runs), rather than
silently treating absent payments as zero.
Cards do not contain a composite risk/fairness score, winner, safety badge, or
deployment approval. The catalog and derived audit are respectively in
`benchmark/catalog/mechanism_risk_cards.yaml` and
`benchmark/outputs/kdd_mechanism_risks/`.

## External evidence and release authority

The checked-in candidate demonstrates local byte integrity only. The public
release gate passes only after a real public repository URL, archival URL, DOI,
and published archive digest resolve to the declared release. Independent
clean-room reproduction remains a separate gate requiring
truthful records from two non-implementers. Maintainers must not replace either
kind of evidence with self-attestation or placeholder metadata.
