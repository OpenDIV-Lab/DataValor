"""Image game declarations; model execution remains in GPU jobs."""

from __future__ import annotations

from . import DatasetManifest

IMAGE_DATASETS = {
    "digits": "bundled_sklearn",
    "fashion_mnist": "torchvision_download",
    "cifar10_subset": "torchvision_download",
}

REAL_IMAGE_DATASETS = frozenset(IMAGE_DATASETS)


def image_manifest(
    dataset_id: str,
    dataset_hash: str,
    *,
    n_owners: int,
    partition: str,
    imbalance_ratio: int,
    split_seed: int,
) -> DatasetManifest:
    if dataset_id not in IMAGE_DATASETS:
        raise ValueError(f"unsupported image dataset: {dataset_id}")
    return DatasetManifest(
        dataset_id,
        "image",
        dataset_hash,
        n_owners,
        partition,
        imbalance_ratio,
        split_seed,
    )


__all__ = ["IMAGE_DATASETS", "REAL_IMAGE_DATASETS", "image_manifest"]
