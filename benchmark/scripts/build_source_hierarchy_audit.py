#!/usr/bin/env python3
"""Build the release-bound source hierarchy audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.source_hierarchy import build_source_hierarchy_audit


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", default=".")
    parser.add_argument("--catalog", default="benchmark/catalog/source_hierarchy.yaml")
    parser.add_argument("--manifest", action="append", default=[])
    parser.add_argument("--output", default="benchmark/outputs/kdd_source_hierarchy")
    args = parser.parse_args()
    root = Path(args.repository_root).resolve()
    manifests = args.manifest or [
        "benchmark/evidence/kdd_heldout_confirmatory_v1.json",
        "benchmark/evidence/kdd_heldout_replication_v2.json",
    ]
    summary = build_source_hierarchy_audit(
        root / args.output,
        catalog_path=root / args.catalog,
        manifest_paths=[root / path for path in manifests],
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

