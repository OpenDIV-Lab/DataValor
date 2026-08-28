"""Deterministic synthetic tabular distribution provider."""

from __future__ import annotations

import math
import random
import uuid
from typing import Any

from .base import BaseDistribution, DistributionBatch


def _require(spec: dict[str, Any], key: str) -> Any:
    if key not in spec: raise ValueError(f"Missing distribution parameter {key!r}")
    return spec[key]


def _draw(spec: dict[str, Any], rng: random.Random, index: int) -> Any:
    kind = str(spec.get("distribution", spec.get("type", "constant"))).lower()
    if kind == "constant": return spec.get("value")
    if kind in {"categorical", "choice"}:
        values = _require(spec, "values")
        if not values: raise ValueError("Categorical values cannot be empty")
        return rng.choices(values, weights=spec.get("weights", spec.get("probabilities")), k=1)[0]
    if kind == "bernoulli": return rng.random() < float(spec.get("p", spec.get("probability", .5)))
    if kind == "uniform": return rng.uniform(float(spec.get("low", 0)), float(spec.get("high", 1)))
    if kind in {"randint", "integer_uniform"}: return rng.randint(int(_require(spec, "low")), int(_require(spec, "high")))
    if kind in {"normal", "gaussian"}: return rng.gauss(float(spec.get("mean", 0)), float(spec.get("std", 1)))
    if kind == "lognormal": return rng.lognormvariate(float(spec.get("mean", 0)), float(spec.get("sigma", 1)))
    if kind == "exponential": return rng.expovariate(float(spec.get("rate", 1)))
    if kind == "beta": return rng.betavariate(float(_require(spec, "alpha")), float(_require(spec, "beta")))
    if kind == "gamma": return rng.gammavariate(float(_require(spec, "shape")), float(spec.get("scale", 1)))
    if kind == "triangular": return rng.triangular(float(spec.get("low", 0)), float(spec.get("high", 1)), spec.get("mode"))
    if kind == "poisson":
        rate = float(spec.get("rate", spec.get("lambda", 1))); count, product = 0, 1.0
        while product > math.exp(-rate): count += 1; product *= rng.random()
        return count - 1
    if kind == "sequence": return spec.get("start", 0) + index * spec.get("step", 1)
    if kind == "uuid": return str(uuid.UUID(int=rng.getrandbits(128), version=4))
    raise ValueError(f"Unsupported parametric distribution {kind!r}")


class ParametricProvider(BaseDistribution):
    name = "synthetic.parametric"

    def __init__(self, num_rows: int = 100, fields: dict[str, dict[str, Any]] | None = None,
                 relationships: list[dict[str, Any]] | None = None):
        if num_rows < 0: raise ValueError("num_rows must be non-negative")
        self.num_rows, self.fields, self.relationships = num_rows, fields or {}, relationships or []

    def generate(self, *, rng: random.Random, context=None) -> DistributionBatch:
        del context
        rows = [{field: _draw(spec, rng, i) for field, spec in self.fields.items()} for i in range(self.num_rows)]
        for rel in self.relationships:
            target, weights = rel["target"], rel.get("weights", {})
            for row in rows:
                score = float(rel.get("bias", 0)) + sum(float(row[field]) * float(weight) for field, weight in weights.items())
                if rel.get("noise_std"): score += rng.gauss(0, float(rel["noise_std"]))
                kind = rel.get("type", "linear")
                if kind == "linear": row[target] = score
                elif kind == "threshold": row[target] = rel.get("positive", 1) if score >= float(rel.get("threshold", 0)) else rel.get("negative", 0)
                elif kind == "logistic": row[target] = rel.get("positive", 1) if rng.random() < 1 / (1 + math.exp(-max(-700, min(700, score)))) else rel.get("negative", 0)
                else: raise ValueError(f"Unsupported relationship type {kind!r}")
        return DistributionBatch(rows, {"source_kind": "synthetic_constructor", "num_fields": len(self.fields), "relationship_count": len(self.relationships)})
