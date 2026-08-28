"""Local and HTTP tabular data provider."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from .base import BaseDistribution, DistributionBatch


def _scalar(value: str) -> Any:
    value = value.strip()
    if value == "": return None
    if value.lower() in {"true", "false"}: return value.lower() == "true"
    if value.lower() in {"null", "none", "na", "nan"}: return None
    try: return int(value)
    except ValueError: pass
    try: return float(value)
    except ValueError: return value


class LocalDatasetProvider(BaseDistribution):
    name = "dataset.local"

    def __init__(self, path: str | None = None, paths: list[str] | None = None, *, format: str | None = None,
                 encoding: str = "utf-8", records_key: str | None = None, text_field: str = "text",
                 delimiter: str | None = None, infer_types: bool = True, field_mapping: dict[str, str] | None = None,
                 select_fields: list[str] | None = None, add_fields: dict[str, Any] | None = None,
                 limit: int | None = None, expected_sha256: str | None = None, timeout: float = 30.0):
        self.locations = ([path] if path else []) + list(paths or [])
        if not self.locations: raise ValueError("dataset.local requires path or paths")
        self.format, self.encoding, self.records_key, self.text_field = format, encoding, records_key, text_field
        self.delimiter, self.infer_types, self.field_mapping = delimiter, infer_types, field_mapping or {}
        self.select_fields, self.add_fields, self.limit = select_fields, add_fields or {}, limit
        self.expected_sha256, self.timeout = expected_sha256, timeout
        if limit is not None and limit < 0: raise ValueError("limit must be non-negative")

    def _read(self, location: str) -> bytes:
        if location.startswith(("http://", "https://")):
            with urlopen(Request(location, headers={"User-Agent": "datavalor"}), timeout=self.timeout) as response:  # noqa: S310
                return response.read()
        return Path(location).read_bytes()

    def _decode(self, raw: bytes, location: str) -> list[dict[str, Any]]:
        suffix = Path(location.split("?", 1)[0]).suffix.lower().lstrip(".")
        kind = (self.format or suffix or "jsonl").lower()
        text = raw.decode(self.encoding)
        if kind in {"jsonl", "ndjson"}:
            return [dict(json.loads(line)) if isinstance(json.loads(line), dict) else {self.text_field: json.loads(line)}
                    for line in text.splitlines() if line.strip()]
        if kind == "json":
            payload = json.loads(text)
            if self.records_key:
                for key in self.records_key.split("."): payload = payload[key]
            rows = payload.get("records", payload) if isinstance(payload, dict) else payload
            rows = rows if isinstance(rows, list) else [rows]
            return [dict(row) if isinstance(row, dict) else {self.text_field: row} for row in rows]
        if kind in {"csv", "tsv"}:
            delim = self.delimiter or ("\t" if kind == "tsv" else ",")
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
            return [{key: (_scalar(value) if self.infer_types else value) for key, value in row.items()} for row in rows]
        if kind in {"txt", "text"}: return [{self.text_field: line} for line in text.splitlines() if line.strip()]
        raise ValueError(f"Unsupported local dataset format {kind!r}")

    def generate(self, *, rng, context=None) -> DistributionBatch:
        del rng, context
        rows, digests = [], []
        for location in self.locations:
            raw = self._read(location); digest = hashlib.sha256(raw).hexdigest(); digests.append(digest)
            if self.expected_sha256 and len(self.locations) == 1 and digest != self.expected_sha256:
                raise ValueError(f"SHA-256 mismatch for {location}")
            rows.extend(self._decode(raw, location))
        output = []
        for row in rows:
            mapped = {self.field_mapping.get(key, key): value for key, value in row.items()}
            if self.select_fields is not None: mapped = {key: mapped.get(key) for key in self.select_fields}
            mapped.update(self.add_fields); output.append(mapped)
        if self.limit is not None: output = output[: self.limit]
        return DistributionBatch(output, {"source_kind": "real_dataset", "locations": self.locations, "input_sha256": digests})
