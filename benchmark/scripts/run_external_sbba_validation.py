#!/usr/bin/env python3
"""Build or verify the official SBB-to-SBBA specialization record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.external_sbba_validation import (
    DEFAULT_EXTERNAL_DIRECTORY,
    DEFAULT_FIXTURES,
    DEFAULT_OUTPUT_DIRECTORY,
    REPOSITORY_ROOT,
    build_official_sbba_validation,
)
from datamechbench.external_validation import audit_external_implementation_records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--external", type=Path, default=DEFAULT_EXTERNAL_DIRECTORY)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    args = parser.parse_args()
    record = args.output / "external_erelsgl_sbba_v1.json"
    if args.build:
        result = build_official_sbba_validation(
            external_directory=args.external,
            fixture_path=args.fixtures,
            runner_path=Path(__file__),
            output_directory=args.output,
            repository_root=args.repository_root,
        )
        payload = {
            "built": True,
            "record": str(record),
            "fixture_count": result["fixture_count"],
            "boundary_fixture_count": result["boundary_fixture_count"],
            "maximum_absolute_error": result["maximum_absolute_error"],
            "maximum_fixture_oracle_error": result[
                "maximum_fixture_oracle_error"
            ],
            "all_close": result["all_close"],
        }
        status = 0 if result["all_close"] else 1
    else:
        audit = audit_external_implementation_records(
            (record.relative_to(args.repository_root).as_posix(),),
            args.repository_root,
            expected_method_ids={"sbba"},
            minimum_records=1,
            minimum_fixtures=5,
        )
        payload = {"built": False, **audit}
        status = 0 if audit["passed"] else 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
