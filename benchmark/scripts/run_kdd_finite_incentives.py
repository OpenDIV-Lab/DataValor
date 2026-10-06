#!/usr/bin/env python3
"""Run the frozen KDD finite-domain incentive audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.finite_incentives import (
    DEFAULT_CONFIG,
    DEFAULT_EVIDENCE,
    DEFAULT_OUTPUT_DIR,
    load_finite_incentive_config,
    run_finite_incentive_audit,
    verify_finite_incentive_artifacts,
    write_finite_incentive_artifacts,
)
from datamechbench.runner import build_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    config = load_finite_incentive_config(args.config)
    result = run_finite_incentive_audit(config, build_registry())
    manifest = write_finite_incentive_artifacts(result, args.output_dir, args.evidence)
    verification = verify_finite_incentive_artifacts(args.evidence)
    if not verification["valid"]:
        raise SystemExit("finite incentive artifact verification failed")
    print(
        json.dumps(
            {
                "method_count": manifest["method_count"],
                "scientific_digest": manifest["scientific_digest"],
                "evidence": args.evidence.as_posix(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
