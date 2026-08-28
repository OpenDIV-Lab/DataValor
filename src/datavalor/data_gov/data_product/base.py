"""Portable tabular data-product adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol
from urllib.parse import urlparse

from datavalor.core.io import canonical_record_hash


@dataclass(frozen=True)
class DataProductMetadata:
    product_id: str
    uri: str
    format: str
    record_count: int | None = None
    sha256: str | None = None
    fields: tuple[str, ...] = ()
    schema: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataProductAdapter(Protocol):
    metadata: DataProductMetadata

    def records(self, limit: int | None = None) -> Iterator[dict[str, Any]]: ...

    def materialize(self, limit: int | None = None) -> list[dict[str, Any]]:
        return list(self.records(limit=limit))


def adapter_from_uri(uri: str | Path, *, product_id: str | None = None, **kwargs: Any) -> DataProductAdapter:
    value = str(uri)
    if urlparse(value).scheme in {"http", "https", "s3", "gs"}:
        raise ValueError("Remote URI adapters require an explicit DataValor provider")
    path = Path(value)
    if path.is_dir():
        from .adapters import DirectoryAdapter
        return DirectoryAdapter(path, product_id=product_id, **kwargs)
    from .adapters import CSVAdapter, JSONAdapter, JSONLAdapter, ParquetAdapter
    cls = {".jsonl": JSONLAdapter, ".ndjson": JSONLAdapter, ".json": JSONAdapter,
           ".csv": CSVAdapter, ".parquet": ParquetAdapter}.get(path.suffix.lower())
    if cls is None:
        raise ValueError(f"Unsupported data product format: {path.suffix or value!r}")
    return cls(path, product_id=product_id, **kwargs)


__all__ = ["DataProductAdapter", "DataProductMetadata", "adapter_from_uri", "canonical_record_hash"]
