#!/usr/bin/env python3
"""Audit the licensed AI data-deal snapshot under its restricted use contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.data_deal_evidence import (
    audit_data_deal_snapshot,
    write_data_deal_evidence_report,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = (
    REPOSITORY_ROOT
    / "benchmark"
    / "data"
    / "external"
    / "ai_data_deals_cc_by_4"
    / "snapshot.json"
)
DEFAULT_OUTPUT = (
    REPOSITORY_ROOT / "benchmark" / "evidence" / "ai_data_deal_evidence_v1.json"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    audit = audit_data_deal_snapshot(args.snapshot)
    if not audit.valid:
        print(json.dumps(audit.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 1
    output = write_data_deal_evidence_report(args.snapshot, args.output)
    print(
        json.dumps(
            {
                "valid": True,
                "row_count": audit.row_count,
                "reported_deal_amount_count": audit.reported_deal_amount_count,
                "high_confidence_reported_deal_amount_count": (
                    audit.high_confidence_reported_deal_amount_count
                ),
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
