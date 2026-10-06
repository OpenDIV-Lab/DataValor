#!/usr/bin/env python3
"""Build qualification failure and minimum-relaxation diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.qualification_analysis import (
    DEFAULT_JOINT_ADMISSIBILITY,
    DEFAULT_OUTPUT,
    build_qualification_analysis,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--joint-admissibility",
        type=Path,
        default=DEFAULT_JOINT_ADMISSIBILITY,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    summary = build_qualification_analysis(
        args.joint_admissibility, args.output_dir
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
