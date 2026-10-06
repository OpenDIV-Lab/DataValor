"""Leakage-safe public feature extraction with content-addressed caches."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .real_data import RealDatasetBundle


@dataclass(frozen=True)
class PublicFeatureConfig:
    kind: str
    transform_id: str
    n_features: int = 2048
    batch_size: int = 128
    weights_id: str = "ResNet18_Weights.DEFAULT"
    schema_id: str = "none"
    alternate_sign: bool = False


_ADULT_NUMERIC_COLUMNS = (
    "age",
    "fnlwgt",
    "education-num",
    "capital-gain",
    "capital-loss",
    "hours-per-week",
)
_ADULT_CATEGORICAL_COLUMNS = (
    "workclass",
    "education",
    "marital-status",
    "occupation",
    "relationship",
    "race",
    "sex",
    "native-country",
)


@dataclass(frozen=True)
class FeatureArtifact:
    dataset_id: str
    values: np.ndarray
    targets: np.ndarray
    row_ids: tuple[str, ...]
    feature_hash: str
    cache_key: str
    transform_id: str
    weight_hash: str
    package_versions: Mapping[str, str]
    fitted_row_ids: tuple[str, ...]
    extraction_seconds: float
    peak_gpu_bytes: int
    device: str
    physical_gpu_id: int | None
    cache_hit: bool


def _versions() -> dict[str, str]:
    versions = {}
    for package in ("numpy", "scikit-learn", "torch", "torchvision"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


def feature_cache_key(
    bundle: RealDatasetBundle,
    config: PublicFeatureConfig,
    *,
    weight_hash: str,
    package_versions: Mapping[str, str],
) -> str:
    payload = {
        "dataset_hash": bundle.dataset_hash,
        "row_ids": bundle.row_ids,
        "config": asdict(config),
        "weight_hash": weight_hash,
        "package_versions": dict(package_versions),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _array_hash(cache_key: str, values: np.ndarray) -> str:
    array = np.ascontiguousarray(values)
    digest = hashlib.sha256(cache_key.encode())
    digest.update(str(array.dtype).encode())
    digest.update(str(array.shape).encode())
    digest.update(array.tobytes())
    return digest.hexdigest()


def _state_dict_hash(state: Mapping[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous().numpy()
        digest.update(name.encode())
        digest.update(value.tobytes())
    return digest.hexdigest()


def _resnet_model_and_hash(device: str) -> tuple[Any, Any, str]:
    import torch
    from torchvision.models import ResNet18_Weights, resnet18

    weights = ResNet18_Weights.DEFAULT
    model = resnet18(weights=weights)
    weight_hash = _state_dict_hash(model.state_dict())
    encoder = torch.nn.Sequential(*list(model.children())[:-1]).eval().to(device)
    for parameter in encoder.parameters():
        parameter.requires_grad_(False)
    return encoder, weights.transforms(), weight_hash


def _extract_resnet(
    features: Any,
    config: PublicFeatureConfig,
    device: str,
    components: tuple[Any, Any, str] | None = None,
) -> tuple[np.ndarray, str, int]:
    import torch

    encoder, transform, weight_hash = components or _resnet_model_and_hash(device)
    images = np.asarray(features)
    if images.ndim == 3:
        images = np.repeat(images[:, None, :, :], 3, axis=1)
    elif images.ndim == 4 and images.shape[-1] == 3:
        images = np.transpose(images, (0, 3, 1, 2))
    else:
        raise ValueError(f"unsupported image shape for ResNet-18: {images.shape}")
    if device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats(device)
    outputs = []
    with torch.no_grad():
        for start in range(0, len(images), config.batch_size):
            batch = torch.as_tensor(images[start : start + config.batch_size])
            batch = transform(batch).to(device)
            outputs.append(encoder(batch).flatten(1).cpu().numpy())
    peak = torch.cuda.max_memory_allocated(device) if device.startswith("cuda") else 0
    return np.concatenate(outputs).astype(np.float32, copy=False), weight_hash, int(peak)


def _extract_values(
    bundle: RealDatasetBundle,
    config: PublicFeatureConfig,
    device: str,
    *,
    resnet_components: tuple[Any, Any, str] | None = None,
) -> tuple[np.ndarray, str, int]:
    if config.kind == "tabular_numeric":
        return np.asarray(bundle.features, dtype=np.float64), "stateless", 0
    if config.kind == "mixed_tabular_hashing":
        if config.schema_id != "adult-openml-1590-v1":
            raise ValueError("unsupported mixed-tabular public schema")
        if not hasattr(bundle.features, "columns"):
            raise TypeError("mixed_tabular_hashing requires named tabular columns")
        expected = set(_ADULT_NUMERIC_COLUMNS + _ADULT_CATEGORICAL_COLUMNS)
        observed = {str(column) for column in bundle.features.columns}
        if observed != expected:
            raise ValueError(
                "Adult columns differ from public schema: "
                f"missing={sorted(expected - observed)}, extra={sorted(observed - expected)}"
            )
        from sklearn.feature_extraction import FeatureHasher

        numeric = bundle.features.loc[:, _ADULT_NUMERIC_COLUMNS].to_numpy(
            dtype=np.float64
        )
        if not np.all(np.isfinite(numeric)):
            raise ValueError("Adult numeric columns must be finite")

        def token(value: Any) -> str:
            if value is None:
                return "__MISSING__"
            rendered = str(value).strip()
            return "__MISSING__" if not rendered or rendered == "?" else rendered

        categorical_rows = [
            [f"{column}={token(row[column])}" for column in _ADULT_CATEGORICAL_COLUMNS]
            for _, row in bundle.features.iterrows()
        ]
        hasher = FeatureHasher(
            n_features=config.n_features,
            input_type="string",
            alternate_sign=config.alternate_sign,
        )
        categorical = hasher.transform(categorical_rows).toarray().astype(
            np.float64, copy=False
        )
        return np.concatenate((numeric, categorical), axis=1), "stateless", 0
    if config.kind == "digits_raw":
        values = np.asarray(bundle.features, dtype=np.float32).reshape(len(bundle.row_ids), -1)
        return values / np.float32(16.0), "stateless", 0
    if config.kind == "text_hashing":
        from sklearn.feature_extraction.text import HashingVectorizer

        vectorizer = HashingVectorizer(
            n_features=config.n_features,
            alternate_sign=False,
            norm="l2",
        )
        values = vectorizer.transform(np.asarray(bundle.features, dtype=object)).toarray()
        return values.astype(np.float32, copy=False), "stateless", 0
    if config.kind == "resnet18_frozen":
        return _extract_resnet(
            bundle.features, config, device, components=resnet_components
        )
    raise ValueError(f"unsupported public feature kind: {config.kind}")


def extract_public_features(
    bundle: RealDatasetBundle,
    config: PublicFeatureConfig,
    *,
    cache_dir: Path,
    device: str,
) -> FeatureArtifact:
    """Extract deterministic public features; no train/dev/test fitting occurs."""
    package_versions = _versions()
    resnet_components = None
    if config.kind == "resnet18_frozen":
        resnet_components = _resnet_model_and_hash(device)
        weight_hash = resnet_components[2]
    else:
        weight_hash = "stateless"
    cache_key = feature_cache_key(
        bundle,
        config,
        weight_hash=weight_hash,
        package_versions=package_versions,
    )
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    array_path = cache_dir / f"{bundle.dataset_id}-{cache_key}.npz"
    manifest_path = cache_dir / f"{bundle.dataset_id}-{cache_key}.json"
    physical_gpu_id = None
    visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if device.startswith("cuda") and visible_devices:
        physical_gpu_id = int(visible_devices.split(",")[0])
    if array_path.exists() and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        with np.load(array_path, allow_pickle=False) as stored:
            values = stored["values"]
        if manifest.get("cache_key") != cache_key:
            raise ValueError("stale feature cache key")
        if manifest.get("feature_hash") != _array_hash(cache_key, values):
            raise ValueError("corrupt feature cache values")
        return FeatureArtifact(
            bundle.dataset_id,
            values,
            bundle.targets,
            bundle.row_ids,
            manifest["feature_hash"],
            cache_key,
            config.transform_id,
            weight_hash,
            package_versions,
            (),
            float(manifest["extraction_seconds"]),
            int(manifest["peak_gpu_bytes"]),
            device,
            physical_gpu_id,
            True,
        )

    started = time.perf_counter()
    values, extracted_weight_hash, peak_gpu_bytes = _extract_values(
        bundle,
        config,
        device,
        resnet_components=resnet_components,
    )
    if extracted_weight_hash != weight_hash:
        raise ValueError("feature weight hash changed during extraction")
    elapsed = time.perf_counter() - started
    feature_hash = _array_hash(cache_key, values)
    temporary_array = array_path.with_name(f"{array_path.name}.{os.getpid()}.tmp.npz")
    temporary_manifest = manifest_path.with_name(
        f"{manifest_path.name}.{os.getpid()}.tmp"
    )
    np.savez_compressed(temporary_array, values=values)
    temporary_manifest.write_text(
        json.dumps(
            {
                "cache_key": cache_key,
                "feature_hash": feature_hash,
                "extraction_seconds": elapsed,
                "peak_gpu_bytes": peak_gpu_bytes,
            },
            sort_keys=True,
        )
        + "\n"
    )
    os.replace(temporary_array, array_path)
    os.replace(temporary_manifest, manifest_path)
    return FeatureArtifact(
        bundle.dataset_id,
        values,
        bundle.targets,
        bundle.row_ids,
        feature_hash,
        cache_key,
        config.transform_id,
        weight_hash,
        package_versions,
        (),
        elapsed,
        peak_gpu_bytes,
        device,
        physical_gpu_id,
        False,
    )


__all__ = [
    "FeatureArtifact",
    "PublicFeatureConfig",
    "extract_public_features",
    "feature_cache_key",
]
