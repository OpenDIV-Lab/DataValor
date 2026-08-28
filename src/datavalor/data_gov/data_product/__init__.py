"""Data product readers migrated into the DataGov boundary."""

from .adapters import (
    CSVAdapter,
    DirectoryAdapter,
    IterableAdapter,
    JSONAdapter,
    JSONLAdapter,
    ParquetAdapter,
)
from .base import DataProductAdapter, DataProductMetadata, adapter_from_uri, canonical_record_hash
from .manifest import load_manifest_product

__all__ = [
    "CSVAdapter", "DataProductAdapter", "DataProductMetadata", "DirectoryAdapter",
    "IterableAdapter", "JSONAdapter", "JSONLAdapter", "ParquetAdapter",
    "adapter_from_uri", "canonical_record_hash", "load_manifest_product",
]
