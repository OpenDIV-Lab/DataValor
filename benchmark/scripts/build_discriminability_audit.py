#!/usr/bin/env python3
"""Build discriminability diagnostics for frozen KDD waves."""

from __future__ import annotations

import argparse
import json

from datamechbench.discriminability import build_discriminability_audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--catalog", default="benchmark/catalog/headline_suite.yaml")
    parser.add_argument("--output", default="benchmark/outputs/kdd_discriminability")
    args = parser.parse_args()
    summary = build_discriminability_audit(
        args.output,
        repository_root=args.repository_root,
        catalog_path=args.catalog,
        waves={
            "v1": "benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl",
            "v2": "benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl",
        },
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
