"""Load a DataValor distribution manifest into a data-product adapter."""

from __future__ import annotations

import json
from pathlib import Path

from datavalor.core.io import canonical_record_hash

from .adapters import _adapter_for_path
from .base import DataProductAdapter, DataProductMetadata


def load_manifest_product(manifest_path: str | Path, source_name: str, *, verify: bool = True) -> DataProductAdapter:
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") not in {"datavalor.distribution/v1", "datavalor.data_product/v1"}:
        raise ValueError(f"Unsupported manifest schema: {payload.get('schema_version')!r}")
    source = payload.get("sources", {}).get(source_name)
    if source is None:
        raise KeyError(f"Unknown manifest source {source_name!r}")
    source_path = Path(source["path"])
    if not source_path.is_absolute():
        source_path = path.parent / source_path
    adapter = _adapter_for_path(source_path, source_name)
    adapter.metadata = DataProductMetadata(source_name, str(source_path), source.get("format", adapter.format),
                                           source.get("record_count"), source.get("sha256"),
                                           tuple(source.get("fields", ())), source.get("schema"), source.get("metadata"))
    if verify:
        rows = adapter.materialize()
        if adapter.metadata.record_count is not None and len(rows) != adapter.metadata.record_count:
            raise ValueError(f"Record count mismatch for source {source_name!r}")
        if adapter.metadata.sha256:
            actual, _ = canonical_record_hash(rows)
            if actual != adapter.metadata.sha256:
                raise ValueError(f"SHA-256 mismatch for source {source_name!r}")
    return adapter
