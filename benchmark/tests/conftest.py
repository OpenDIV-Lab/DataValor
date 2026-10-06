from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
for path in (REPO_ROOT / "benchmark" / "src", REPO_ROOT / "src"):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)
