from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from datamechbench.game_builders.real_coalitions import (
    build_real_coalition_tables,
    classification_utility,
    regression_utility,
)
from datamechbench.game_builders.real_data import RealDatasetBundle, split_and_partition
from datamechbench.game_builders.real_features import PublicFeatureConfig, extract_public_features
from datamechbench.game_builders.real_models import ModelTrajectoryConfig
from datamechbench.game_builders.real_sources import declared_real_sources


def test_real_utility_definitions_pin_empty_and_negative_direction() -> None:
    labels = np.asarray([0, 1, 2, 1])
    uniform = np.full((4, 3), 1 / 3)
    assert classification_utility(uniform, labels, n_classes=3) == pytest.approx(0.0)
    confident_wrong = np.full((4, 3), 0.05)
    confident_wrong[:, 0] = 0.9
    assert classification_utility(confident_wrong, labels, n_classes=3) < 0
    targets = np.asarray([1.0, -2.0, 3.0])
    assert regression_utility(np.zeros(3), targets) == pytest.approx(-14 / 3)


def test_paired_tables_are_complete_and_train_one_high_trajectory_per_coalition(
    tmp_path: Path,
) -> None:
    rng = np.random.default_rng(5)
    ninety = 90
    features = rng.integers(0, 17, size=(ninety, 64)).astype(np.float32)
    targets = np.repeat(np.asarray([0, 1, 2]), ninety // 3)
    source = declared_real_sources()["digits"]
    bundle = RealDatasetBundle.create(source, features, targets)
    manifest = split_and_partition(
        bundle,
        setting_id="tiny-real",
        n_owners=3,
        split_seed=11,
        partition="iid",
        imbalance_ratio=1,
    )
    artifact = extract_public_features(
        bundle,
        PublicFeatureConfig(kind="digits_raw", transform_id="digits-div16-v1"),
        cache_dir=tmp_path / "features",
        device="cpu",
    )
    tables = build_real_coalition_tables(
        manifest,
        artifact,
        ModelTrajectoryConfig(
            model_family="tree_ensemble",
            task="classification",
            global_classes=(0, 1, 2),
        ),
        cache_dir=tmp_path / "coalitions",
        device="cpu",
    )
    assert set(tables.tables) == {"low", "medium", "high"}
    assert tables.trajectory_builds == 7
    assert set(tables.records) == set(range(8))
    expected_masks = set(range(8))
    for table in tables.tables.values():
        assert set(table.values) == expected_masks
        assert table.values[0] == pytest.approx(0.0)
    assert {tuple(table.values) for table in tables.tables.values()} == {
        tuple(range(8))
    }

    resumed = build_real_coalition_tables(
        manifest,
        artifact,
        ModelTrajectoryConfig(
            model_family="tree_ensemble",
            task="classification",
            global_classes=(0, 1, 2),
        ),
        cache_dir=tmp_path / "coalitions",
        device="cpu",
    )
    assert resumed.trajectory_builds == 0
    assert resumed.content_hash == tables.content_hash

    record_path = next((tmp_path / "coalitions" / tables.input_hash / "coalitions").glob("*.json"))
    payload = json.loads(record_path.read_text())
    payload["input_hash"] = "stale"
    record_path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="input hash mismatch"):
        build_real_coalition_tables(
            manifest,
            artifact,
            ModelTrajectoryConfig(
                model_family="tree_ensemble",
                task="classification",
                global_classes=(0, 1, 2),
            ),
            cache_dir=tmp_path / "coalitions",
            device="cpu",
        )
