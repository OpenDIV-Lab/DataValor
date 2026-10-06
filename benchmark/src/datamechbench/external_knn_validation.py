"""Deterministic cross-check against the pinned OpenDataVal KNN-Shapley source."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import platform
import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.preprocessing import StandardScaler

from .data import OwnerDataset
from .methods.valuation_model_based import evaluate_model_based
from .models import ValuationCase

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
DEFAULT_SOURCE = PACKAGE_ROOT / "external" / "opendataval" / "knnshap.py"
DEFAULT_LICENSE = PACKAGE_ROOT / "external" / "opendataval" / "LICENSE.txt"
DEFAULT_FIXTURES = (
    PACKAGE_ROOT / "external" / "opendataval" / "knn_shapley_fixtures.json"
)
DEFAULT_OUTPUT_DIRECTORY = PACKAGE_ROOT / "evidence"

VALIDATION_ID = "opendataval-knn-shapley-5c2856b9"
UPSTREAM_COMMIT = "5c2856b95237a07ee4565638060e043f1e410822"
UPSTREAM_REPOSITORY = "https://github.com/opendataval/opendataval"
UPSTREAM_SOURCE_URL = (
    f"{UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT}/"
    "opendataval/dataval/knnshap/knnshap.py"
)
UPSTREAM_ARCHIVE_SHA256 = (
    "e13ff293c86c51796445d0de3bb74b3511ab8cc994eb9496b01c2582e2689dd0"
)
UPSTREAM_SOURCE_SHA256 = (
    "9c66a528a1fa5e16c0bf2b2d7498d395a1a64c5ff9c59893a491d657e8f38177"
)
VENDORED_LICENSE_SHA256 = (
    "ca0f1acf7dc72429be8a2a62db250f45ed405faf97543444abe6c937103533b3"
)
COMPARISON_TOLERANCE = 1e-7


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_relative(path: Path, root: Path, label: str) -> str:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} must be inside repository root") from exc
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")
    return relative.as_posix()


def _load_upstream_class(source_path: Path) -> tuple[type[Any], types.ModuleType]:
    """Execute the unchanged upstream file while stubbing unrelated package plumbing."""

    import torch  # Imported lazily so core verification does not require PyTorch.

    class DataEvaluator:
        pass

    class ModelLessMixin:
        embedding_model: Any

        def embeddings(self, *tensors: Any) -> tuple[Any, ...]:
            if getattr(self, "embedding_model", None) is not None:
                return tuple(self.embedding_model.predict(tensor) for tensor in tensors)
            return tensors

    class Model:
        pass

    packages: dict[str, types.ModuleType] = {}
    for name in ("opendataval", "opendataval.dataval", "opendataval.model"):
        package = types.ModuleType(name)
        package.__path__ = []  # type: ignore[attr-defined]
        packages[name] = package
    api = types.ModuleType("opendataval.dataval.api")
    api.DataEvaluator = DataEvaluator  # type: ignore[attr-defined]
    api.ModelLessMixin = ModelLessMixin  # type: ignore[attr-defined]
    model_api = types.ModuleType("opendataval.model.api")
    model_api.Model = Model  # type: ignore[attr-defined]
    injected = {
        **packages,
        "opendataval.dataval.api": api,
        "opendataval.model.api": model_api,
    }
    previous = {name: sys.modules.get(name) for name in injected}
    sys.modules.update(injected)
    try:
        spec = importlib.util.spec_from_file_location(
            "datamechbench_pinned_opendataval_knnshap", source_path
        )
        if spec is None or spec.loader is None:
            raise ValueError("unable to load pinned OpenDataVal source")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    if not hasattr(module, "KNNShapley"):
        raise ValueError("pinned OpenDataVal source does not define KNNShapley")
    if module.torch is not torch:
        raise ValueError("pinned source did not execute against the declared torch module")
    return module.KNNShapley, module


def _owner_dataset(case: dict[str, Any]) -> OwnerDataset:
    x_train = np.asarray(case["x_train"], dtype=float)
    y_train = np.asarray(case["y_train"], dtype=int)
    x_validation = np.asarray(case["x_validation"], dtype=float)
    y_validation = np.asarray(case["y_validation"], dtype=int)
    if x_train.ndim != 2 or x_validation.ndim != 2:
        raise ValueError("cross-check features must be two-dimensional")
    if len(x_train) != len(y_train) or len(x_validation) != len(y_validation):
        raise ValueError("cross-check feature/label lengths differ")
    if x_train.shape[1] != x_validation.shape[1]:
        raise ValueError("cross-check train/validation feature dimensions differ")
    owners = tuple(f"o{index}" for index in range(len(x_train)))
    return OwnerDataset(
        dataset_id=f"external-crosscheck-{case['case_id']}",
        source_shape=(len(x_train) + len(x_validation), x_train.shape[1]),
        train_indices=np.arange(len(x_train)),
        validation_indices=np.arange(len(x_validation)) + len(x_train),
        test_indices=np.asarray([], dtype=int),
        x_train=x_train,
        y_train=y_train,
        x_validation=x_validation,
        y_validation=y_validation,
        x_test=np.empty((0, x_train.shape[1]), dtype=float),
        y_test=np.asarray([], dtype=int),
        owner_rows={owner: (index,) for index, owner in enumerate(owners)},
        noise_rates={owner: 0.0 for owner in owners},
        dataset_hash=hashlib.sha256(
            json.dumps(case, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    )


def _one_hot(labels: np.ndarray, classes: tuple[int, ...]) -> np.ndarray:
    indices = {label: index for index, label in enumerate(classes)}
    result = np.zeros((len(labels), len(classes)), dtype=float)
    for row, label in enumerate(labels):
        result[row, indices[int(label)]] = 1.0
    return result


def _compare_case(
    upstream_class: type[Any], upstream_module: types.ModuleType, raw_case: Any
) -> dict[str, Any]:
    import torch

    if not isinstance(raw_case, dict):
        raise ValueError("cross-check case must be an object")
    dataset = _owner_dataset(raw_case)
    owners = dataset.owner_ids
    valuation_case = ValuationCase(
        case_id=str(raw_case["case_id"]),
        owner_ids=owners,
        utility=lambda coalition: float(len(tuple(coalition))),
        case_type="real_owner_data",
        metadata={"owner_dataset": dataset},
    )
    k = int(raw_case["k"])
    local = evaluate_model_based("knn_shapley", valuation_case, {"k": k}, seed=0)
    local_scores = [float(local.scores[owner]) for owner in owners]

    scaler = StandardScaler().fit(dataset.x_train)
    train = scaler.transform(dataset.x_train)
    validation = scaler.transform(dataset.x_validation)
    classes = tuple(
        int(value)
        for value in sorted(
            set(dataset.y_train.tolist()) | set(dataset.y_validation.tolist())
        )
    )
    upstream = upstream_class(k_neighbors=k, batch_size=max(len(train), len(validation)))
    upstream.x_train = torch.as_tensor(train, dtype=torch.float32)
    upstream.x_valid = torch.as_tensor(validation, dtype=torch.float32)
    upstream.y_train = torch.as_tensor(
        _one_hot(dataset.y_train, classes), dtype=torch.float32
    )
    upstream.y_valid = torch.as_tensor(
        _one_hot(dataset.y_validation, classes), dtype=torch.float32
    )
    original_tqdm = upstream_module.tqdm.tqdm
    upstream_module.tqdm.tqdm = lambda values: values
    try:
        upstream.train_data_values()
    finally:
        upstream_module.tqdm.tqdm = original_tqdm
    external_scores = [float(value) for value in upstream.evaluate_data_values()]
    maximum_error = max(
        abs(local_value - external_value)
        for local_value, external_value in zip(
            local_scores, external_scores, strict=True
        )
    )
    return {
        "case_id": valuation_case.case_id,
        "k": k,
        "owner_ids": list(owners),
        "local_scores": local_scores,
        "external_scores": external_scores,
        "maximum_absolute_error": maximum_error,
    }


def _binding(role: str, path: Path, root: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": _repository_relative(path, root, role),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def build_opendataval_knn_validation(
    *,
    source_path: str | Path = DEFAULT_SOURCE,
    license_path: str | Path = DEFAULT_LICENSE,
    fixture_path: str | Path = DEFAULT_FIXTURES,
    runner_path: str | Path,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Run both implementations, write byte-bound results, and emit the record."""

    import sklearn
    import torch
    import tqdm

    root = Path(repository_root)
    source = Path(source_path)
    license_file = Path(license_path)
    fixtures_file = Path(fixture_path)
    runner = Path(runner_path)
    output = Path(output_directory)
    for label, path in (
        ("source", source),
        ("license", license_file),
        ("fixtures", fixtures_file),
        ("runner", runner),
    ):
        _repository_relative(path, root, label)
    if _sha256(source) != UPSTREAM_SOURCE_SHA256:
        raise ValueError("pinned OpenDataVal source hash mismatch")
    if _sha256(license_file) != VENDORED_LICENSE_SHA256:
        raise ValueError("pinned OpenDataVal license hash mismatch")
    fixtures = json.loads(fixtures_file.read_text(encoding="utf-8"))
    if fixtures.get("schema_version") != "1.0" or fixtures.get(
        "fixture_kind"
    ) != "knn_shapley_external_crosscheck":
        raise ValueError("invalid external KNN fixture schema")
    cases = fixtures.get("cases")
    if not isinstance(cases, list) or len(cases) < 3:
        raise ValueError("external KNN cross-check requires at least three cases")
    upstream_class, upstream_module = _load_upstream_class(source)
    comparisons = [
        _compare_case(upstream_class, upstream_module, case) for case in cases
    ]
    maximum_error = max(
        float(item["maximum_absolute_error"]) for item in comparisons
    )
    result = {
        "schema_version": "1.0",
        "result_kind": "external_implementation_comparison",
        "validation_id": VALIDATION_ID,
        "method_id": "knn_shapley",
        "external_commit": UPSTREAM_COMMIT,
        "executed_source_sha256": _sha256(source),
        "upstream_archive_sha256": UPSTREAM_ARCHIVE_SHA256,
        "source_execution": "unchanged_upstream_file_with_minimal_api_import_shim",
        "execution_environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "torch": torch.__version__,
            "tqdm": tqdm.__version__,
        },
        "preprocessing_alignment": fixtures["preprocessing_alignment"],
        "tolerance": COMPARISON_TOLERANCE,
        "all_close": maximum_error <= COMPARISON_TOLERANCE,
        "maximum_absolute_error": maximum_error,
        "fixture_count": len(comparisons),
        "comparisons": comparisons,
    }
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "external_opendataval_knn_shapley_results_v1.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    record = {
        "schema_version": "1.0",
        "record_kind": "external_implementation_validation",
        "validation_id": VALIDATION_ID,
        "method_id": "knn_shapley",
        "track": "valuation",
        "claim_boundary": "algorithm_core_with_declared_preprocessing_alignment",
        "external_implementation": {
            "name": "OpenDataVal KNNShapley",
            "origin": "official_upstream",
            "repository_url": UPSTREAM_REPOSITORY,
            "commit_sha": UPSTREAM_COMMIT,
            "source_url": UPSTREAM_SOURCE_URL,
            "source_sha256": UPSTREAM_SOURCE_SHA256,
            "archive_sha256": UPSTREAM_ARCHIVE_SHA256,
            "license_id": "MIT",
        },
        "artifacts": [
            _binding("external_source", source, root),
            _binding("external_license", license_file, root),
            _binding("comparison_fixtures", fixtures_file, root),
            _binding("comparison_results", result_path, root),
            _binding("validation_runner", runner, root),
        ],
    }
    record_path = output / "external_opendataval_knn_shapley_v1.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "DEFAULT_FIXTURES",
    "DEFAULT_LICENSE",
    "DEFAULT_OUTPUT_DIRECTORY",
    "DEFAULT_SOURCE",
    "REPOSITORY_ROOT",
    "build_opendataval_knn_validation",
]
