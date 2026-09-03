"""Dependency-free helpers shared by governance service connectors."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from datavalor.core.exceptions import DataValorError


class ConnectorError(DataValorError):
    """A remote connector failed after its configured retry budget."""


def call_with_retry(
    operation: Callable[..., Any],
    *args: Any,
    retries: int = 0,
    timeout: float | None = None,
    **kwargs: Any,
) -> Any:
    """Invoke an injected SDK/transport with bounded retries.

    Timeout is passed to clients that accept it; arbitrary fake clients remain
    usable because a second call without the keyword is attempted on a
    ``TypeError``.  No sleeps are used by default, keeping offline tests fast.
    """

    last: Exception | None = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            if timeout is None:
                return operation(*args, **kwargs)
            try:
                return operation(*args, timeout=timeout, **kwargs)
            except TypeError as exc:
                if "timeout" not in str(exc):
                    raise
                return operation(*args, **kwargs)
        except Exception as exc:  # SDK exception types vary by release.
            last = exc
            if attempt >= max(0, int(retries)):
                break
    raise ConnectorError(
        f"external connector operation failed after {max(0, int(retries)) + 1} attempt(s)"
    ) from last


def as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    for name in ("to_dict", "as_dict", "dict"):
        method = getattr(value, name, None)
        if callable(method):
            try:
                result = method()
            except TypeError:
                result = method(exclude_none=True)
            if isinstance(result, Mapping):
                return result
    for name in ("jsonValue", "json_value", "to_json"):
        method = getattr(value, name, None)
        if callable(method):
            try:
                result = method()
                if isinstance(result, str):
                    result = json.loads(result)
                if isinstance(result, Mapping):
                    return result
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    return {}


def mapping_value(value: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    for path in paths:
        current: Any = value
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return default

