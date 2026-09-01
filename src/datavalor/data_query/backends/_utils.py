"""Dependency-free conversion helpers for DataQuery adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    for name in ("to_dict", "as_dict", "dict", "model_dump"):
        method = getattr(value, name, None)
        if callable(method):
            try:
                result = method()
            except TypeError:
                result = method(exclude_none=True)
            if isinstance(result, Mapping):
                return result
    return {}


def records(value: Any) -> tuple[Mapping[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        for key in ("records", "data", "rows", "results"):
            if key in value:
                return records(value[key])
        return (value,)
    if hasattr(value, "to_dict"):
        try:
            rows = value.to_dict(orient="records")
        except TypeError:
            rows = value.to_dict()
        if isinstance(rows, list):
            return tuple(row for row in rows if isinstance(row, Mapping))
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return tuple(row if isinstance(row, Mapping) else {"value": row} for row in value)
    return ()


def columns(rows: tuple[Mapping[str, Any], ...]) -> tuple[str, ...]:
    names: list[str] = []
    for row in rows:
        for key in row:
            if str(key) not in names:
                names.append(str(key))
    return tuple(names)
