"""Text game declarations; encoders and downloads are benchmark concerns."""

from __future__ import annotations

from . import DatasetManifest

TEXT_DATASETS = {
    "ag_news": "huggingface_download",
    "20newsgroups": "sklearn_download",
}

REAL_TEXT_DATASETS = frozenset(TEXT_DATASETS)


def text_manifest(
    dataset_id: str,
    dataset_hash: str,
    *,
    n_owners: int,
    partition: str,
    imbalance_ratio: int,
    split_seed: int,
) -> DatasetManifest:
    if dataset_id not in TEXT_DATASETS:
        raise ValueError(f"unsupported text dataset: {dataset_id}")
    return DatasetManifest(
        dataset_id,
        "text",
        dataset_hash,
        n_owners,
        partition,
        imbalance_ratio,
        split_seed,
    )


__all__ = ["REAL_TEXT_DATASETS", "TEXT_DATASETS", "text_manifest"]
