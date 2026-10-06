#!/usr/bin/env python3
"""Build or verify the frozen trading support-geometry study."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.trading_geometry import (
    DEFAULT_GEOMETRY_OUTPUT,
    build_geometry_artifacts,
    verify_geometry_artifacts,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_GEOMETRY_OUTPUT)
    args = parser.parse_args()
    if args.build:
        payload = build_geometry_artifacts(args.output)
    else:
        payload = verify_geometry_artifacts(args.output / "manifest.json")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
