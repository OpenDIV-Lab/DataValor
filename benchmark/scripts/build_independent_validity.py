#!/usr/bin/env python3
"""Build or verify prospective-selection and independent-validity evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.independent_validity import (
    build_independent_validity,
    verify_independent_validity,
)
from datamechbench.prospective_selection import (
    build_prospective_selection,
    verify_prospective_selection,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument(
        "--catalog", type=Path, default=Path("benchmark/catalog/headline_suite.yaml")
    )
    parser.add_argument(
        "--v1-results", type=Path,
        default=Path("benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"),
    )
    parser.add_argument(
        "--v2-results", type=Path,
        default=Path("benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"),
    )
    parser.add_argument(
        "--prospective-output", type=Path,
        default=Path("benchmark/outputs/kdd_prospective_selection"),
    )
    parser.add_argument(
        "--validity-output", type=Path,
        default=Path("benchmark/outputs/kdd_independent_validity"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        payload = {
            "prospective_selection": verify_prospective_selection(
                args.prospective_output / "manifest.json"
            ),
            "independent_validity": verify_independent_validity(
                args.validity_output / "manifest.json"
            ),
        }
    else:
        payload = {
            "prospective_selection": build_prospective_selection(
                args.prospective_output,
                repository_root=args.repository_root,
                catalog_path=args.catalog,
                v1_results=args.v1_results,
                v2_results=args.v2_results,
            ),
            "independent_validity": build_independent_validity(
                args.validity_output,
                repository_root=args.repository_root,
                catalog_path=args.catalog,
            ),
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(item.get("valid") for item in payload.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
