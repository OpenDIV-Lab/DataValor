"""Dataset-shift and corruption operators with deterministic random state."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any


def _copy(records): return [dict(row) for row in records]


def _sample(records, cfg, rng):
    size = int(cfg.get("size", round(len(records) * float(cfg.get("fraction", 1.0)))))
    if size < 0: raise ValueError("sample size must be non-negative")
    if cfg.get("replace", False): return _copy(rng.choices(records, k=size)) if records else []
    if size > len(records): raise ValueError("cannot sample more records without replacement")
    return _copy(rng.sample(records, size))


def _filter(records, cfg):
    field = cfg["field"]
    expected = cfg.get("value")
    checks = {
        "eq": lambda value: value == expected,
        "ne": lambda value: value != expected,
        "gt": lambda value: value is not None and value > expected,
        "ge": lambda value: value is not None and value >= expected,
        "lt": lambda value: value is not None and value < expected,
        "le": lambda value: value is not None and value <= expected,
        "in": lambda value: value in expected,
        "contains": lambda value: expected in value,
    }
    operator = cfg.get("operator", "eq")
    if operator not in checks:
        raise ValueError(f"Unsupported filter operator {operator!r}")
    return [dict(row) for row in records if checks[operator](row.get(field))]


def _covariate_shift(records, cfg, rng):
    field = cfg["field"]
    values = [float(row[field]) for row in records if row.get(field) is not None]
    if not values:
        raise ValueError(f"Covariate field {field!r} has no numeric values")
    mean = sum(values) / len(values)
    scale = (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5 or 1.0
    direction = cfg.get("direction", "high")
    if direction not in {"high", "low"}:
        raise ValueError("direction must be high or low")
    sign = 1.0 if direction == "high" else -1.0
    strength = float(cfg.get("strength", 1.0))
    weights = [math.exp(max(-20.0, min(20.0, sign * strength * ((float(row.get(field, mean)) - mean) / scale)))) for row in records]
    size = int(cfg.get("size", len(records)))
    return _copy(rng.choices(records, weights=weights, k=size)) if records else []


def _noise(records, cfg, rng):
    fields = cfg.get("fields") or [cfg["field"]]
    std = float(cfg.get("std", cfg.get("scale", 0.1)))
    output = _copy(records)
    for row in output:
        for field in fields:
            if field in row and isinstance(row[field], (int, float)) and not isinstance(row[field], bool):
                row[field] += rng.gauss(0.0, std)
    return output


def _duplicate(records, cfg):
    times = int(cfg.get("times", cfg.get("count", 1)))
    if times < 0:
        raise ValueError("duplicate times must be non-negative")
    return [dict(row) for row in records for _ in range(times + 1)]


def _missingness(records, cfg, rng):
    probability = float(cfg.get("probability", .1)); fields = cfg.get("fields") or sorted({k for row in records for k in row})
    if not 0 <= probability <= 1: raise ValueError("missingness probability must be in [0, 1]")
    output = _copy(records); value = cfg.get("value")
    for row in output:
        for field in fields:
            if field in row and rng.random() < float(cfg.get("per_field", {}).get(field, probability)): row[field] = value
    return output


def _label_shift(records, cfg, rng):
    field = cfg.get("label_field", cfg.get("field", "label")); proportions = cfg["proportions"]
    labels = list(proportions); weights = [float(proportions[label]) for label in labels]; total = sum(weights)
    if total <= 0 or any(weight < 0 for weight in weights): raise ValueError("invalid label proportions")
    size = int(cfg.get("size", len(records))); grouped = defaultdict(list)
    for row in records: grouped[str(row.get(field))].append(row)
    output = []
    for label, count in zip(labels, _counts(size, [w / total for w in weights])):
        choices = grouped.get(str(label), [])
        if count and not choices: raise ValueError(f"no records for label {label!r}")
        output.extend(rng.choices(choices, k=count) if cfg.get("replace", True) else rng.sample(choices, count))
    rng.shuffle(output); return _copy(output)


def _counts(total, ratios):
    exact = [total * ratio for ratio in ratios]; result = [math.floor(v) for v in exact]
    for index in sorted(range(len(result)), key=lambda i: exact[i] - result[i], reverse=True)[: total - sum(result)]: result[index] += 1
    return result


def apply_perturbations(records: list[dict[str, Any]], operations: list[dict[str, Any]] | None, *, seed: int = 0) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply named operations and return transformed rows plus an audit trail."""
    rng = random.Random(seed); output = _copy(records); audit = []
    for operation in operations or []:
        kind = str(operation.get("method", operation.get("type", "sample"))).lower()
        if kind in {"sample", "resample"}: output = _sample(output, operation, rng)
        elif kind == "filter": output = _filter(output, operation)
        elif kind in {"covariate_shift", "covariate-shift"}: output = _covariate_shift(output, operation, rng)
        elif kind in {"noise", "gaussian_noise"}: output = _noise(output, operation, rng)
        elif kind in {"duplicate", "duplicates"}: output = _duplicate(output, operation)
        elif kind in {"missingness", "missing"}: output = _missingness(output, operation, rng)
        elif kind in {"label_shift", "label-shift"}: output = _label_shift(output, operation, rng)
        else: raise ValueError(f"Unsupported perturbation {kind!r}")
        audit.append({"method": kind, "parameters": dict(operation), "seed": seed, "record_count": len(output)})
    return output, audit
