#!/usr/bin/env python3
"""Build or verify pinned DaDaDa listing-price calibration profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml
from datamechbench.direct_market_calibration import (
    build_calibration_artifacts,
    verify_calibration_artifacts,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "benchmark" / "catalog" / "dadada_market_calibration.yaml"
DEFAULT_OUTPUT = ROOT / "benchmark" / "data" / "market_calibration"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify direct data-market price profiles."
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--build", action="store_true")
    action.add_argument("--verify", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    protocol = yaml.safe_load(args.catalog.read_text(encoding="utf-8"))
    if args.build:
        if args.input is None:
            raise SystemExit("--input is required with --build")
        result = {
            "built": True,
            **build_calibration_artifacts(args.input, args.output, protocol),
        }
    else:
        result = {
            "built": False,
            **verify_calibration_artifacts(args.output, protocol),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
