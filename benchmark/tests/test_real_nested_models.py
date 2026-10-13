from __future__ import annotations

import numpy as np
from datamechbench.game_builders.real_data import RealDatasetBundle
from datamechbench.game_builders.real_features import (
    PublicFeatureConfig,
    extract_public_features,
    feature_cache_key,
)
from datamechbench.game_builders.real_models import (
    ModelTrajectoryConfig,
    build_trajectory,
)
from datamechbench.game_builders.real_sources import declared_real_sources
from numpy.testing import assert_array_equal


def _classification_data() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(19)
    features = rng.normal(size=(96, 7))
    targets = np.repeat(np.asarray([0, 1, 2], dtype=np.int64), 32)
    return features, targets, rng.normal(size=(21, 7))


def test_forest_predictions_are_exact_prefixes_of_one_high_forest() -> None:
    features, targets, evaluation = _classification_data()
    config = ModelTrajectoryConfig(
        model_family="tree_ensemble",
        task="classification",
        global_classes=(0, 1, 2, 3),
    )
    trajectory = build_trajectory(
        config, (features, targets), evaluation, seed=29, device="cpu"
    )
    assert tuple(trajectory.predictions) == ("low", "medium", "high")
    assert [trajectory.predictions[name].capacity for name in trajectory.predictions] == [
        16,
        48,
        128,
    ]
    assert trajectory.predictions["high"].values.shape == (21, 4)

    for name, count in (("low", 16), ("medium", 48), ("high", 128)):
        local = np.mean(
            [tree.predict_proba(evaluation) for tree in trajectory.estimator.estimators_[:count]],
            axis=0,
        )
        manual = np.zeros((len(evaluation), 4), dtype=np.float64)
        manual[:, :3] = local
        assert_array_equal(trajectory.predictions[name].values, manual)


def test_forest_cpu_replay_is_bitwise_deterministic() -> None:
    features, targets, evaluation = _classification_data()
    config = ModelTrajectoryConfig(
        model_family="tree_ensemble",
        task="classification",
        global_classes=(0, 1, 2, 3),
    )
    first = build_trajectory(config, (features, targets), evaluation, seed=47, device="cpu")
    second = build_trajectory(config, (features, targets), evaluation, seed=47, device="cpu")
    for name in first.predictions:
        assert_array_equal(first.predictions[name].values, second.predictions[name].values)


def test_boosting_predictions_are_stages_from_one_high_trajectory() -> None:
    rng = np.random.default_rng(23)
    features = rng.normal(size=(120, 6))
    targets = features[:, 0] - 0.4 * features[:, 1] + 0.1 * rng.normal(size=120)
    evaluation = rng.normal(size=(17, 6))
    config = ModelTrajectoryConfig(model_family="boosting", task="regression")
    trajectory = build_trajectory(
        config, (features, targets), evaluation, seed=11, device="cpu"
    )
    stages = list(trajectory.estimator.staged_predict(evaluation))
    for name, count in (("low", 20), ("medium", 60), ("high", 120)):
        assert_array_equal(trajectory.predictions[name].values, stages[count - 1])


def test_boosting_keeps_global_output_width_when_a_class_is_missing() -> None:
    features, targets, evaluation = _classification_data()
    config = ModelTrajectoryConfig(
        model_family="boosting",
        task="classification",
        global_classes=(0, 1, 2, 3),
    )
    trajectory = build_trajectory(
        config, (features, targets), evaluation, seed=11, device="cpu"
    )
    for prediction in trajectory.predictions.values():
        assert prediction.values.shape == (len(evaluation), 4)
        assert_array_equal(prediction.values[:, 3], np.zeros(len(evaluation)))


def test_boosting_single_class_coalition_is_finite_and_keeps_family_prefixes() -> None:
    rng = np.random.default_rng(41)
    features = rng.normal(size=(24, 5))
    targets = np.full(24, 2, dtype=np.int64)
    evaluation = rng.normal(size=(9, 5))
    trajectory = build_trajectory(
        ModelTrajectoryConfig(
            model_family="boosting",
            task="classification",
            global_classes=(0, 1, 2, 3),
        ),
        (features, targets),
        evaluation,
        seed=29,
        device="cpu",
    )
    assert trajectory.estimator.family == "degenerate_gradient_boosting"
    for prediction in trajectory.predictions.values():
        assert prediction.values.shape == (9, 4)
        assert np.isfinite(prediction.values).all()
        assert_array_equal(prediction.values[:, 2], np.ones(9))


def test_neural_head_checkpoints_are_epoch_prefixes_and_replay_on_cpu() -> None:
    rng = np.random.default_rng(31)
    features = rng.normal(size=(90, 12)).astype(np.float32)
    targets = np.repeat(np.asarray([0, 1, 2], dtype=np.int64), 30)
    evaluation = rng.normal(size=(13, 12)).astype(np.float32)
    config = ModelTrajectoryConfig(
        model_family="neural_head",
        task="classification",
        global_classes=(0, 1, 2, 3),
    )
    first = build_trajectory(
        config, (features, targets), evaluation, seed=11, device="cpu"
    )
    second = build_trajectory(
        config, (features, targets), evaluation, seed=11, device="cpu"
    )
    assert first.checkpoint_epochs == {"low": 1, "medium": 3, "high": 6}
    assert set(first.checkpoints) == {"low", "medium", "high"}
    assert first.checkpoint_hashes == second.checkpoint_hashes
    for name in first.predictions:
        assert first.predictions[name].values.shape == (13, 4)
        assert_array_equal(first.predictions[name].values, second.predictions[name].values)
        assert first.predictions[name].checkpoint_hash == first.checkpoint_hashes[name]


def test_medium_neural_trajectory_stops_early_and_matches_full_prefix() -> None:
    rng = np.random.default_rng(137)
    features = rng.normal(size=(80, 9)).astype(np.float32)
    targets = np.repeat(np.asarray([0, 1], dtype=np.int64), 40)
    evaluation = rng.normal(size=(11, 9)).astype(np.float32)
    config = ModelTrajectoryConfig(
        model_family="neural_head",
        task="classification",
        global_classes=(0, 1),
    )

    medium = build_trajectory(
        config,
        (features, targets),
        evaluation,
        seed=43,
        device="cpu",
        max_fidelity="medium",
    )
    full = build_trajectory(
        config, (features, targets), evaluation, seed=43, device="cpu"
    )

    assert tuple(medium.predictions) == ("low", "medium")
    assert medium.checkpoint_epochs == {"low": 1, "medium": 3}
    assert_array_equal(
        medium.predictions["medium"].values,
        full.predictions["medium"].values,
    )
    assert medium.checkpoint_hashes["medium"] == full.checkpoint_hashes["medium"]


def test_digits_features_are_normalized_and_content_addressed(tmp_path) -> None:
    source = declared_real_sources()["digits"]
    pixels = np.asarray(
        [np.zeros((8, 8)), np.full((8, 8), 16.0)], dtype=np.float64
    )
    bundle = RealDatasetBundle.create(source, pixels.reshape(2, 64), [0, 1])
    config = PublicFeatureConfig(kind="digits_raw", transform_id="digits-div16-v1")
    first = extract_public_features(bundle, config, cache_dir=tmp_path, device="cpu")
    second = extract_public_features(bundle, config, cache_dir=tmp_path, device="cpu")
    assert first.values.shape == (2, 64)
    assert first.values.dtype == np.float32
    assert float(first.values.min()) == 0.0
    assert float(first.values.max()) == 1.0
    assert first.feature_hash == second.feature_hash
    assert second.cache_hit is True


def test_numeric_tabular_features_preserve_published_values(tmp_path) -> None:
    source = declared_real_sources()["breast_cancer"]
    values = np.asarray([[1.5, 2.0], [3.25, -4.0]], dtype=np.float64)
    bundle = RealDatasetBundle.create(source, values, [0, 1])
    artifact = extract_public_features(
        bundle,
        PublicFeatureConfig(kind="tabular_numeric", transform_id="raw-numeric-v1"),
        cache_dir=tmp_path,
        device="cpu",
    )
    assert artifact.values.dtype == np.float64
    assert_array_equal(artifact.values, values)
    assert artifact.fitted_row_ids == ()


def test_adult_mixed_features_are_stateless_schema_fixed_and_row_local(tmp_path) -> None:
    import pandas as pd

    source = declared_real_sources()["adult"]
    rows = pd.DataFrame(
        {
            "age": [39, 50, 28],
            "workclass": ["State-gov", "Self-emp-not-inc", "Never-seen-at-train"],
            "fnlwgt": [77516, 83311, 338409],
            "education": ["Bachelors", "Bachelors", None],
            "education-num": [13, 13, 9],
            "marital-status": ["Never-married", "Married-civ-spouse", "Divorced"],
            "occupation": ["Adm-clerical", "Exec-managerial", "?"],
            "relationship": ["Not-in-family", "Husband", "Unmarried"],
            "race": ["White", "White", "Black"],
            "sex": ["Male", "Male", "Female"],
            "capital-gain": [2174, 0, 0],
            "capital-loss": [0, 0, 0],
            "hours-per-week": [40, 13, 40],
            "native-country": ["United-States", "United-States", None],
        }
    )
    row_ids = ("adult:a", "adult:b", "adult:c")
    bundle = RealDatasetBundle.create(
        source, rows, [0, 1, 0], row_ids=row_ids
    )
    config = PublicFeatureConfig(
        kind="mixed_tabular_hashing",
        transform_id="adult-public-schema-hash-v1",
        n_features=32,
        schema_id="adult-openml-1590-v1",
        alternate_sign=False,
    )

    artifact = extract_public_features(
        bundle, config, cache_dir=tmp_path / "first", device="cpu"
    )
    reordered = RealDatasetBundle.create(
        source,
        rows.iloc[[2, 0, 1]].reset_index(drop=True),
        [0, 0, 1],
        row_ids=("adult:c", "adult:a", "adult:b"),
    )
    reordered_artifact = extract_public_features(
        reordered, config, cache_dir=tmp_path / "second", device="cpu"
    )

    assert artifact.values.shape == (3, 38)
    assert_array_equal(
        artifact.values[:, :6],
        rows[
            [
                "age",
                "fnlwgt",
                "education-num",
                "capital-gain",
                "capital-loss",
                "hours-per-week",
            ]
        ].to_numpy(dtype=np.float64),
    )
    by_id = dict(zip(artifact.row_ids, artifact.values, strict=True))
    reordered_by_id = dict(
        zip(reordered_artifact.row_ids, reordered_artifact.values, strict=True)
    )
    for row_id in row_ids:
        assert_array_equal(by_id[row_id], reordered_by_id[row_id])
    assert artifact.fitted_row_ids == ()
    assert artifact.weight_hash == "stateless"


def test_text_hashing_is_stateless_and_feature_key_covers_all_inputs(tmp_path) -> None:
    source = declared_real_sources()["ag_news"]
    bundle = RealDatasetBundle.create(
        source,
        np.asarray(["red fox", "blue fox", "green bird"], dtype=object),
        [0, 1, 0],
    )
    config = PublicFeatureConfig(
        kind="text_hashing", transform_id="hashing-word12-v1", n_features=32
    )
    artifact = extract_public_features(
        bundle, config, cache_dir=tmp_path, device="cpu"
    )
    assert artifact.values.shape == (3, 32)
    assert artifact.fitted_row_ids == ()
    assert artifact.weight_hash == "stateless"
    base = feature_cache_key(
        bundle,
        config,
        weight_hash="stateless",
        package_versions={"scikit-learn": "1"},
    )
    changed_transform = feature_cache_key(
        bundle,
        PublicFeatureConfig(
            kind="text_hashing", transform_id="different", n_features=32
        ),
        weight_hash="stateless",
        package_versions={"scikit-learn": "1"},
    )
    changed_weight = feature_cache_key(
        bundle,
        config,
        weight_hash="different",
        package_versions={"scikit-learn": "1"},
    )
    changed_package = feature_cache_key(
        bundle,
        config,
        weight_hash="stateless",
        package_versions={"scikit-learn": "2"},
    )
    changed_rows = RealDatasetBundle.create(
        source,
        np.asarray(["changed", "blue fox", "green bird"], dtype=object),
        [0, 1, 0],
    )
    assert len({base, changed_transform, changed_weight, changed_package}) == 4
    assert base != feature_cache_key(
        changed_rows,
        config,
        weight_hash="stateless",
        package_versions={"scikit-learn": "1"},
    )
