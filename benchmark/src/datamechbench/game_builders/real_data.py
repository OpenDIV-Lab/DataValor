"""Canonical real-dataset bundles and leakage-audited owner manifests."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from sklearn.model_selection import train_test_split

from . import partition_indices
from .real_sources import SourcePolicy, SourceRecord, resolve_source

ALLOWED_SPLIT_SEEDS = frozenset({11, 29, 47})


def _canonical_array_payload(value: Any) -> bytes:
    if hasattr(value, "to_numpy"):
        value = value.to_numpy()
    array = np.asarray(value)
    header = json.dumps(
        {"shape": array.shape, "dtype": str(array.dtype)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if array.dtype.kind in {"O", "U", "S"}:
        body = json.dumps(
            array.astype(str).tolist(), ensure_ascii=False, separators=(",", ":")
        ).encode()
    else:
        body = np.ascontiguousarray(array).tobytes()
    return header + b"\0" + body


def canonical_dataset_hash(
    features: Any,
    targets: Any,
    row_ids: tuple[str, ...],
    source: SourceRecord,
) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(asdict(source), sort_keys=True, separators=(",", ":")).encode())
    digest.update(_canonical_array_payload(features))
    digest.update(_canonical_array_payload(targets))
    digest.update(json.dumps(row_ids, separators=(",", ":")).encode())
    return digest.hexdigest()


@dataclass(frozen=True)
class RealDatasetBundle:
    source: SourceRecord
    features: Any
    targets: np.ndarray
    row_ids: tuple[str, ...]
    dataset_hash: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        source: SourceRecord,
        features: Any,
        targets: Any,
        *,
        row_ids: tuple[str, ...] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "RealDatasetBundle":
        target_array = np.asarray(targets)
        if len(target_array) != len(features):
            raise ValueError("features and targets must contain the same number of rows")
        ids = row_ids or tuple(f"{source.dataset_id}:{index}" for index in range(len(target_array)))
        if len(ids) != len(target_array) or len(set(ids)) != len(ids):
            raise ValueError("row IDs must be unique and match dataset length")
        return cls(
            source,
            features,
            target_array,
            tuple(ids),
            canonical_dataset_hash(features, target_array, tuple(ids), source),
            dict(metadata or {}),
        )

    @property
    def dataset_id(self) -> str:
        return self.source.dataset_id

    @property
    def modality(self) -> str:
        return self.source.modality

    @property
    def task(self) -> str:
        return self.source.task


def _take_rows(features: Any, indices: np.ndarray) -> Any:
    if hasattr(features, "iloc"):
        return features.iloc[indices].reset_index(drop=True)
    return np.asarray(features)[indices]


def _artifact_record(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": path.name,
        "sha256": digest.hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def _load_local_adult_arff(path: Path) -> tuple[Any, np.ndarray]:
    import pandas as pd
    from scipy.io import arff

    records, _ = arff.loadarff(path)
    frame = pd.DataFrame.from_records(records)
    for column in frame.columns:
        if frame[column].dtype == object:
            frame[column] = frame[column].map(
                lambda value: value.decode("utf-8")
                if isinstance(value, bytes)
                else value
            )
    target = frame.pop("class").astype(str).to_numpy()
    return frame, target


def _load_local_ag_news(paths: tuple[Path, Path]) -> tuple[np.ndarray, np.ndarray]:
    import pandas as pd

    frame = pd.concat(
        [pd.read_parquet(path, columns=["text", "label"]) for path in paths],
        ignore_index=True,
    )
    return frame["text"].astype(str).to_numpy(dtype=object), frame["label"].to_numpy(
        dtype=np.int64
    )


def _load_local_cifar(paths: tuple[Path, Path]) -> tuple[np.ndarray, np.ndarray]:
    from io import BytesIO

    import pandas as pd
    from PIL import Image

    frame = pd.concat(
        [pd.read_parquet(path, columns=["img", "label"]) for path in paths],
        ignore_index=True,
    )
    images = []
    for encoded in frame["img"]:
        payload = encoded["bytes"] if isinstance(encoded, dict) else encoded
        with Image.open(BytesIO(payload)) as image:
            images.append(np.asarray(image.convert("RGB"), dtype=np.uint8))
    return np.stack(images), frame["label"].to_numpy(dtype=np.int64)


def _strata(targets: np.ndarray, task: str) -> np.ndarray:
    if task == "classification":
        return targets
    quantiles = np.unique(np.quantile(targets.astype(float), np.linspace(0, 1, 11)))
    if len(quantiles) <= 2:
        return np.zeros(len(targets), dtype=int)
    return np.digitize(targets.astype(float), quantiles[1:-1], right=True)


def deterministic_cap(
    bundle: RealDatasetBundle, *, cap: int | None, seed: int
) -> RealDatasetBundle:
    if cap is None or len(bundle.targets) <= cap:
        return bundle
    if cap < 2:
        raise ValueError("cap must be at least two")
    indices = np.arange(len(bundle.targets))
    selected, _ = train_test_split(
        indices,
        train_size=cap,
        random_state=seed,
        stratify=_strata(bundle.targets, bundle.task),
    )
    selected = np.sort(selected)
    return RealDatasetBundle.create(
        bundle.source,
        _take_rows(bundle.features, selected),
        bundle.targets[selected],
        row_ids=tuple(bundle.row_ids[index] for index in selected),
        metadata={**bundle.metadata, "cap": cap, "cap_seed": seed},
    )


@dataclass(frozen=True)
class RealDatasetManifest:
    setting_id: str
    dataset_id: str
    dataset_hash: str
    source: SourceRecord
    modality: str
    task: str
    n_owners: int
    split_seed: int
    partition: str
    imbalance_ratio: int
    stratification: str
    train_row_ids: tuple[str, ...]
    validation_row_ids: tuple[str, ...]
    test_row_ids: tuple[str, ...]
    owner_row_ids: Mapping[str, tuple[str, ...]]
    transform_fit_row_ids: tuple[str, ...]
    content_hash: str


def _manifest_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=list).encode()
    ).hexdigest()


def split_and_partition(
    bundle: RealDatasetBundle,
    *,
    setting_id: str,
    n_owners: int,
    split_seed: int,
    partition: str,
    imbalance_ratio: int,
) -> RealDatasetManifest:
    if split_seed not in ALLOWED_SPLIT_SEEDS:
        raise ValueError(f"split_seed must be one of {sorted(ALLOWED_SPLIT_SEEDS)}")
    indices = np.arange(len(bundle.targets))
    strata = _strata(bundle.targets, bundle.task)
    train_validation, test = train_test_split(
        indices,
        test_size=1 / 6,
        random_state=split_seed,
        stratify=strata,
    )
    train, validation = train_test_split(
        train_validation,
        test_size=1 / 5,
        random_state=split_seed + 1,
        stratify=strata[train_validation],
    )
    train = np.sort(train)
    validation = np.sort(validation)
    test = np.sort(test)
    owner_labels = strata[train]
    local_partition = partition_indices(
        owner_labels,
        n_owners=n_owners,
        scheme=partition,
        imbalance_ratio=imbalance_ratio,
        seed=split_seed,
    )
    owner_rows = {
        owner: tuple(bundle.row_ids[train[index]] for index in local_indices)
        for owner, local_indices in local_partition.items()
    }
    train_ids = tuple(bundle.row_ids[index] for index in train)
    validation_ids = tuple(bundle.row_ids[index] for index in validation)
    test_ids = tuple(bundle.row_ids[index] for index in test)
    payload = {
        "setting_id": setting_id,
        "dataset_id": bundle.dataset_id,
        "dataset_hash": bundle.dataset_hash,
        "source": asdict(bundle.source),
        "modality": bundle.modality,
        "task": bundle.task,
        "n_owners": n_owners,
        "split_seed": split_seed,
        "partition": partition,
        "imbalance_ratio": imbalance_ratio,
        "stratification": "class_labels" if bundle.task == "classification" else "target_quantiles_10",
        "train_row_ids": train_ids,
        "validation_row_ids": validation_ids,
        "test_row_ids": test_ids,
        "owner_row_ids": owner_rows,
        "transform_fit_row_ids": train_ids,
    }
    return RealDatasetManifest(**payload, content_hash=_manifest_hash(payload))


def audit_split_isolation(manifest: RealDatasetManifest) -> tuple[str, ...]:
    errors = []
    train = set(manifest.train_row_ids)
    validation = set(manifest.validation_row_ids)
    test = set(manifest.test_row_ids)
    if train & validation or train & test or validation & test:
        errors.append("split_overlap")
    owner_rows = [row for rows in manifest.owner_row_ids.values() for row in rows]
    if set(owner_rows) != train or len(owner_rows) != len(set(owner_rows)):
        errors.append("owner_rows_not_exact_train_partition")
    if not set(manifest.transform_fit_row_ids).issubset(train):
        errors.append("transform_fit_rows_outside_train")
    return tuple(errors)


def load_real_dataset(
    dataset_id: str,
    *,
    cache_dir: Path,
    cap: int | None,
    source_policy: SourcePolicy,
) -> RealDatasetBundle:
    """Load one declared real dataset without fitting any feature transform."""
    source = resolve_source(dataset_id, source_policy)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    if source.replaces == "adult":
        raise RuntimeError("the UCI direct Adult replacement requires a downloaded CSV")
    if dataset_id in {"breast_cancer", "wine", "diabetes", "digits"}:
        from sklearn import datasets as skdatasets

        loader = {
            "breast_cancer": skdatasets.load_breast_cancer,
            "wine": skdatasets.load_wine,
            "diabetes": skdatasets.load_diabetes,
            "digits": skdatasets.load_digits,
        }[dataset_id]
        loaded = loader()
        bundle = RealDatasetBundle.create(source, loaded.data, loaded.target)
    elif dataset_id == "california_housing":
        from sklearn.datasets import fetch_california_housing

        loaded = fetch_california_housing(data_home=cache_dir, download_if_missing=source_policy.allow_download)
        bundle = RealDatasetBundle.create(source, loaded.data, loaded.target)
    elif dataset_id == "adult":
        local_arff = cache_dir / "adult.arff"
        if local_arff.exists():
            features, targets = _load_local_adult_arff(local_arff)
            bundle = RealDatasetBundle.create(
                source,
                features,
                targets,
                metadata={"retrieval_artifacts": [_artifact_record(local_arff)]},
            )
        else:
            if not source_policy.allow_download:
                raise OSError("Adult OpenML ARFF not found and downloads are disabled")
            from sklearn.datasets import fetch_openml

            loaded = fetch_openml(data_id=1590, as_frame=True, data_home=cache_dir)
            bundle = RealDatasetBundle.create(
                source, loaded.data, loaded.target.astype(str).to_numpy()
            )
    elif dataset_id == "20newsgroups":
        from sklearn.datasets import fetch_20newsgroups

        loaded = fetch_20newsgroups(
            subset="all", data_home=cache_dir, download_if_missing=source_policy.allow_download,
            remove=("headers", "footers", "quotes"),
        )
        bundle = RealDatasetBundle.create(source, np.asarray(loaded.data, dtype=object), loaded.target)
    elif dataset_id == "ag_news":
        local_paths = (
            cache_dir / "ag_news_train.parquet",
            cache_dir / "ag_news_test.parquet",
        )
        if all(path.exists() for path in local_paths):
            texts, targets = _load_local_ag_news(local_paths)
            bundle = RealDatasetBundle.create(
                source,
                texts,
                targets,
                metadata={
                    "retrieval_artifacts": [_artifact_record(path) for path in local_paths]
                },
            )
        else:
            if not source_policy.allow_download:
                raise OSError("AG News Parquet files not found and downloads are disabled")
            from datasets import load_dataset

            loaded = load_dataset("ag_news", cache_dir=str(cache_dir))
            texts = np.asarray(
                list(loaded["train"]["text"]) + list(loaded["test"]["text"]),
                dtype=object,
            )
            targets = np.asarray(
                list(loaded["train"]["label"]) + list(loaded["test"]["label"]),
                dtype=np.int64,
            )
            bundle = RealDatasetBundle.create(source, texts, targets)
    elif dataset_id in {"fashion_mnist", "cifar10_subset"}:
        cifar_paths = (
            cache_dir / "cifar10_train.parquet",
            cache_dir / "cifar10_test.parquet",
        )
        if dataset_id == "cifar10_subset" and all(
            path.exists() for path in cifar_paths
        ):
            features, targets = _load_local_cifar(cifar_paths)
            bundle = RealDatasetBundle.create(
                source,
                features,
                targets,
                metadata={
                    "retrieval_artifacts": [_artifact_record(path) for path in cifar_paths]
                },
            )
            return deterministic_cap(bundle, cap=cap, seed=20260930)
        from torchvision.datasets import CIFAR10, FashionMNIST

        cls = FashionMNIST if dataset_id == "fashion_mnist" else CIFAR10
        train = cls(root=str(cache_dir), train=True, download=source_policy.allow_download)
        test = cls(root=str(cache_dir), train=False, download=source_policy.allow_download)
        features = np.concatenate((np.asarray(train.data), np.asarray(test.data)))
        targets = np.asarray(list(train.targets) + list(test.targets), dtype=np.int64)
        bundle = RealDatasetBundle.create(source, features, targets)
    else:
        raise KeyError(f"no loader implemented for declared dataset: {dataset_id}")
    return deterministic_cap(bundle, cap=cap, seed=20260930)


def source_inventory_record(bundle: RealDatasetBundle) -> dict[str, Any]:
    shape = list(getattr(bundle.features, "shape", np.asarray(bundle.features).shape))
    return {
        "dataset_id": bundle.dataset_id,
        "modality": bundle.modality,
        "task": bundle.task,
        "canonical_source": bundle.source.canonical_source,
        "license_id": bundle.source.license_id,
        "loader_id": bundle.source.loader_id,
        "package_name": bundle.source.package_name,
        "package_version": bundle.source.package_version,
        "pinned_revision": bundle.source.pinned_revision,
        "replaces": bundle.source.replaces,
        "dataset_hash": bundle.dataset_hash,
        "row_count": len(bundle.row_ids),
        "feature_shape": shape,
        "target_dtype": str(bundle.targets.dtype),
        "metadata": dict(bundle.metadata),
    }


def write_source_inventory(
    records: tuple[Mapping[str, Any], ...], path: Path
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {"schema_version": "1.0", "datasets": list(records)},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    os.replace(temporary, target)
    return target


__all__ = [
    "ALLOWED_SPLIT_SEEDS",
    "RealDatasetBundle",
    "RealDatasetManifest",
    "audit_split_isolation",
    "canonical_dataset_hash",
    "deterministic_cap",
    "load_real_dataset",
    "source_inventory_record",
    "split_and_partition",
    "write_source_inventory",
]
