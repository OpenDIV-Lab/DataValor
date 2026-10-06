#!/usr/bin/env python3
"""Build or verify the CNIL aggregate type-envelope study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.aggregate_type_envelope import (
    DEFAULT_CATALOG,
    DEFAULT_OUTPUT,
    build_aggregate_type_artifacts,
    verify_aggregate_type_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.build:
        result = build_aggregate_type_artifacts(args.output, args.catalog)
    else:
        result = verify_aggregate_type_artifacts(args.output / "manifest.json")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
