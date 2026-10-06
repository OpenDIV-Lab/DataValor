#!/usr/bin/env python3
"""Build or verify the KDD headline mechanism risk-card artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.risk_cards import (
    DEFAULT_CATALOG,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TARGET,
    build_mechanism_risk_artifacts,
    verify_mechanism_risk_artifacts,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify non-composite headline mechanism risk cards."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--target", default=str(DEFAULT_TARGET))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--repository-root", default=str(REPOSITORY_ROOT))
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.build:
        result = build_mechanism_risk_artifacts(
            args.catalog,
            args.target,
            args.output_dir,
            repository_root=args.repository_root,
        )
        result = {
            "built": True,
            "card_count": result["card_count"],
            "dimension_row_count": result["dimension_row_count"],
            "manifest": str(Path(args.output_dir) / "manifest.json"),
            "no_cross_method_composite": result["no_cross_method_composite"],
        }
        code = 0
    else:
        result = verify_mechanism_risk_artifacts(
            Path(args.output_dir) / "manifest.json",
            repository_root=args.repository_root,
        )
        result = {"built": False, **result}
        code = 0 if result["valid"] else 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
