#!/usr/bin/env python3
"""Build the non-substitutable real-market semantic alignment artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.market_semantics import DEFAULT_OUTPUT, write_market_semantic_artifacts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = write_market_semantic_artifacts(args.output)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "valid": payload["valid"],
                "layer_count": payload["layer_count"],
                "output": str(args.output),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
