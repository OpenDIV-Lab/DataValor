"""Normalize browser-facing input formats into DataValor record payloads."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse


@dataclass(frozen=True)
class InputError:
    code: str
    message: str
    location: str


@dataclass(frozen=True)
class InputPreview:
    input_type: str
    records: tuple[dict[str, Any], ...]
    schema: dict[str, str]
    errors: tuple[InputError, ...]
    stats: dict[str, Any]


def _scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if text.lower() in {"null", "none"}:
        return None
    try:
        return int(text) if text and all(char not in text.lower() for char in (".", "e")) else float(text)
    except ValueError:
        return value


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "string"


def _coerce(value: Any, expected: str) -> Any:
    if value is None:
        return None
    if expected == "string":
        return str(value)
    if expected == "integer":
        return int(value)
    if expected == "number":
        return float(value)
    if expected == "boolean":
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized not in {"true", "1", "yes", "y", "false", "0", "no", "n"}:
                raise ValueError(f"cannot coerce {value!r} to boolean")
            return normalized in {"true", "1", "yes", "y"}
        return bool(value)
    if expected == "object":
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict):
            raise ValueError("value is not an object")
        return parsed
    if expected == "array":
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, list):
            raise ValueError("value is not an array")
        return parsed
    if expected not in {"null", "mixed"}:
        raise ValueError(f"unsupported schema type: {expected}")
    return value


def _infer(records: list[dict[str, Any]]) -> dict[str, str]:
    fields: dict[str, list[str]] = {}
    for record in records:
        for name, value in record.items():
            fields.setdefault(str(name), []).append(_type_name(value))
    schema = {}
    for name, types in fields.items():
        non_null = {item for item in types if item != "null"}
        if non_null <= {"integer"}:
            schema[name] = "integer"
        elif non_null <= {"integer", "number"}:
            schema[name] = "number"
        elif len(non_null) == 1:
            schema[name] = next(iter(non_null))
        else:
            schema[name] = "mixed"
    return schema


def parse_input(input_type: str, content: Any, options: Mapping[str, Any] | None = None) -> InputPreview:
    """Parse a supported input without reading remote resources or arbitrary paths."""
    kind = str(input_type).lower().replace("-", "_")
    options = dict(options or {})
    records: list[dict[str, Any]] = []
    errors: list[InputError] = []
    encoding = str(options.get("encoding", "utf-8")).lower()
    if encoding not in {"utf-8", "utf8", "gb18030", "latin-1", "latin1"}:
        errors.append(InputError("invalid_encoding", f"unsupported encoding: {encoding}", "options.encoding"))
    if kind == "json":
        try:
            value = json.loads(content) if isinstance(content, str) else content
            values = value if isinstance(value, list) else [value]
            for index, item in enumerate(values, 1):
                if isinstance(item, dict):
                    records.append(dict(item))
                else:
                    errors.append(InputError("record_type", "JSON records must be objects", f"record:{index}"))
        except (json.JSONDecodeError, TypeError) as exc:
            errors.append(InputError("invalid_json", str(exc), "document"))
    elif kind in {"jsonl", "ndjson"}:
        for line_number, line in enumerate(str(content or "").splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
                if not isinstance(item, dict):
                    raise TypeError("JSON line must contain an object")
                records.append(item)
            except (json.JSONDecodeError, TypeError) as exc:
                errors.append(InputError("invalid_json", str(exc), f"line:{line_number}"))
    elif kind in {"csv", "tsv"}:
        delimiter = str(options.get("delimiter", "\t" if kind == "tsv" else ","))
        if len(delimiter) != 1:
            errors.append(InputError("invalid_delimiter", "delimiter must be exactly one character", "options.delimiter"))
        else:
            reader = csv.DictReader(io.StringIO(str(content or "")), delimiter=delimiter)
            for row_number, row in enumerate(reader, 2):
                extras = row.pop(None, None)
                missing = [name for name, value in row.items() if value is None]
                if extras or missing:
                    errors.append(InputError("column_count", "row has a different number of columns than the header", f"row:{row_number}"))
                records.append({str(name): _scalar(value) for name, value in row.items() if name is not None})
    elif kind in {"key_value", "parameters"}:
        if not isinstance(content, Mapping):
            errors.append(InputError("record_type", "key-value input must be an object", "document"))
        else:
            records.append({str(name): _scalar(value) for name, value in content.items()})
    elif kind in {"uri", "catalog", "artifact", "upstream"}:
        reference = str(content or "").strip()
        parsed = urlparse(reference)
        expected_scheme = None if kind == "uri" else kind
        if not reference or not parsed.scheme or (expected_scheme and parsed.scheme != expected_scheme):
            errors.append(InputError("invalid_reference", f"invalid {kind} reference", "content"))
        available = {str(value) for value in options.get("available_references", ())}
        reference_id = (parsed.netloc + parsed.path).lstrip("/")
        if available and reference_id not in available:
            errors.append(InputError("missing_reference", f"reference does not exist: {reference_id}", "content"))
    else:
        errors.append(InputError("unsupported_type", f"unsupported input type: {input_type}", "input_type"))

    schema_option = options.get("schema", {})
    if not isinstance(schema_option, Mapping):
        errors.append(InputError("invalid_schema", "schema must be an object", "options.schema"))
        schema_option = {}
    override = {str(name): str(value) for name, value in schema_option.items()}
    if override:
        for row_number, record in enumerate(records, 1):
            for name, expected in override.items():
                if name not in record:
                    continue
                try:
                    record[name] = _coerce(record[name], expected)
                except (TypeError, ValueError) as exc:
                    errors.append(InputError("schema_coercion", str(exc), f"record:{row_number}.{name}"))
    total_records = len(records)
    sample_size = options.get("sample_size")
    if sample_size is not None:
        try:
            sample_size = max(0, int(sample_size))
            records = records[:sample_size]
        except (TypeError, ValueError):
            errors.append(InputError("invalid_sample_size", "sample_size must be an integer", "options.sample_size"))
    try:
        batch_size = max(1, int(options.get("batch_size", max(1, len(records)))))
    except (TypeError, ValueError):
        errors.append(InputError("invalid_batch_size", "batch_size must be a positive integer", "options.batch_size"))
        batch_size = max(1, len(records))
    schema = {**_infer(records), **override}
    stats = {"record_count": len(records), "source_record_count": total_records, "field_count": len(schema), "sampled": len(records) < total_records, "batch_size": batch_size, "batch_count": (len(records) + batch_size - 1) // batch_size, "valid": not errors}
    return InputPreview(kind, tuple(records), schema, tuple(errors), stats)


__all__ = ["InputError", "InputPreview", "parse_input"]
