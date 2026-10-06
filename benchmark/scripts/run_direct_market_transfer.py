#!/usr/bin/env python3
"""Build or verify the direct data-market price-support transfer study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.direct_market_transfer import (
    DEFAULT_CHILE_EVIDENCE,
    DEFAULT_OUTPUT,
    DEFAULT_PROFILES,
    build_direct_market_transfer_artifacts,
    load_frozen_openml_games,
    verify_direct_market_transfer_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify the direct-listing support transfer study."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--build", action="store_true")
    action.add_argument("--verify", action="store_true")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--chile-evidence", type=Path, default=DEFAULT_CHILE_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.build:
        result = {
            "built": True,
            **build_direct_market_transfer_artifacts(
                load_frozen_openml_games(ROOT),
                args.profiles,
                args.chile_evidence,
                args.output,
            ),
        }
    else:
        result = {
            "built": False,
            **verify_direct_market_transfer_artifacts(
                args.output, args.profiles, args.chile_evidence
            ),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
