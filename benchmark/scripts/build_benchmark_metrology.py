#!/usr/bin/env python3
"""Build or verify benchmark mutation and source-block reliability evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.metrology import (
    build_benchmark_metrology,
    verify_benchmark_metrology,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmark/outputs/kdd_metrology")
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument(
        "--v1-results",
        type=Path,
        default=Path("benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"),
    )
    parser.add_argument(
        "--v2-results",
        type=Path,
        default=Path("benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    payload = (
        verify_benchmark_metrology(args.output / "manifest.json")
        if args.verify
        else build_benchmark_metrology(
            args.output,
            repository_root=args.repository_root,
            v1_results=args.v1_results,
            v2_results=args.v2_results,
        )
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
