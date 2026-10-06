"""Tabular game declarations and deterministic manifests."""

from __future__ import annotations

from . import DatasetManifest

TABULAR_DATASETS = {
    "breast_cancer": ("classification", "tree_ensemble"),
    "wine": ("classification", "tree_ensemble"),
    "adult": ("classification", "boosting"),
    "covertype_subset": ("classification", "boosting"),
    "california_housing": ("regression", "boosting"),
    "diabetes": ("regression", "boosting"),
}

REAL_TABULAR_DATASETS = frozenset(TABULAR_DATASETS)


def tabular_manifest(
    dataset_id: str,
    dataset_hash: str,
    *,
    n_owners: int,
    partition: str,
    imbalance_ratio: int,
    split_seed: int,
) -> DatasetManifest:
    if dataset_id not in TABULAR_DATASETS:
        raise ValueError(f"unsupported tabular dataset: {dataset_id}")
    return DatasetManifest(
        dataset_id,
        "tabular",
        dataset_hash,
        n_owners,
        partition,
        imbalance_ratio,
        split_seed,
    )


__all__ = ["REAL_TABULAR_DATASETS", "TABULAR_DATASETS", "tabular_manifest"]
