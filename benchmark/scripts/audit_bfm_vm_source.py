#!/usr/bin/env python3
"""Audit a pinned BFM-SWM author-source archive without vendoring it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.bfm_vm_source_audit import (
    PINNED_HEADER_SHA256,
    write_bfm_vm_source_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmark/evidence/bfm_vm_source_audit_v1.json"),
    )
    args = parser.parse_args()
    record = write_bfm_vm_source_audit(
        args.source_archive,
        args.output,
        expected_header_sha256=PINNED_HEADER_SHA256,
    )
    print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
