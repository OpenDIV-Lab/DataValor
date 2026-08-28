"""Atomic, dependency-free file I/O and content hashing helpers."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def canonical_record_hash(records: Iterable[Mapping[str, Any]]) -> tuple[str, int]:
    digest = hashlib.sha256()
    count = 0
    for row in records:
        digest.update(json.dumps(dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
        digest.update(b"\n")
        count += 1
    return digest.hexdigest(), count


def _atomic_write(path: Path, content: str) -> None:
    ensure_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_json(path: str | Path, value: Any) -> None:
    payload = asdict(value) if is_dataclass(value) else value
    _atomic_write(Path(path), json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def write_jsonl(path: str | Path, rows: Iterable[Mapping[str, Any]]) -> None:
    _atomic_write(Path(path), "".join(json.dumps(dict(row), ensure_ascii=False, default=str) + "\n" for row in rows))


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"JSONL row {line_no} is not an object")
            rows.append(value)
    return rows
