#!/usr/bin/env python3
"""Build or verify resource-frontier and group-incidence evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.distributive_incidence import (
    build_distributive_incidence,
    verify_distributive_incidence,
)
from datamechbench.market_resources import (
    build_market_resource_report,
    verify_market_resource_report,
)
from datamechbench.resource_frontier import (
    build_resource_frontier,
    verify_resource_frontier,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument(
        "--valuation-results",
        type=Path,
        default=Path("benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"),
    )
    parser.add_argument(
        "--gold-results",
        type=Path,
        default=Path("benchmark/outputs/kdd_induced_value_gold/raw_results.jsonl"),
    )
    parser.add_argument(
        "--resource-output",
        type=Path,
        default=Path("benchmark/outputs/kdd_resource_frontier"),
    )
    parser.add_argument(
        "--incidence-output",
        type=Path,
        default=Path("benchmark/outputs/kdd_distributive_incidence"),
    )
    parser.add_argument(
        "--market-resource-output",
        type=Path,
        default=Path("benchmark/outputs/kdd_market_resources"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        payload = {
            "resource_frontier": verify_resource_frontier(
                args.resource_output / "manifest.json"
            ),
            "distributive_incidence": verify_distributive_incidence(
                args.incidence_output / "manifest.json"
            ),
            "market_resources": verify_market_resource_report(
                args.market_resource_output / "manifest.json"
            ),
        }
    else:
        payload = {
            "resource_frontier": build_resource_frontier(
                args.resource_output,
                repository_root=args.repository_root,
                results_path=args.valuation_results,
            ),
            "distributive_incidence": build_distributive_incidence(
                args.incidence_output,
                repository_root=args.repository_root,
                results_path=args.gold_results,
            ),
            "market_resources": build_market_resource_report(
                args.market_resource_output,
                repository_root=args.repository_root,
                results_path=args.valuation_results,
            ),
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(item.get("valid") for item in payload.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
