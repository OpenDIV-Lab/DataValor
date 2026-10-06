#!/usr/bin/env python3
"""Fail-closed preflight for the native Python KDD reproduction environment."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

from datamechbench.environment_preflight import audit_python_environment

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPOSITORY_ROOT / "benchmark" / "reproduction" / "requirements-cpu.lock"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    audit = audit_python_environment(
        args.lock,
        args.repository_root,
        python_version=sys.version_info[:3],
        system=platform.system(),
        machine=platform.machine(),
    )
    payload = audit.as_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if audit.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
