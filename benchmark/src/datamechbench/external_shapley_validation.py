"""Cross-check exact Shapley against the pinned S-SVARM ground-truth code."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import sys
import types
import warnings
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from .models import ValuationCase
from .runner import build_registry

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
DEFAULT_EXTERNAL_DIRECTORY = PACKAGE_ROOT / "external" / "svarm_official"
DEFAULT_FIXTURES = DEFAULT_EXTERNAL_DIRECTORY / "exact_shapley_fixtures.json"
DEFAULT_OUTPUT_DIRECTORY = PACKAGE_ROOT / "evidence"

VALIDATION_ID = "svarm-ground-truth-exact-shapley-c4e30395"
UPSTREAM_COMMIT = "c4e30395b14b8bf9a8687d839d5b406f825bb23d"
UPSTREAM_REPOSITORY = (
    "https://github.com/kolpaczki/"
    "Approximating-the-Shapley-Value-without-Marginal-Contributions"
)
UPSTREAM_SOURCE_URL = (
    f"{UPSTREAM_REPOSITORY}/blob/{UPSTREAM_COMMIT}/"
    "ApproxMethods/GroundTruth/ExhaustiveSearch.py"
)
UPSTREAM_ARCHIVE_SHA256 = (
    "72a62cb98ac15816b5185b8c6b3d03d7bd2ee176b468eb80cf251b840aa66f2a"
)
COMPARISON_TOLERANCE = 1e-12

SOURCE_FILES: Mapping[str, tuple[str, str]] = {
    "external_source": (
        "ApproxMethods/GroundTruth/ExhaustiveSearch.py",
        "c6a4abb155ce448c10ad01c7adc416d835087e488d8827d181d764d03542b67c",
    ),
    "external_dependency_abstract_approximation": (
        "ApproxMethods/AbstractApproxMethod.py",
        "3de1d9afb3f2e1187729841a59de67b7e1d2f9c3806c85aab073a9d52915e40e",
    ),
    "external_dependency_experiment_storage": (
        "Experiment/ExperimentData.py",
        "bff4695d2d4ad2c833fae74ca13399f30e773856d9a16c5fa25cb7e3c8ae731e",
    ),
    "external_dependency_utils": (
        "utils/utils.py",
        "d2f7027c612247f209ad4d14880b91c10a67b799c9e46be5aaafdf01cb70dcf2",
    ),
}
LICENSE_SHA256 = "c6d82091d98d3c9a4f908d07042f2191242063fd7db363d786f8016d250b7e8e"


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


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError(f"unable to load pinned upstream module: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_upstream_class(external_directory: Path) -> type[Any]:
    """Execute all algorithmically relevant upstream files without rewriting them."""

    package_names = (
        "Games",
        "utils",
        "Experiment",
        "ApproxMethods",
        "ApproxMethods.GroundTruth",
    )
    module_names = (
        "Games.AbstractGame",
        "utils.utils",
        "Experiment.ExperimentData",
        "ApproxMethods.AbstractApproxMethod",
        "ApproxMethods.GroundTruth.ExhaustiveSearch",
    )
    names = (*package_names, *module_names)
    previous = {name: sys.modules.get(name) for name in names}
    try:
        for name in package_names:
            package = types.ModuleType(name)
            package.__path__ = []  # type: ignore[attr-defined]
            sys.modules[name] = package
        abstract_game = types.ModuleType("Games.AbstractGame")

        class BaseGame:
            pass

        abstract_game.BaseGame = BaseGame  # type: ignore[attr-defined]
        sys.modules["Games.AbstractGame"] = abstract_game
        _load_module("utils.utils", external_directory / "utils/utils.py")
        _load_module(
            "Experiment.ExperimentData",
            external_directory / "Experiment/ExperimentData.py",
        )
        _load_module(
            "ApproxMethods.AbstractApproxMethod",
            external_directory / "ApproxMethods/AbstractApproxMethod.py",
        )
        module = _load_module(
            "ApproxMethods.GroundTruth.ExhaustiveSearch",
            external_directory / "ApproxMethods/GroundTruth/ExhaustiveSearch.py",
        )
        upstream_class = module.ExhaustiveSearch
    finally:
        for name, original in previous.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original
    return upstream_class


def _finite_float(raw: Any, label: str) -> float:
    if isinstance(raw, bool):
        raise ValueError(f"{label} must be finite")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite")
    return value


def _parse_case(raw_case: Any) -> dict[str, Any]:
    if not isinstance(raw_case, Mapping):
        raise ValueError("exact Shapley cross-check case must be an object")
    case_id = str(raw_case.get("case_id", "")).strip()
    owners = tuple(str(value) for value in raw_case.get("owner_ids", ()))
    if not case_id or not owners or len(set(owners)) != len(owners):
        raise ValueError("exact Shapley fixture has invalid case or owner IDs")
    additive_raw = raw_case.get("additive_values")
    if not isinstance(additive_raw, Mapping) or set(additive_raw) != set(owners):
        raise ValueError(f"additive values must cover every owner: {case_id}")
    additive = {
        owner: _finite_float(additive_raw[owner], f"additive value {owner}")
        for owner in owners
    }
    interactions: list[tuple[frozenset[str], float]] = []
    for index, raw_interaction in enumerate(raw_case.get("interactions", ())):
        if not isinstance(raw_interaction, Mapping):
            raise ValueError(f"invalid interaction {index}: {case_id}")
        members = frozenset(str(value) for value in raw_interaction.get("members", ()))
        if not members or not members <= set(owners):
            raise ValueError(f"invalid interaction members {index}: {case_id}")
        interactions.append(
            (members, _finite_float(raw_interaction.get("value"), "interaction value"))
        )
    return {
        "case_id": case_id,
        "owner_ids": owners,
        "base_value": _finite_float(raw_case.get("base_value", 0.0), "base value"),
        "additive_values": additive,
        "interactions": interactions,
        **{
            key: [_finite_float(value, key) for value in raw_case[key]]
            for key in (
                "expected_scores",
                "expected_local_scores",
                "expected_external_scores",
            )
            if key in raw_case
        },
        "declared_difference": str(raw_case.get("declared_difference", "")),
    }


def _utility(case: Mapping[str, Any], coalition: Any) -> float:
    selected = frozenset(str(value) for value in coalition)
    result = float(case["base_value"])
    additive = case["additive_values"]
    result += sum(float(additive[owner]) for owner in selected)
    result += sum(
        value for members, value in case["interactions"] if members <= selected
    )
    return result


class _FixtureGame:
    def __init__(self, case: Mapping[str, Any]) -> None:
        self.case = case
        self.owners = tuple(case["owner_ids"])

    def get_player_number(self) -> int:
        return len(self.owners)

    def get_value(self, players: Any) -> float:
        return _utility(self.case, (self.owners[int(index)] for index in players))


def _score_vectors(
    upstream_class: type[Any], case: Mapping[str, Any]
) -> tuple[list[float], list[float]]:
    owners = tuple(case["owner_ids"])
    valuation_case = ValuationCase(
        case_id=str(case["case_id"]),
        owner_ids=owners,
        utility=lambda coalition: _utility(case, coalition),
        case_type="analytic",
    )
    local_output = build_registry().create(
        "shapley_exact", {"max_records": len(owners)}
    ).evaluate(valuation_case, 0)
    local_scores = [float(local_output.scores[owner]) for owner in owners]
    upstream = upstream_class()
    upstream.reset(
        game=_FixtureGame(case), budget=1, evaluation_penalty=0, step_size=1
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        external_values = upstream.compute_exact_shapley_values()
    external_scores = [float(value) for value in external_values]
    return local_scores, external_scores


def _compare_case(upstream_class: type[Any], raw_case: Any) -> dict[str, Any]:
    case = _parse_case(raw_case)
    expected = case.get("expected_scores")
    owners = tuple(case["owner_ids"])
    if not isinstance(expected, list) or len(expected) != len(owners):
        raise ValueError(f"expected scores must cover every owner: {case['case_id']}")
    local_scores, external_scores = _score_vectors(upstream_class, case)
    maximum_error = max(
        abs(local - external)
        for local, external in zip(local_scores, external_scores, strict=True)
    )
    oracle_error = max(
        abs(observed - target)
        for scores in (local_scores, external_scores)
        for observed, target in zip(scores, expected, strict=True)
    )
    return {
        "case_id": case["case_id"],
        "owner_ids": list(owners),
        "local_scores": local_scores,
        "external_scores": external_scores,
        "expected_scores": expected,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": oracle_error,
    }


def _compare_boundary(upstream_class: type[Any], raw_case: Any) -> dict[str, Any]:
    case = _parse_case(raw_case)
    owners = tuple(case["owner_ids"])
    expected_local = case.get("expected_local_scores")
    expected_external = case.get("expected_external_scores")
    if (
        not isinstance(expected_local, list)
        or not isinstance(expected_external, list)
        or len(expected_local) != len(owners)
        or len(expected_external) != len(owners)
        or not case["declared_difference"]
    ):
        raise ValueError(f"invalid boundary oracle: {case['case_id']}")
    local_scores, external_scores = _score_vectors(upstream_class, case)
    difference = max(
        abs(local - external)
        for local, external in zip(local_scores, external_scores, strict=True)
    )
    oracle_error = max(
        abs(observed - expected)
        for scores, targets in (
            (local_scores, expected_local),
            (external_scores, expected_external),
        )
        for observed, expected in zip(scores, targets, strict=True)
    )
    return {
        "case_id": case["case_id"],
        "status": "expected_semantic_boundary",
        "declared_difference": case["declared_difference"],
        "owner_ids": list(owners),
        "local_scores": local_scores,
        "external_scores": external_scores,
        "expected_local_scores": expected_local,
        "expected_external_scores": expected_external,
        "maximum_absolute_difference": difference,
        "matches_declared_difference": oracle_error <= COMPARISON_TOLERANCE,
    }


def _binding(role: str, path: Path, root: Path) -> dict[str, Any]:
    return {
        "role": role,
        "path": _repository_relative(path, root, role),
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def build_svarm_exact_shapley_validation(
    *,
    external_directory: str | Path = DEFAULT_EXTERNAL_DIRECTORY,
    fixture_path: str | Path = DEFAULT_FIXTURES,
    runner_path: str | Path,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    repository_root: str | Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    """Execute pinned independent code and emit byte-bound evidence records."""

    import scipy

    root = Path(repository_root)
    external = Path(external_directory)
    fixtures_file = Path(fixture_path)
    runner = Path(runner_path)
    output = Path(output_directory)
    source_paths: dict[str, Path] = {}
    for role, (relative, expected_hash) in SOURCE_FILES.items():
        path = external / relative
        _repository_relative(path, root, role)
        if _sha256(path) != expected_hash:
            raise ValueError(f"pinned S-SVARM source hash mismatch: {path.name}")
        source_paths[role] = path
    license_file = external / "LICENSE"
    for label, path in (
        ("license", license_file),
        ("fixtures", fixtures_file),
        ("runner", runner),
    ):
        _repository_relative(path, root, label)
    if _sha256(license_file) != LICENSE_SHA256:
        raise ValueError("pinned S-SVARM license hash mismatch")

    fixtures = json.loads(fixtures_file.read_text(encoding="utf-8"))
    if fixtures.get("schema_version") != "1.0" or fixtures.get(
        "fixture_kind"
    ) != "exact_shapley_external_crosscheck":
        raise ValueError("invalid external exact-Shapley fixture schema")
    shared_cases = fixtures.get("shared_cases")
    boundary_cases = fixtures.get("boundary_cases")
    if not isinstance(shared_cases, list) or len(shared_cases) < 3:
        raise ValueError("exact-Shapley cross-check requires at least three shared cases")
    if not isinstance(boundary_cases, list) or not boundary_cases:
        raise ValueError("exact-Shapley cross-check requires a semantic boundary case")

    upstream_class = _load_upstream_class(external)
    comparisons = [_compare_case(upstream_class, case) for case in shared_cases]
    boundaries = [_compare_boundary(upstream_class, case) for case in boundary_cases]
    maximum_error = max(float(item["maximum_absolute_error"]) for item in comparisons)
    oracle_error = max(
        float(item["maximum_fixture_oracle_error"]) for item in comparisons
    )
    executed_sources = {
        role: _sha256(path) for role, path in source_paths.items()
    }
    result = {
        "schema_version": "1.0",
        "result_kind": "external_implementation_comparison",
        "validation_id": VALIDATION_ID,
        "method_id": "shapley_exact",
        "external_commit": UPSTREAM_COMMIT,
        "executed_source_sha256": executed_sources["external_source"],
        "executed_source_files": executed_sources,
        "upstream_archive_sha256": UPSTREAM_ARCHIVE_SHA256,
        "source_execution": "unchanged_upstream_files_with_import_shims",
        "execution_environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "claim_boundary": "finite normalized characteristic games with v(empty)=0",
        "tolerance": COMPARISON_TOLERANCE,
        "all_close": maximum_error <= COMPARISON_TOLERANCE,
        "maximum_absolute_error": maximum_error,
        "maximum_fixture_oracle_error": oracle_error,
        "fixture_count": len(comparisons),
        "comparisons": comparisons,
        "boundary_fixture_count": len(boundaries),
        "boundary_comparisons": boundaries,
    }
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "external_svarm_exact_shapley_results_v1.json"
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    record = {
        "schema_version": "1.0",
        "record_kind": "external_implementation_validation",
        "validation_id": VALIDATION_ID,
        "method_id": "shapley_exact",
        "track": "valuation",
        "claim_boundary": (
            "exact characteristic-value core on finite normalized games; "
            "nonzero-empty behavior retained as a disclosed boundary"
        ),
        "external_implementation": {
            "name": "S-SVARM repository ExhaustiveSearch ground truth",
            "origin": "independent_reimplementation",
            "repository_url": UPSTREAM_REPOSITORY,
            "commit_sha": UPSTREAM_COMMIT,
            "source_url": UPSTREAM_SOURCE_URL,
            "source_sha256": SOURCE_FILES["external_source"][1],
            "archive_sha256": UPSTREAM_ARCHIVE_SHA256,
            "license_id": "MIT",
        },
        "artifacts": [
            *[
                _binding(role, path, root)
                for role, path in source_paths.items()
            ],
            _binding("external_license", license_file, root),
            _binding("comparison_fixtures", fixtures_file, root),
            _binding("comparison_results", result_path, root),
            _binding("validation_runner", runner, root),
        ],
    }
    record_path = output / "external_svarm_exact_shapley_v1.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


__all__ = [
    "DEFAULT_EXTERNAL_DIRECTORY",
    "DEFAULT_FIXTURES",
    "DEFAULT_OUTPUT_DIRECTORY",
    "REPOSITORY_ROOT",
    "build_svarm_exact_shapley_validation",
]
