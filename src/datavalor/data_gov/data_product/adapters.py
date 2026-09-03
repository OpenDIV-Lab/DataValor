"""JSON, JSONL, CSV, Parquet, directory, and iterable adapters."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Iterator

from .base import DataProductMetadata


class _FileAdapter:
    format = "unknown"

    def __init__(self, path: str | Path, *, product_id: str | None = None, schema: dict[str, Any] | None = None):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.product_id = product_id or self.path.stem
        self.schema = schema
        self.metadata = DataProductMetadata(self.product_id, str(self.path), self.format, schema=schema)

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        raise NotImplementedError

    def materialize(self, limit: int | None = None) -> list[dict[str, Any]]:
        return list(self.records(limit=limit))


class JSONLAdapter(_FileAdapter):
    format = "jsonl"

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        count = 0
        with self.path.open("r", encoding="utf-8") as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"JSONL row {line_no} is not an object")
                yield row
                count += 1
                if limit is not None and count >= limit:
                    return


class JSONAdapter(_FileAdapter):
    format = "json"

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        rows = payload.get("records", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise ValueError("JSON data product must contain a list or {'records': list}")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"JSON row {index} is not an object")
            if limit is not None and index >= limit:
                return
            yield row


class CSVAdapter(_FileAdapter):
    format = "csv"

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        with self.path.open("r", encoding="utf-8", newline="") as stream:
            for index, row in enumerate(csv.DictReader(stream)):
                if limit is not None and index >= limit:
                    return
                yield dict(row)


class ParquetAdapter(_FileAdapter):
    format = "parquet"

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise RuntimeError("Reading Parquet requires optional dependency 'pyarrow'") from exc
        for index, row in enumerate(parquet.read_table(self.path).to_pylist()):
            if limit is not None and index >= limit:
                return
            yield row


class IterableAdapter:
    format = "iterable"

    def __init__(self, iterable: Iterable[dict[str, Any]], *, product_id: str = "stream", uri: str = "memory://stream"):
        self._iterable = iterable
        self.metadata = DataProductMetadata(product_id, uri, self.format)

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        for index, row in enumerate(self._iterable):
            if limit is not None and index >= limit:
                return
            if not isinstance(row, dict):
                raise ValueError("Iterable data product yielded a non-object row")
            yield row


class DirectoryAdapter:
    format = "directory"

    def __init__(self, path: str | Path, *, product_id: str | None = None,
                 patterns: tuple[str, ...] = ("*.jsonl", "*.ndjson", "*.csv", "*.json", "*.parquet")):
        self.path = Path(path)
        if not self.path.is_dir():
            raise NotADirectoryError(self.path)
        self.product_id = product_id or self.path.name
        self.paths = sorted({item for pattern in patterns for item in self.path.glob(pattern)})
        self.metadata = DataProductMetadata(self.product_id, str(self.path), self.format)

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]:
        emitted = 0
        for path in self.paths:
            adapter = _adapter_for_path(path, self.product_id)
            remaining = None if limit is None else max(0, limit - emitted)
            for row in adapter.records(limit=remaining):
                yield row
                emitted += 1
                if limit is not None and emitted >= limit:
                    return


def _adapter_for_path(path: Path, product_id: str) -> _FileAdapter:
    classes = {".jsonl": JSONLAdapter, ".ndjson": JSONLAdapter, ".json": JSONAdapter,
               ".csv": CSVAdapter, ".parquet": ParquetAdapter}
    try:
        cls = classes[path.suffix.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported data product format: {path.suffix}") from exc
    return cls(path, product_id=product_id)
