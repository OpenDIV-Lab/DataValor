#!/usr/bin/env python3
"""Build or verify the official McAfee cross-implementation record."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.external_mcafee_validation import (
    DEFAULT_EXTERNAL_DIRECTORY,
    DEFAULT_FIXTURES,
    DEFAULT_OUTPUT_DIRECTORY,
    DEFAULT_TRADE_REDUCTION_FIXTURES,
    REPOSITORY_ROOT,
    build_official_mcafee_validation,
    build_official_trade_reduction_validation,
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
    parser.add_argument(
        "--trade-reduction-fixtures",
        type=Path,
        default=DEFAULT_TRADE_REDUCTION_FIXTURES,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    args = parser.parse_args()
    record = args.output / "external_erelsgl_mcafee_v1.json"
    trade_reduction_record = (
        args.output / "external_erelsgl_trade_reduction_v1.json"
    )
    if args.build:
        mcafee_result = build_official_mcafee_validation(
            external_directory=args.external,
            fixture_path=args.fixtures,
            runner_path=Path(__file__),
            output_directory=args.output,
            repository_root=args.repository_root,
        )
        trade_reduction_result = build_official_trade_reduction_validation(
            external_directory=args.external,
            fixture_path=args.trade_reduction_fixtures,
            runner_path=Path(__file__),
            output_directory=args.output,
            repository_root=args.repository_root,
        )
        payload = {
            "built": True,
            "records": [str(record), str(trade_reduction_record)],
            "mcafee_fixture_count": mcafee_result["fixture_count"],
            "trade_reduction_fixture_count": trade_reduction_result[
                "fixture_count"
            ],
            "maximum_absolute_error": max(
                mcafee_result["maximum_absolute_error"],
                trade_reduction_result["maximum_absolute_error"],
            ),
            "maximum_fixture_oracle_error": max(
                mcafee_result["maximum_fixture_oracle_error"],
                trade_reduction_result["maximum_fixture_oracle_error"],
            ),
            "all_close": (
                mcafee_result["all_close"]
                and trade_reduction_result["all_close"]
            ),
        }
        status = 0 if payload["all_close"] else 1
    else:
        audit = audit_external_implementation_records(
            (
                record.relative_to(args.repository_root).as_posix(),
                trade_reduction_record.relative_to(
                    args.repository_root
                ).as_posix(),
            ),
            args.repository_root,
            expected_method_ids={"mcafee", "trade_reduction"},
            minimum_records=2,
            minimum_fixtures=3,
        )
        payload = {"built": False, **audit}
        status = 0 if audit["passed"] else 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
