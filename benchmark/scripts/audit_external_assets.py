#!/usr/bin/env python3
"""Build or verify high-value external benchmark asset admission evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.external_asset_gate import (
    build_external_asset_audit,
    verify_external_asset_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate-catalog",
        type=Path,
        default=Path("benchmark/catalog/direct_market_source_candidates.yaml"),
    )
    parser.add_argument(
        "--procurement-source-audit",
        type=Path,
        default=Path("benchmark/evidence/bfm_vm_source_audit_v1.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark/outputs/kdd_external_asset_gate"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    payload = (
        verify_external_asset_audit(args.output / "manifest.json")
        if args.verify
        else build_external_asset_audit(
            args.output,
            candidate_catalog=args.candidate_catalog,
            procurement_source_audit=args.procurement_source_audit,
        )
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
