#!/usr/bin/env python3
"""Build or verify the OpenDataVal KNN-Shapley cross-implementation record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.external_knn_validation import (
    DEFAULT_FIXTURES,
    DEFAULT_LICENSE,
    DEFAULT_OUTPUT_DIRECTORY,
    DEFAULT_SOURCE,
    REPOSITORY_ROOT,
    build_opendataval_knn_validation,
)
from datamechbench.external_validation import audit_external_implementation_records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--license", type=Path, default=DEFAULT_LICENSE)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    args = parser.parse_args()
    record = args.output / "external_opendataval_knn_shapley_v1.json"
    if args.build:
        result = build_opendataval_knn_validation(
            source_path=args.source,
            license_path=args.license,
            fixture_path=args.fixtures,
            runner_path=Path(__file__),
            output_directory=args.output,
            repository_root=args.repository_root,
        )
        payload = {
            "built": True,
            "record": str(record),
            "fixture_count": result["fixture_count"],
            "maximum_absolute_error": result["maximum_absolute_error"],
            "all_close": result["all_close"],
        }
        status = 0 if result["all_close"] else 1
    else:
        audit = audit_external_implementation_records(
            (record.relative_to(args.repository_root).as_posix(),),
            args.repository_root,
            expected_method_ids={"knn_shapley"},
            minimum_records=1,
            minimum_fixtures=3,
        )
        payload = {"built": False, **audit}
        status = 0 if audit["passed"] else 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
