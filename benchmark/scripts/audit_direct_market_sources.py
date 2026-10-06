#!/usr/bin/env python3
"""Audit candidate direct data-market sources against the admission contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.source_eligibility import (
    audit_source_candidate_catalog,
    write_source_candidate_audit,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = (
    REPOSITORY_ROOT / "benchmark" / "catalog" / "direct_market_source_candidates.yaml"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT
    / "benchmark"
    / "evidence"
    / "direct_market_source_candidate_audit_v1.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    audit = audit_source_candidate_catalog(args.catalog)
    if not audit.valid:
        print(json.dumps(audit.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    output = write_source_candidate_audit(args.catalog, args.output)
    print(
        json.dumps(
            {
                "valid": True,
                "candidate_count": audit.candidate_count,
                "eligible_candidate_count": len(audit.eligible_candidate_ids),
                "ineligible_candidate_count": len(audit.ineligible_candidate_ids),
                "pending_candidate_count": len(audit.pending_candidate_ids),
                "output": output.as_posix(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
