#!/usr/bin/env python3
"""Build or verify the KDD decision-impact artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.decision_impact import (
    DEFAULT_INPUTS,
    DEFAULT_OUTPUT_DIR,
    REPOSITORY_ROOT,
    build_decision_impact,
    verify_decision_impact_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument(
        "--confirmatory-contrasts",
        type=Path,
        default=DEFAULT_INPUTS["confirmatory_contrasts"],
    )
    parser.add_argument(
        "--constraint-profiles",
        type=Path,
        default=DEFAULT_INPUTS["constraint_profiles"],
    )
    parser.add_argument(
        "--finite-incentives",
        type=Path,
        default=DEFAULT_INPUTS["finite_incentives"],
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    args = parser.parse_args()
    if args.build:
        manifest = build_decision_impact(
            {
                "confirmatory_contrasts": args.confirmatory_contrasts,
                "constraint_profiles": args.constraint_profiles,
                "finite_incentives": args.finite_incentives,
            },
            args.output_dir,
            repository_root=args.repository_root,
        )
        payload = {
            "built": True,
            "output_dir": args.output_dir.as_posix(),
            "row_counts": manifest["row_counts"],
        }
    else:
        payload = {
            "built": False,
            **verify_decision_impact_manifest(args.output_dir / "manifest.json"),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if args.build or payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
