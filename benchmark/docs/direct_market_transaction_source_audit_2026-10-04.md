# Direct data-market transaction and reservation-price source audit

> Audit date: 2026-10-04  
> Scope: candidate evidence that could strengthen DataMechBench beyond public
> listing asks without relabeling a proxy as a data-market transaction.

## Decision

The follow-up benchmark integration now exposes this audit through
`outputs/kdd_market_semantics/`.  That artifact aligns six evidence layers with
the claims they can and cannot support.  In particular, the licensed 78-deal
registry has complete named buyer/seller roles and source URLs, but only 35
rows disclose any financial term, seven are classified as reported deal
amounts, and two of those are high confidence.  Aggregate pricing accounts for
71 rows, per-unit pricing for two, and the top two buyer clusters account for
50% of rows.  These observations strengthen real-market role, pricing-basis,
disclosure, and concentration semantics while leaving the replayable mechanism
outcome count and observed-private-type count at zero.

One newly inspected source is eligible for a deliberately restricted evidence
role: the CC BY 4.0 `midah/ai-data-deals` registry supports a deal-level
pricing-mechanism landscape, payment-disclosure audit and reported-payment
support envelope. It does **not** supply seller reservation costs, buyer values,
standardized mechanism outcomes or row-independent market observations. No
source is therefore eligible to create a new observed private-type or
mechanism-outcome cohort. The current DaDaDa study remains a **listed-price
support transfer**, not a transaction-price or private-cost cohort. CNIL's
aggregate curves are now used separately in
`T-AGGREGATE-TYPE-ENVELOPE`: a model-generated sensitivity setting that keeps
every public anchor fixed and explicitly does not create observed individuals.

The decision is now executable rather than prose-only. The machine-readable
ledger in `catalog/direct_market_source_candidates.yaml` evaluates sixteen sources
against eight conjunctive conditions; the deterministic report in
`evidence/direct_market_source_candidate_audit_v1.json` admits **1/16**, with a
machine-enforced allowed/prohibited-use scope. The admitted source's separate
evidence funnel retains 78 public deals but classifies only 7 as reported deal
amounts and only 2 of those as high-confidence. It also records 71 aggregate,
2 per-unit and 5 unknown pricing mechanisms, 18 buyer clusters, 56 seller
clusters and a 50% top-two-buyer row share. The
audit treats every `unknown` as blocking and rejects a declared `eligible`
status whenever any condition is `not_met` or `unknown`.

The criterion-level audit changes the interpretation of the gap. Eleven of 16
candidates satisfy both institution and price semantics, but only one of those
11 also has reproducible access, explicit reuse rights, and a privacy-safe
release. Across all 16 candidates, price semantics blocks only 2, whereas reuse
rights and privacy safety each block 13 and transformation audit blocks 12.
The bottleneck in this deliberately high-relevance candidate set is therefore
predominantly **releaseability**, not the absence of economically meaningful
experiments. This is a diagnostic of the audited candidate set, not an estimate
of prevalence across the literature. Counts are generated directly in
`evidence/direct_market_source_candidate_audit_v1.json`; `unknown` remains
blocking rather than being converted to `met`.

A follow-up inspection materially narrows the reservation-price gap. The
Alizadeh--Gilardi OSF project does contain two public participant-level CSVs,
with exact repository SHA-256 values recorded in the ledger. It is nevertheless
inadmissible: the OSF node declares no licence; the raw files contain Prolific
and response identifiers, timestamps, demographics and free text; no analysis
code or variable-level codebook is deposited; and the paper's debrief states
that neither the described marketplace nor a price-contingent transfer was
implemented. This is not an absence-of-data result. It is a three-way
reuse/privacy/construct-validity failure that a benchmark must not erase by
locally dropping columns.

Two additional high-value candidates sharpen the boundary. Norwegian Citizen
Panel round 28 exposes an official open-ended personal-data selling-price item
with 1,566 valid responses and randomized framing, but the file must be ordered,
the dataset licence is null, and its use restriction does not authorize
redistribution. Alorwu et al. run the closest institution found in this search:
2,656 consequential bids in reverse second-price auctions for personal health
data. Their paper, however, states explicitly that the authors do not have
permission to share the observations. The first source is accessible only under
an unfit release contract; the second has the right institution but no sharable
data. Neither can become a benchmark cohort by relabeling article tables.

Three further participant-level studies make the exclusion logic more
informative rather than merely increasing the search count. Skatova et al.
publish 261 rows of stated willingness to pay for a privacy-protection service,
but this is not willingness to accept for selling data and the OSF node has no
data licence. Hswen et al. elicit GPS-data compensation through a
Vickrey-auction framing, but withhold the participant data for confidentiality
and privacy. Khavkin and Toch are the closest newly found source: their
validation study has 146 participant-level real disclosure decisions and actual
payments. Yet its mutable private view-only OSF project has no licence, and all
146 inspected rows include a response identifier, exact coordinates, and an
exact street address alongside sensitive disclosure and demographic fields.
It is therefore **mechanism-relevant but release-ineligible**. The raw file was
used only for this field-level audit and is not copied into the repository;
local column deletion cannot repair absent permission or consent scope.

The search exposed three economically different observables that the benchmark
must never merge:

1. a public **listing ask**, which describes an offer but not acceptance;
2. an executed **settlement/payment**, which shows trade but not either party's
   latent value or reservation cost; and
3. an incentive-compatible **elicited reservation price**, which measures a
   participant type under an experimental institution but is not a commercial
   marketplace transaction.

A future source can strengthen one or more of these columns, but it cannot be
used to infer an unobserved column without a separately stated model.

## Eligibility contract

A source enters a new frozen cohort only if all of the following are evidenced:

- the institution actually trades access to data or elicits the value of that
  access;
- seller, buyer, platform, asset/access right, and payment semantics are
  documented;
- the observed amount is classified as ask, bid, settlement, provider revenue,
  fee, or reservation price rather than called generically `price`;
- acquisition is repeatable from a versioned public endpoint or immutable
  deposit;
- redistribution and derivative-analysis rights are explicit;
- personal or commercially identifying fields can be excluded without losing
  the estimand;
- the source supplies enough independent units for a source block and does not
  duplicate a development/held-out block already used for inference; and
- transformation, currency/token normalization, censoring, free trades,
  refunds, self-trades, and missingness can be audited.

Failure on any item keeps the source in the candidate ledger and outside all
leaderboards and confirmatory claims.

## Candidate audit

| Candidate | Observable supported | Primary evidence | Access/licence finding | Current decision |
|---|---|---|---|---|
| `midah/ai-data-deals` | Public AI training/RAG licensing deals, pricing-mechanism labels and reported financial terms | The [Hugging Face dataset](https://huggingface.co/datasets/midah/ai-data-deals/tree/f8ce413790627e25138104d5f23d169430bb8aa6) contains 78 provenance-bearing rows at pinned revision `f8ce413…`; the source Parquet SHA-256 is `4a5f21…bef7` | The data card declares CC BY 4.0. The minimized derivative omits long press quotations, retains source URLs and canonical row hashes, and exposes two malformed modality values rather than silently cleaning them. Only 7/78 rows are classified as reported deal amounts and only 2/78 are high-confidence; 71/78 use aggregate pricing and repeated buyers/sellers make rows dependent | **Eligible only for deal-level evidence.** It supports disclosure, pricing-mechanism and reported-payment-support analysis. The use contract prohibits seller-cost/buyer-value calibration, mechanism ranking and row-iid inference, so it does not create a leaderboard setting |
| Ocean Protocol Polygon fixed-rate orders | Public on-chain base-token settlements coupled to datatoken access orders | Ocean's [`FixedRateExchange`](https://github.com/oceanprotocol/contracts/blob/main/contracts/pools/fixedRate/FixedRateExchange.sol) defines `Swapped` and shows that the emitted `baseTokenSwappedAmount` is the gross buyer pull, already including the three reported swap fees. [`ERC20Template4`](https://github.com/oceanprotocol/contracts/blob/main/contracts/templates/ERC20Template4.sol) defines `OrderStarted` and the atomic buy-and-order path | A fixed Blockscout scan found 316 swaps. Of these, 220 shared a transaction with `OrderStarted`; requiring an `ExchangeCreated` join, buy direction, and the same datatoken order emitter left 198 settlements over 56 assets. Partitioned scans reproduced the same 316-event swap set. However, neither the current Blockscout terms nor the Polygon interface terms provide an explicit licence for derivative analysis and redistribution of these API outputs; an API-schema or contract-code licence is not a data-output licence. Two assets also contribute 142/198 events, so transaction rows are not independent units | **Technically acquired, still ineligible.** Retain the machine-readable negative audit in `evidence/ocean_settlement_source_audit_v1.json`; do not publish raw addresses/transactions, construct a cohort, or support a paper claim until rights and an asset-level inference contract are explicit |
| Wu (2025), *Secondary Market Monetization and Willingness to Share Personal Data* | Consequential multiple-price-list minimum acceptable compensation for releasing personally identifiable psychometric data | The [Management Science article](https://pubsonline.informs.org/doi/10.1287/mnsc.2022.03423) documents the institution, 1,188 participant clusters and the price grid, and links official data files | The journal's [Code and Data Disclosure Policy](https://pubsonline.informs.org/page/mnsc/code-and-data-disclosure-policy) restricts downloaded packages to verifying the source paper and requires author permission for other research use. Thus retrieval alone cannot authorize a benchmark cohort; de-identification and consent scope also remain unaudited | **Ineligible without author permission.** This is the strongest reservation-type candidate, but the previous “retrieve and inspect” action is insufficient: obtain a written reuse grant or a separately licensed deposit before accessing participant rows for DataMechBench |
| AWS Data Exchange | Subscription activity, subscriber payments, disbursements and refunds from an operational data marketplace | AWS documents [provider financial reports](https://docs.aws.amazon.com/data-exchange/latest/userguide/provider-financials.html) containing subscription activity, payments and disbursements | Reports are delivered to registered providers/sellers; no public, redistributable transaction-level cohort was identified | **Ineligible without provider partnership and release permission.** Public catalog listings remain asks, not settlements |
| Snowflake Marketplace | Purchases, earnings, accumulated charges and monetized usage for paid data listings | Snowflake documents [Provider Studio listing analytics](https://docs.snowflake.com/en/collaboration/provider-listings-monitor-studio) and the [`MONETIZED_USAGE_DAILY`](https://docs.snowflake.com/en/collaboration/views/monetized-usage-daily-org) view | Purchase and payment information requires provider/account privileges and contains consumer/account details; no public redistributable extract was identified | **Ineligible without a consenting provider and privacy-preserving release.** A provider aggregate could support adoption/usage but not necessarily transaction-level mechanism replay |
| Zhang and Beltrán (2022), simulated private-data marketplace experiment | Experimental monetary cost of selling private data under privacy/type/volume treatments | The [SSRN record](https://doi.org/10.2139/ssrn.4053024) describes the laboratory market | The record states all rights reserved and no reusable raw-data deposit was identified | **Literature evidence only.** Do not copy numeric observations or imply dataset access |
| Alizadeh and Gilardi (2025), X-data marketplace survey experiments | BDM-framed but non-consequential stated minimum prices and participation under marketplace/donation/one-time-purchase prompts | [arXiv:2506.16618](https://arxiv.org/abs/2506.16618) links the public [OSF project](https://osf.io/c6uj8/). OSF exposes two 43-column CSVs at SHA-256 `6e6c69…b4645` and `5a3c7d…d1597`; the paper debrief says no marketplace existed and no data transfer was requested | The OSF node has no licence. Both files contain Prolific ID, ResponseId, timestamps, demographics and free text; their 1,280/1,239 rows do not directly match the stated 1,250/1,250 analysis Ns, and no analysis code or variable-level codebook is deposited | **Reproducibly accessible but inadmissible.** Public download is not reuse permission; deleting identifiers locally cannot establish consent or redistribution rights. Require an author-licensed minimized extract, codebook and exclusion/deduplication rules, and retain the observable as stated rather than incentive-compatible reservation price |
| CNIL (2025) personal-data monetisation survey | Stated monthly compensation bands and a never-sell mass from a representative sample of 2,082 French residents | The [official CNIL report](https://www.cnil.fr/en/monetisation-personal-data-how-much-our-data-worth) reports six supply and six demand acceptance anchors plus 35% unwilling to sell at any price | Only aggregate percentages are published. CNIL site text is CC-BY-ND 4.0 FR, while no respondent-level Open Licence deposit, codebook, survey weights or missingness record was located | **Aggregate-compatible sensitivity only.** `T-AGGREGATE-TYPE-ENVELOPE` evaluates nine declared within-bin placements while preserving every public anchor. It does not expand bins into observed people, call stated answers reservation costs, or support population inference; request a separately licensed microdata release before cohort construction |
| Agahari and de Reuver (2022), TU Delft MPC data-marketplace experiment | Perceived control, risk, privacy, trust and willingness to share under three marketplace mockups | [4TU.ResearchData DOI 10.4121/19403534.v1](https://doi.org/10.4121/19403534.v1) provides CC BY 4.0 files, hashes and a reuse-oriented README | The variables are perception and willingness-to-share scales, not asks, bids, payments or monetary reservation types; the mockups execute no sale | **Licensed but economically ineligible.** It can inform institutional-acceptance research, not price or seller-cost calibration; no numeric remapping from Likert responses is permitted |
| Friehe, Gerhards, and Weber (2025), *Keep them out of It!* | Consequential BDM minimum acceptable price for selling personal WTP information under peer-data compromise probabilities | The [Journal of Economic Psychology article](https://doi.org/10.1016/j.joep.2025.102830) documents a EUR 0--6 grid, censoring above EUR 6, six cells and 596 participants | The accessible supplement is an online appendix; no reusable machine-readable raw-data deposit or dataset-specific licence was identified | **High-value candidate, currently ineligible.** Obtain a licensed participant-pair extract and retain above-cap non-sale as censoring rather than assigning a numeric cost |
| Norwegian Citizen Panel round 28 | Individual open-ended stated price for selling personal data, plus randomized revenue-anchor and sensitive-data framing | The [official dataset DOI](https://doi.org/10.18712/NSD-NSD3189-V2) and codebook document `r28_dmwtpx1` with 1,566 valid responses in a 10,242-case probability-recruited panel | Sikt metadata says the file is available when ordered for research/teaching/student use, returns no dataset licence, and the anonymous open-data job rejects the DOI | **Semantically useful, release-ineligible.** Do not bundle ordered data or derived rows without written redistribution rights; if permission is obtained, retain framing cells, weights and open-ended outlier rules and label the values as stated rather than incentive-compatible types |
| Alorwu et al. (2024), personal health-data auctions | 2,656 repeated bids to sell sleep and pain data to academic, government and for-profit buyer labels | The [open article](https://doi.org/10.1016/j.ijhcs.2024.103241) documents 55 participants, four data types, three buyer identities, opt-out and consequential reverse second-price auctions | The paper's Data availability statement says the authors do not have permission to share data; article CC BY does not license the underlying observations | **Institutionally strongest, still ineligible.** Article tables cannot reconstruct participant-day bids. A source-authorized, minimized longitudinal extract is required, with participant as the dependence unit |
| Skatova et al. (2023), personal-data protection valuation | Stated willingness to pay to prevent sharing of eight personal-data types across five elicitation conditions | The [PLOS ONE article](https://doi.org/10.1371/journal.pone.0284581) links OSF project `s35ur`; its 261-row `data040822.csv` is hash-pinned in the ledger | The OSF node has no data licence. More importantly, payment for a privacy-protection service is not compensation for disclosure, seller cost, buyer value, or a data transaction | **Economically and legally ineligible.** It may motivate a separate privacy-demand study, but sign-reversing WTP cannot construct a seller reservation type |
| Hswen et al. (2022), GPS-data Vickrey valuation | Monetary compensation bids from survey respondents who first declined to provide smartphone GPS data | The [Humanities and Social Sciences Communications article](https://doi.org/10.1057/s41599-022-01338-7) documents the Vickrey-auction framing and bid subset | The data-availability statement withholds the datasets for confidentiality and privacy and provides no open data licence or immutable deposit | **Semantically relevant, release-ineligible.** Aggregate article values cannot become participant types; require an author-licensed minimized extract and explicit payment/transfer semantics |
| Khavkin and Toch (2025), differential-privacy disclosure experiments | Conjoint WTA choices plus a separate 146-participant validation study with real disclosure decisions and actual payments | The [Decision Support Systems article](https://doi.org/10.1016/j.dss.2025.114474) separates the 588-participant simulated conjoint and 146-participant consequential validation; the inspected validation file's hash and field audit are frozen in the ledger | OSF project `tebgn` is private, mutable and view-only, with no licence. Each of 146 rows contains `ResponseId`, exact longitude/latitude and exact street address; sensitive salary, diabetes, attitudes, and demographics are also present | **Closest new mechanism source, but decisively ineligible.** Never redistribute or locally “sanitize” the raw file. Request an author-produced, explicitly licensed minimized extract, codebook, payment-realization mapping, and analysis code; keep conjoint and validation studies separate |
| DaDaDa frozen snapshot | Public data-product listing asks across marketplaces and price modes | Existing pinned source receipt and eight anonymous cohorts in `benchmark/data/market_calibration/` | Apache-2.0-licensed source snapshot is already hash-bound; transaction, discount, buyer value and reservation cost are explicitly absent | **Retain as listing support only.** It remains useful for support/scale stress and cannot close the settlement or latent-type gap |

## Why the restricted positive result matters

The access pattern is itself consequential for benchmark design. Centralized
commercial marketplaces observe the cleanest purchases and disbursements but
expose them only inside seller accounts. Decentralized markets can expose
settlement on public ledgers, yet reproducibility depends on durable indexing,
asset metadata and token semantics. Laboratory markets can elicit reservation
prices under controlled incentives, but human-subject privacy and reuse rights
constrain redistribution.

Consequently, “realism” cannot be a single badge. DataMechBench should keep its
four-dimensional source cards and add a source only for the dimension it
actually observes. In particular:

- a settlement cohort can validate payment-scale and participation stress, but
  not truthful private costs;
- an elicited-reservation cohort can calibrate seller types, but not commercial
  demand or platform equilibrium; and
- a listing cohort can validate support and product heterogeneity, but not
  acceptance or welfare.

The licensed deal registry adds a fourth case: a public contract registry can
establish that data rights are purchased and can expose pricing-basis opacity,
yet it still cannot be transported into participant-level types. Its disclosure
funnel is a construct-validity result: “public deal” (78 rows), “some financial
wording” (35 rows), “reported deal amount” (7 rows), and “high-confidence
reported amount” (2 rows) are different evidence levels. Collapsing them would
turn estimates, revenue proxies, royalty shares and offers into fictitious
transactions. Likewise, 39/78 rows belong to the two most frequent buyer labels,
so ordinary row-level confidence intervals would manufacture sample size.

This separation preserves the paper's main claim-aligned principle: empirical
evidence is attached to the mechanism claim it can identify, not promoted to a
stronger claim because it came from a real platform.

## Executable next actions

The Wu reservation-type candidate is also evaluated by the machine-checkable
external-asset gate in `outputs/kdd_external_asset_gate/`. Its consequential
BDM semantics pass, but reuse rights, privacy-safe field review, and a frozen
transformation audit do not. All three must change to `met` before the cohort is
eligible; access to a downloadable file alone cannot promote it.

1. Keep the licensed registry's snapshot, classifier and use contract in the
   release, but use it only for deal-level disclosure/structure evidence. Do not
   normalize heterogeneous contract totals into a seller-type distribution.
2. Request written research-reuse permission for the Wu package; a successful
   download under the journal's replication-only terms is not sufficient.
   Separately ask the Alizadeh--Gilardi authors for a versioned, explicitly
   licensed, identifier-free extract plus codebook and analysis-population
   rules. Do not redistribute the current OSF CSVs.
3. Obtain written permission or an explicit data-output licence for the Ocean
   event extract, then freeze an immutable event-set deposit. Use asset/exchange,
   not transaction, as the independent unit; keep token contracts as separate
   cohorts and never add `Swapped` fee fields to `baseTokenSwappedAmount` again.
4. Seek one AWS Data Exchange or Snowflake provider willing to release a
   k-anonymized, licence-cleared aggregate containing listing identifier,
   charge mode, transaction/usage date, gross charge and refund flag. Provider
   revenue must remain distinct from buyer payment when fees apply.
5. Retain the CNIL aggregate-envelope study as model sensitivity rather than
   an empirical cohort. Ask CNIL for a versioned, licensed anonymized survey
   extract and ask the
   Friehe--Gerhards--Weber authors for a licensed participant-pair extract. For
   both, require the original codebook, censoring/nonparticipation flags,
   weights or pair identifiers, exclusions and consent scope.
6. For Norwegian Citizen Panel round 28, request explicit redistribution and
   derivative-benchmark permission before ordering the microdata. For the
   Alorwu health-data auctions, a new participant-consent-compatible release is
   required; the article's own no-permission statement rules out informal file
   transfer as a release path.
7. Ask Khavkin and Toch for an author-produced, licence-cleared validation
   extract that excludes direct and quasi-identifying location fields, carries
   a payment-realization map and codebook, and is explicitly covered by consent.
   Do not redistribute the current view-only file or mix its consequential
   validation rows with the simulated conjoint. Skatova et al. can only support
   a distinct privacy-protection WTP construct even if permission is obtained;
   Hswen et al. require both permission and a documented minimization review.
8. If none succeeds before submission, retain the restricted/negative audit, keep all
   “proxy-calibrated” and “listed-price support” wording, and do not claim real
   data-market equilibrium or private reservation values.
