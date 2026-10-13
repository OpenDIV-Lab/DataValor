#!/usr/bin/env python3
"""Build the fixed-grid KDD headline resolution sensitivity artifact."""

from __future__ import annotations

import argparse
import json

from datamechbench.resolution_envelope import build_resolution_envelope


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--catalog", default="benchmark/catalog/headline_suite.yaml")
    parser.add_argument(
        "--protocol", default="benchmark/catalog/resolution_sensitivity.yaml"
    )
    parser.add_argument("--output", default="benchmark/outputs/kdd_resolution_envelope")
    parser.add_argument(
        "--v1", default="benchmark/outputs/kdd_heldout_confirmatory/raw_results.jsonl"
    )
    parser.add_argument(
        "--v2", default="benchmark/outputs/kdd_heldout_replication_v2/raw_results.jsonl"
    )
    parser.add_argument(
        "--challenge", default="benchmark/outputs/kdd_diagnostic_challenge/raw_results.jsonl"
    )
    args = parser.parse_args()
    summary = build_resolution_envelope(
        args.output,
        repository_root=args.repository_root,
        catalog_path=args.catalog,
        protocol_path=args.protocol,
        v1_path=args.v1,
        v2_path=args.v2,
        challenge_path=args.challenge,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
