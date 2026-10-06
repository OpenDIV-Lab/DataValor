"""Frozen provenance catalog for public datasets used by real-game studies."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass, field
from typing import Mapping


def _version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


@dataclass(frozen=True)
class SourceRecord:
    dataset_id: str
    modality: str
    task: str
    canonical_source: str
    license_id: str
    loader_id: str
    package_name: str
    package_version: str
    pinned_revision: str | None = None
    allowed_replacements: tuple[str, ...] = ()
    replaces: str | None = None


@dataclass(frozen=True)
class SourcePolicy:
    allow_download: bool = True
    replacements: Mapping[str, str] = field(default_factory=dict)


def declared_real_sources() -> dict[str, SourceRecord]:
    sklearn_version = _version("scikit-learn")
    torchvision_version = _version("torchvision")
    datasets_version = _version("datasets")
    return {
        "breast_cancer": SourceRecord(
            "breast_cancer", "tabular", "classification",
            "sklearn:load_breast_cancer", "CC-BY-4.0", "sklearn_builtin",
            "scikit-learn", sklearn_version,
        ),
        "wine": SourceRecord(
            "wine", "tabular", "classification", "sklearn:load_wine",
            "CC-BY-4.0", "sklearn_builtin", "scikit-learn", sklearn_version,
        ),
        "adult": SourceRecord(
            "adult", "tabular", "classification", "openml:data_id=1590",
            "CC-BY-4.0", "sklearn_openml", "scikit-learn", sklearn_version,
            allowed_replacements=("adult_uci_mirror",),
        ),
        "california_housing": SourceRecord(
            "california_housing", "tabular", "regression",
            "sklearn:fetch_california_housing", "StatLib", "sklearn_fetch",
            "scikit-learn", sklearn_version, allowed_replacements=("diabetes",),
        ),
        "diabetes": SourceRecord(
            "diabetes", "tabular", "regression", "sklearn:load_diabetes",
            "BSD-3-Clause", "sklearn_builtin", "scikit-learn", sklearn_version,
        ),
        "digits": SourceRecord(
            "digits", "image", "classification", "sklearn:load_digits",
            "CC-BY-4.0", "sklearn_builtin", "scikit-learn", sklearn_version,
        ),
        "ag_news": SourceRecord(
            "ag_news", "text", "classification", "huggingface:ag_news",
            "unknown-upstream", "huggingface_datasets", "datasets", datasets_version,
            pinned_revision="default", allowed_replacements=("20newsgroups",),
        ),
        "20newsgroups": SourceRecord(
            "20newsgroups", "text", "classification",
            "sklearn:fetch_20newsgroups", "dataset-terms", "sklearn_fetch",
            "scikit-learn", sklearn_version,
        ),
        "fashion_mnist": SourceRecord(
            "fashion_mnist", "image", "classification",
            "torchvision:FashionMNIST", "MIT", "torchvision_dataset",
            "torchvision", torchvision_version,
        ),
        "cifar10_subset": SourceRecord(
            "cifar10_subset", "image", "classification", "torchvision:CIFAR10",
            "MIT-like", "torchvision_dataset", "torchvision", torchvision_version,
        ),
    }


def _replacement_sources() -> dict[str, SourceRecord]:
    return {
        "adult_uci_mirror": SourceRecord(
            "adult_uci_mirror", "tabular", "classification",
            "uci:adult/id=2", "CC-BY-4.0", "uci_direct", "none", "n/a",
            replaces="adult",
        )
    }


def resolve_source(dataset_id: str, policy: SourcePolicy) -> SourceRecord:
    sources = declared_real_sources()
    if dataset_id not in sources:
        raise KeyError(f"undeclared real dataset: {dataset_id}")
    primary = sources[dataset_id]
    replacement_id = policy.replacements.get(dataset_id)
    if replacement_id is None:
        return primary
    if replacement_id not in primary.allowed_replacements:
        raise ValueError(
            f"{replacement_id!r} is not an allowed replacement for {dataset_id!r}"
        )
    if replacement_id in sources:
        return SourceRecord(
            **{
                **sources[replacement_id].__dict__,
                "replaces": dataset_id,
            }
        )
    return _replacement_sources()[replacement_id]


__all__ = [
    "SourcePolicy",
    "SourceRecord",
    "declared_real_sources",
    "resolve_source",
]
