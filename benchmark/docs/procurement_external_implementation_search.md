# Procurement external-implementation search audit

> Search date: 2026-10-03  
> Purpose: determine whether a runnable, author-maintained implementation can
> support an external parity record for the procurement track.

## Eligibility rule

An implementation counts as external evidence only when it is publicly
retrievable, independently maintained from DataMechBench, attributable to the
paper authors or an established project, license/source pinned, and executable
on shared fixtures. A paper-exact local translation, a repository search hit,
or a third-party sketch does not satisfy this rule.

## Sources searched

| Work | Primary public artifact | Source-package SHA-256 | Public-code search result |
|---|---|---:|---|
| Singer, *Budget Feasible Mechanisms* (FOCS 2010) | <https://arxiv.org/abs/1002.2334> | `e029ae17f33969698c643b22fad2674fad30bb0deec77afeea1e341e4740eb52` | no repository returned for arXiv ID/title query; no code declaration in the 22,457-byte source package |
| Chen--Gravin--Lu, *On the Approximability of Budget Feasible Mechanisms* (SODA 2011) | <https://arxiv.org/abs/1007.3801> | `eaa31b5eac347e741bb0fb9b11e1900bb41711989ce59bb8ac1f3020b7a1b3aa` | no repository returned for arXiv ID/title query; no code declaration in the 34,067-byte source package |
| Jalaly--Tardos, *Simple and Efficient Budget Feasible Mechanisms* (WINE 2018) | <https://arxiv.org/abs/1703.10681> | `99311ee86fff1affaeee86f8fe894bfcefa1598057965f8f9c093bd969f4b035` | no repository returned for arXiv ID/title query; no substantive code declaration in the 29,996-byte source package |
| Han--Wu--Huang--Cui, *Triple Eagle* (NeurIPS 2023) | <https://papers.neurips.cc/paper_files/paper/2023/hash/6af779991368999ab3da0d366c208fba-Abstract-Conference.html> | official proceedings PDF inspected | Algorithms 1--4 and C++ experiment description are present, but no public implementation or supplementary code was linked or found |
| Cui--Huang--Sun--Xue, *Budget-Feasible Mechanisms for Submodular Welfare Maximization in Procurement Auctions* (ICML 2026) | <https://proceedings.mlr.press/v306/cui26b.html> | author repository commit `82f97be91f4404a9f943c5ebf3d60a272a76a13d`; `BFM-VM.h` SHA-256 `4b3772…c61c` | author experiment code found at <https://github.com/xue74193-dot/BFM-SWM>; identity is pinned, but no licence file exists and the static audit records two paper/code structural discrepancies |

The source packages were searched recursively for repository, GitHub, source
code, software, implementation, simulation, and experiment declarations.
GitHub's public repository API was queried by each arXiv ID and by the work
titles/topic phrase. Visible public author profiles were inspected where an
unambiguous profile could be identified. An incidental LaTeX style comment in
the Jalaly--Tardos bundle was excluded because it is not mechanism code.

## Result and benchmark consequence

No artifact met the complete executable external-evidence eligibility rule.
The BFM-SWM repository newly supplies pinned author-source identity and a static
structure audit, but not licensed redistribution or output parity. Therefore:

- CGL, Jalaly--Tardos, and Triple Eagle are labeled native `paper_exact`, not
  `official_adapter`;
- Singer-derived incomplete cores remain `paper_variant` where already
  documented;
- no procurement parity JSON is added to `benchmark/evidence/`;
- the external parity evidence outside procurement now covers official
  OpenDataVal KNN-Shapley plus two author-maintained trading paths: McAfee and
  the general-position two-category specialization of generalized SBB to SBBA;
- procurement remains a priority for a later author-code release, direct
  author response, or independent clean-room reproduction.

This is a dated, reproducible search boundary rather than a proof that code
does not exist. A later eligible artifact should be pinned by commit, license,
environment, fixtures, observable mapping, and byte-level result hashes before
the benchmark changes its external-validation claim.
## Machine-checkable promotion gate

The dated search record is now consumed by
`scripts/audit_external_assets.py` together with the pinned BFM-SWM source
audit. Promotion to independent executable parity is conjunctive: source
identity, redistribution authorization, all structural paper/code checks, and
output-level agreement must all pass. The current author source establishes
only repository/commit identity. It has no repository licence, fails two
structural checks recorded in `evidence/bfm_vm_source_audit_v1.json`, and has no
executable output-parity receipt. It therefore remains useful negative evidence
and cannot be described as an independent implementation comparison.
