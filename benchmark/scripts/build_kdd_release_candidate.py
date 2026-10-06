#!/usr/bin/env python3
"""Build or verify the deterministic KDD public-release candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from datamechbench.public_release import (
    DEFAULT_ARCHIVE,
    DEFAULT_EXTRA_PATHS,
    DEFAULT_REPRODUCTION_MANIFEST,
    DEFAULT_SIDECAR,
    REPOSITORY_ROOT,
    build_release_candidate,
    verify_release_candidate,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--reproduction-manifest", type=Path, default=DEFAULT_REPRODUCTION_MANIFEST)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--sidecar", type=Path, default=DEFAULT_SIDECAR)
    args = parser.parse_args()
    if args.build:
        result = build_release_candidate(
            args.repository_root,
            args.reproduction_manifest,
            args.archive,
            args.sidecar,
            extra_paths=DEFAULT_EXTRA_PATHS,
        )
        payload = {
            "built": True,
            "archive": args.archive.as_posix(),
            "sidecar": args.sidecar.as_posix(),
            "archive_sha256": result["archive"]["sha256"],
            "entry_count": result["entry_count"],
        }
    else:
        checked = verify_release_candidate(args.sidecar, args.repository_root)
        payload = {"built": False, **checked}
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if args.build or payload["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
