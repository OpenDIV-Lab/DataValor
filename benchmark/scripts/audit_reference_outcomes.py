#!/usr/bin/env python3
"""Recompute standard reference metrics from persisted mechanism outcomes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.reference_evaluation import write_reference_outcome_audit
from datamechbench.runner import build_cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = write_reference_outcome_audit(
        args.results, args.output, cases=build_cases()
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
