"""Repository path discovery shared by every UI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"


def prepare_import_paths() -> tuple[Path, Path]:
    """Expose repository and src packages without depending on the process cwd."""
    for path in (REPOSITORY_ROOT, SOURCE_ROOT):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)
    return REPOSITORY_ROOT, SOURCE_ROOT
