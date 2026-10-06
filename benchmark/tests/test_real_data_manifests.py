from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml
from datamechbench.game_builders.real_data import (
    ALLOWED_SPLIT_SEEDS,
    RealDatasetBundle,
    audit_split_isolation,
    canonical_dataset_hash,
    deterministic_cap,
    load_real_dataset,
    source_inventory_record,
    split_and_partition,
    write_source_inventory,
)
from datamechbench.game_builders.real_sources import (
    SourcePolicy,
    declared_real_sources,
    resolve_source,
)
from datamechbench.game_builders.run_config import expand_real_game_matrix
from datamechbench.settings.valuation_real import real_valuation_settings

EXPECTED_SOURCES = {
    "breast_cancer": ("tabular", "classification", "sklearn:load_breast_cancer"),
    "wine": ("tabular", "classification", "sklearn:load_wine"),
    "adult": ("tabular", "classification", "openml:data_id=1590"),
    "california_housing": ("tabular", "regression", "sklearn:fetch_california_housing"),
    "diabetes": ("tabular", "regression", "sklearn:load_diabetes"),
    "digits": ("image", "classification", "sklearn:load_digits"),
    "ag_news": ("text", "classification", "huggingface:ag_news"),
    "20newsgroups": ("text", "classification", "sklearn:fetch_20newsgroups"),
    "fashion_mnist": ("image", "classification", "torchvision:FashionMNIST"),
    "cifar10_subset": ("image", "classification", "torchvision:CIFAR10"),
}


def _bundle(*, task: str = "classification", n: int = 240) -> RealDatasetBundle:
    rng = np.random.default_rng(7)
    features = rng.normal(size=(n, 5)).astype(np.float32)
    targets = (
        np.asarray([index % 4 for index in range(n)], dtype=np.int64)
        if task == "classification"
        else np.linspace(-2.0, 3.0, n, dtype=np.float64)
    )
    source = declared_real_sources()["breast_cancer" if task == "classification" else "diabetes"]
    row_ids = tuple(f"row-{index:04d}" for index in range(n))
    return RealDatasetBundle.create(source, features, targets, row_ids=row_ids)


def test_source_catalog_pins_all_ten_real_datasets_and_licenses() -> None:
    sources = declared_real_sources()
    assert set(sources) == set(EXPECTED_SOURCES)
    for dataset_id, (modality, task, canonical_source) in EXPECTED_SOURCES.items():
        record = sources[dataset_id]
        assert (record.modality, record.task, record.canonical_source) == (
            modality,
            task,
            canonical_source,
        )
        assert record.license_id
        assert record.loader_id


def test_real_game_matrix_has_all_development_partitions_and_frozen_holdouts() -> None:
    cells = expand_real_game_matrix(real_valuation_settings())
    development = [cell for cell in cells if cell.evidence_split == "development"]
    confirmatory = [cell for cell in cells if cell.evidence_split == "confirmatory"]

    assert len(development) == 24
    assert {
        (cell.dataset_id, cell.partition, cell.split_seed) for cell in development
    } == {
        (setting.dataset_id, partition, {"iid": 11, "label_skew": 29, "quantity_skew": 47}[partition])
        for setting in real_valuation_settings()
        if setting.evidence_split == "development"
        for partition in ("iid", "label_skew", "quantity_skew")
    }
    assert {(cell.dataset_id, cell.partition, cell.split_seed) for cell in confirmatory} == {
        ("fashion_mnist", "label_skew", 29),
        ("cifar10_subset", "iid", 11),
    }
    assert {cell.dataset_id for cell in development} >= {
        "adult", "ag_news", "20newsgroups"
    }


def test_real_game_matrix_preserves_structured_partition_na_reason() -> None:
    [adult] = [
        setting for setting in real_valuation_settings() if setting.dataset_id == "adult"
    ]
    cells = expand_real_game_matrix(
        (adult,),
        unavailable_partitions={
            ("adult", "label_skew"): "fewer_than_eight_nonempty_label_shards"
        },
    )
    label_cell = next(cell for cell in cells if cell.partition == "label_skew")

    assert label_cell.status == "not_applicable"
    assert label_cell.reason == "fewer_than_eight_nonempty_label_shards"
    assert len(cells) == 3


def test_source_policy_rejects_undeclared_or_unapproved_replacements() -> None:
    policy = SourcePolicy(allow_download=False, replacements={})
    with pytest.raises(KeyError, match="undeclared real dataset"):
        resolve_source("made_up", policy)
    with pytest.raises(ValueError, match="not an allowed replacement"):
        resolve_source(
            "adult",
            SourcePolicy(allow_download=False, replacements={"adult": "digits"}),
        )
    replacement = resolve_source(
        "adult",
        SourcePolicy(allow_download=False, replacements={"adult": "adult_uci_mirror"}),
    )
    assert replacement.canonical_source.startswith("uci:")
    assert replacement.replaces == "adult"


def test_source_yaml_matches_runtime_catalog() -> None:
    path = Path(__file__).parents[1] / "configs" / "elr_vrds_real_sources.yaml"
    payload = yaml.safe_load(path.read_text())
    assert set(payload["sources"]) == set(EXPECTED_SOURCES)
    assert payload["split_seeds"] == [11, 29, 47]
    assert payload["caps"]["large"] == 6000
    assert payload["replacement_policy"]["ag_news"] == ["20newsgroups"]


def test_canonical_hash_changes_with_array_row_source_or_package_metadata() -> None:
    bundle = _bundle(n=32)
    same = RealDatasetBundle.create(
        bundle.source, bundle.features.copy(), bundle.targets.copy(), row_ids=bundle.row_ids
    )
    changed_features = bundle.features.copy()
    changed_features[0, 0] += 1.0
    changed_source = replace(bundle.source, package_version="different")
    assert bundle.dataset_hash == same.dataset_hash
    assert bundle.dataset_hash != canonical_dataset_hash(
        changed_features, bundle.targets, bundle.row_ids, bundle.source
    )
    assert bundle.dataset_hash != canonical_dataset_hash(
        bundle.features, bundle.targets, ("changed", *bundle.row_ids[1:]), bundle.source
    )
    assert bundle.dataset_hash != canonical_dataset_hash(
        bundle.features, bundle.targets, bundle.row_ids, changed_source
    )


@pytest.mark.parametrize("task", ["classification", "regression"])
def test_deterministic_cap_is_stable_and_target_aware(task: str) -> None:
    bundle = _bundle(task=task, n=240)
    first = deterministic_cap(bundle, cap=120, seed=20260930)
    second = deterministic_cap(bundle, cap=120, seed=20260930)
    assert first.row_ids == second.row_ids
    assert first.dataset_hash == second.dataset_hash
    assert len(first.row_ids) == 120
    assert set(first.row_ids).issubset(bundle.row_ids)
    if task == "classification":
        assert set(first.targets.tolist()) == set(bundle.targets.tolist())


@pytest.mark.parametrize("seed", sorted(ALLOWED_SPLIT_SEEDS))
@pytest.mark.parametrize("partition", ["iid", "label_skew", "quantity_skew"])
def test_real_split_and_owner_partition_are_complete_disjoint_and_deterministic(
    seed: int, partition: str
) -> None:
    bundle = _bundle(n=240)
    kwargs = dict(
        setting_id="real-fixture-n8",
        n_owners=8,
        split_seed=seed,
        partition=partition,
        imbalance_ratio=4 if partition == "quantity_skew" else 1,
    )
    first = split_and_partition(bundle, **kwargs)
    second = split_and_partition(bundle, **kwargs)
    assert first.content_hash == second.content_hash
    train = set(first.train_row_ids)
    validation = set(first.validation_row_ids)
    test = set(first.test_row_ids)
    assert not train & validation
    assert not train & test
    assert not validation & test
    assert train | validation | test == set(bundle.row_ids)
    owner_rows = [row for rows in first.owner_row_ids.values() for row in rows]
    assert set(owner_rows) == train
    assert len(owner_rows) == len(set(owner_rows))
    assert set(first.owner_row_ids) == {f"o{index}" for index in range(8)}
    assert set(first.transform_fit_row_ids).issubset(train)
    assert audit_split_isolation(first) == ()


def test_regression_split_uses_quantile_strata_without_changing_targets() -> None:
    bundle = _bundle(task="regression", n=240)
    manifest = split_and_partition(
        bundle,
        setting_id="real-regression-n8",
        n_owners=8,
        split_seed=11,
        partition="iid",
        imbalance_ratio=1,
    )
    assert manifest.task == "regression"
    assert manifest.stratification == "target_quantiles_10"
    assert bundle.targets.dtype == np.float64
    assert audit_split_isolation(manifest) == ()


def test_split_audit_detects_test_leakage_and_invalid_seed() -> None:
    bundle = _bundle(n=240)
    with pytest.raises(ValueError, match="split_seed"):
        split_and_partition(
            bundle,
            setting_id="bad-seed",
            n_owners=8,
            split_seed=13,
            partition="iid",
            imbalance_ratio=1,
        )
    manifest = split_and_partition(
        bundle,
        setting_id="leak-check",
        n_owners=8,
        split_seed=11,
        partition="iid",
        imbalance_ratio=1,
    )
    leaked = replace(
        manifest,
        transform_fit_row_ids=(
            *manifest.transform_fit_row_ids,
            manifest.test_row_ids[0],
        ),
    )
    assert "transform_fit_rows_outside_train" in audit_split_isolation(leaked)


def test_source_inventory_is_portable_and_contains_no_arrays(tmp_path: Path) -> None:
    bundle = _bundle(n=32)
    record = source_inventory_record(bundle)
    assert record["dataset_hash"] == bundle.dataset_hash
    assert record["row_count"] == 32
    assert record["feature_shape"] == [32, 5]
    assert "features" not in record and "targets" not in record
    target = write_source_inventory((record,), tmp_path / "inventory.json")
    payload = yaml.safe_load(target.read_text())
    assert payload["schema_version"] == "1.0"
    assert payload["datasets"] == [record]


def test_adult_loader_replays_a_local_openml_arff_without_network(tmp_path: Path) -> None:
    (tmp_path / "adult.arff").write_text(
        """@RELATION adult
@ATTRIBUTE age NUMERIC
@ATTRIBUTE workclass {Private,Public}
@ATTRIBUTE class {<=50K,>50K}
@DATA
25,Private,<=50K
41,Public,>50K
33,Private,<=50K
52,Public,>50K
"""
    )
    bundle = load_real_dataset(
        "adult",
        cache_dir=tmp_path,
        cap=None,
        source_policy=SourcePolicy(allow_download=False),
    )
    assert bundle.features.shape == (4, 2)
    assert bundle.targets.tolist() == ["<=50K", ">50K", "<=50K", ">50K"]
    assert bundle.metadata["retrieval_artifacts"][0]["sha256"]


def test_ag_news_loader_replays_local_parquet_without_network(tmp_path: Path) -> None:
    import pandas as pd

    pd.DataFrame({"text": ["alpha", "beta"], "label": [0, 1]}).to_parquet(
        tmp_path / "ag_news_train.parquet"
    )
    pd.DataFrame({"text": ["gamma", "delta"], "label": [1, 0]}).to_parquet(
        tmp_path / "ag_news_test.parquet"
    )
    bundle = load_real_dataset(
        "ag_news",
        cache_dir=tmp_path,
        cap=None,
        source_policy=SourcePolicy(allow_download=False),
    )
    assert bundle.features.tolist() == ["alpha", "beta", "gamma", "delta"]
    assert bundle.targets.tolist() == [0, 1, 1, 0]
    assert len(bundle.metadata["retrieval_artifacts"]) == 2


def test_cifar_loader_replays_local_parquet_without_network(tmp_path: Path) -> None:
    from io import BytesIO

    import pandas as pd
    from PIL import Image

    def image_bytes(value: int) -> bytes:
        target = BytesIO()
        Image.fromarray(np.full((32, 32, 3), value, dtype=np.uint8)).save(
            target, format="PNG"
        )
        return target.getvalue()

    for split, values in (("train", (5, 25)), ("test", (100, 200))):
        pd.DataFrame(
            {
                "img": [{"bytes": image_bytes(value), "path": None} for value in values],
                "label": [0, 1],
            }
        ).to_parquet(tmp_path / f"cifar10_{split}.parquet")
    bundle = load_real_dataset(
        "cifar10_subset",
        cache_dir=tmp_path,
        cap=None,
        source_policy=SourcePolicy(allow_download=False),
    )
    assert bundle.features.shape == (4, 32, 32, 3)
    assert bundle.targets.tolist() == [0, 1, 0, 1]
    assert int(bundle.features[2, 0, 0, 0]) == 100
