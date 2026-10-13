#!/usr/bin/env python3
"""Build or verify the controlled induced-value mechanism gold suite."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.induced_value_gold import (
    build_induced_value_gold,
    verify_induced_value_gold,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark/outputs/kdd_induced_value_gold"),
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    payload = (
        verify_induced_value_gold(args.output / "manifest.json")
        if args.verify
        else build_induced_value_gold(args.output, args.repository_root)
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
