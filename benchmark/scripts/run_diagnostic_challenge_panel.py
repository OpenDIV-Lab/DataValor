#!/usr/bin/env python3
"""Build or verify the registered P/T theory-boundary challenge panel."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.challenge_panel import build_challenge_panel, verify_challenge_panel


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument(
        "--protocol",
        type=Path,
        default=Path("benchmark/catalog/diagnostic_challenge_panel.yaml"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark/outputs/kdd_diagnostic_challenge"),
    )
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    payload = (
        verify_challenge_panel(args.output / "manifest.json")
        if args.verify
        else build_challenge_panel(
            args.output,
            repository_root=args.repository_root,
            protocol_path=args.protocol,
        )
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
