"""Optional scikit-learn dataset and generator providers."""

from __future__ import annotations

import random
from typing import Any

from .base import BaseDistribution, DistributionBatch


def _sklearn():
    try:
        import sklearn.datasets as datasets
    except ImportError as exc:
        raise ImportError("This provider requires optional dependency scikit-learn") from exc
    return datasets


class SklearnDatasetProvider(BaseDistribution):
    name = "dataset.sklearn"

    def __init__(self, dataset: str = "iris", *, return_target: bool = True, feature_prefix: str = "feature_", target_field: str = "target"):
        self.dataset, self.return_target, self.feature_prefix, self.target_field = dataset, return_target, feature_prefix, target_field

    def generate(self, *, rng: random.Random, context=None) -> DistributionBatch:
        del rng, context
        datasets = _sklearn(); loader = getattr(datasets, f"load_{self.dataset}", None)
        if loader is None: raise ValueError(f"Unsupported sklearn dataset {self.dataset!r}")
        bundle = loader(); rows = []
        for i, values in enumerate(bundle.data):
            row = {f"{self.feature_prefix}{j}": value.item() if hasattr(value, "item") else value for j, value in enumerate(values)}
            if self.return_target and hasattr(bundle, "target"): row[self.target_field] = bundle.target[i].item() if hasattr(bundle.target[i], "item") else bundle.target[i]
            rows.append(row)
        return DistributionBatch(rows, {"source_kind": "real_dataset", "library": "scikit-learn", "dataset": self.dataset})


class SklearnGeneratorProvider(BaseDistribution):
    name = "synthetic.sklearn"

    def __init__(self, generator: str = "make_classification", *, n_samples: int = 100, random_state: int | None = None, **kwargs: Any):
        self.generator, self.n_samples, self.random_state, self.kwargs = generator, n_samples, random_state, kwargs

    def generate(self, *, rng: random.Random, context=None) -> DistributionBatch:
        del context
        datasets = _sklearn(); fn = getattr(datasets, self.generator, None)
        if fn is None: raise ValueError(f"Unsupported sklearn generator {self.generator!r}")
        kwargs = dict(self.kwargs); kwargs.setdefault("n_samples", self.n_samples); kwargs.setdefault("random_state", self.random_state if self.random_state is not None else rng.randrange(2**32))
        result = fn(**kwargs); features, target = (result if isinstance(result, tuple) else (result.data, getattr(result, "target", None)))
        rows = []
        for i, values in enumerate(features):
            row = {f"feature_{j}": value.item() if hasattr(value, "item") else value for j, value in enumerate(values)}
            if target is not None: row["target"] = target[i].item() if hasattr(target[i], "item") else target[i]
            rows.append(row)
        return DistributionBatch(rows, {"source_kind": "synthetic_constructor", "library": "scikit-learn", "generator": self.generator})
