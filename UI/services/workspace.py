from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
COLLECTIONS = frozenset({"products", "participants", "runs", "artifacts", "workflows", "batches"})


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for name in COLLECTIONS:
            (self.root / name).mkdir(exist_ok=True)

    @staticmethod
    def validate_id(value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("id must contain only letters, numbers, dot, dash, or underscore")
        return value

    def path(self, collection: str, item_id: str) -> Path:
        self.validate_id(item_id)
        if collection not in COLLECTIONS:
            raise ValueError("unknown workspace collection")
        return self.root / collection / f"{item_id}.json"

    def put(self, collection: str, item_id: str, value: Any) -> None:
        target = self.path(collection, item_id)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def get(self, collection: str, item_id: str) -> Any | None:
        target = self.path(collection, item_id)
        return json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None

    def list(self, collection: str) -> list[Any]:
        directory = self.root / collection
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]

    def delete(self, collection: str, item_id: str) -> bool:
        target = self.path(collection, item_id)
        if not target.is_file():
            return False
        target.unlink()
        return True
