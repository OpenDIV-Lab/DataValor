"""Locate immutable runtime assets in a checkout or installed wheel."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _resource_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    configured = os.environ.get("DATAMECHBENCH_RESOURCE_ROOT")
    if configured:
        roots.append(Path(configured).expanduser())
    package_file = Path(__file__).resolve()
    roots.extend(
        (
            package_file.parents[2],
            package_file.parents[1] / "share" / "datamechbench",
            Path(sys.prefix) / "share" / "datamechbench",
        )
    )
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return tuple(unique)


def resource_path(*parts: str) -> Path:
    """Return an existing benchmark asset or fail with searched locations."""

    if not parts or any(not part or Path(part).is_absolute() or ".." in Path(part).parts for part in parts):
        raise ValueError("resource path parts must be non-empty relative names")
    candidates = tuple(root.joinpath(*parts) for root in _resource_roots())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    searched = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"DataMechBench resource {'/'.join(parts)} not found; searched: {searched}")


__all__ = ["resource_path"]
