import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from datamechbench.game_builders.real_models import (
    FidelityPrediction,
    ModelTrajectoryConfig,
    NestedTrajectory,
)
from datamechbench.game_builders.real_oracle import (
    CachedTrajectoryOracle,
    make_real_trajectory_oracle,
)


def test_oracle_is_lazy_and_one_training_emits_every_fidelity(tmp_path: Path) -> None:
    calls: list[int] = []

    def evaluate(mask: int):
        calls.append(mask)
        return {
            "low": mask * 0.1,
            "medium": mask * 0.2,
            "high": mask * 0.3,
        }, 1.25, {"low": "l", "medium": "m", "high": "h"}

    oracle = CachedTrajectoryOracle(
        owner_ids=("o0", "o1", "o2"),
        input_hash="game-v1",
        cache_dir=tmp_path,
        evaluator=evaluate,
    )

    assert calls == []
    assert oracle.value(3, "low") == pytest.approx(0.3)
    # Repeated fidelity queries in one experiment must reuse the validated
    # in-memory trajectory rather than reparsing the JSON record each time.
    oracle._path(3).unlink()
    assert oracle.value(3, "high") == pytest.approx(0.9)
    assert calls == [3]
    assert oracle.trajectory_builds == 1
    assert oracle.logical_calls == {"low": 1, "medium": 0, "high": 1}


def test_oracle_replay_uses_atomic_cache_without_evaluator(tmp_path: Path) -> None:
    first = CachedTrajectoryOracle(
        owner_ids=("o0", "o1"),
        input_hash="game-v1",
        cache_dir=tmp_path,
        evaluator=lambda mask: (
            {"low": 0.1, "medium": 0.2, "high": 0.3},
            0.4,
            {},
        ),
    )
    assert first.value(1, "high") == pytest.approx(0.3)

    def forbidden(mask: int):
        raise AssertionError(f"cache miss for {mask}")

    replay = CachedTrajectoryOracle(
        owner_ids=("o0", "o1"),
        input_hash="game-v1",
        cache_dir=tmp_path,
        evaluator=forbidden,
    )
    assert replay.value(1, "medium") == pytest.approx(0.2)
    assert replay.trajectory_builds == 0


def test_prefix_oracle_builds_only_requested_fidelity_then_upgrades(tmp_path: Path) -> None:
    calls: list[tuple[int, str]] = []

    def evaluate_prefix(mask: int, fidelity: str):
        calls.append((mask, fidelity))
        names = ("low", "medium", "high")
        stop = names.index(fidelity) + 1
        return (
            {name: mask * (index + 1) / 10 for index, name in enumerate(names[:stop])},
            float(stop),
            {name: name[0] for name in names[:stop]},
        )

    oracle = CachedTrajectoryOracle(
        owner_ids=("o0", "o1"),
        input_hash="prefix-game-v1",
        cache_dir=tmp_path,
        evaluator=None,
        prefix_evaluator=evaluate_prefix,
    )

    assert oracle.value(1, "medium") == pytest.approx(0.2)
    assert oracle.value(1, "low") == pytest.approx(0.1)
    assert calls == [(1, "medium")]
    assert oracle.value(1, "high") == pytest.approx(0.3)
    assert calls == [(1, "medium"), (1, "high")]
    assert oracle.trajectory_builds == 2
    assert oracle.physical_fit_seconds == pytest.approx(5.0)

    replay = CachedTrajectoryOracle(
        owner_ids=("o0", "o1"),
        input_hash="prefix-game-v1",
        cache_dir=tmp_path,
        evaluator=None,
        prefix_evaluator=lambda mask, fidelity: (_ for _ in ()).throw(
            AssertionError("upgraded prefix record should replay from disk")
        ),
    )
    assert replay.value(1, "high") == pytest.approx(0.3)
    assert replay.trajectory_builds == 0


def test_oracle_rejects_stale_or_malformed_records(tmp_path: Path) -> None:
    root = tmp_path / "game-v1" / "coalitions"
    root.mkdir(parents=True)
    (root / "1.json").write_text(
        json.dumps(
            {
                "mask": 1,
                "input_hash": "other-game",
                "utilities": {"low": 0.1, "medium": 0.2, "high": 0.3},
                "fit_seconds": 0.4,
                "checkpoint_hashes": {},
            }
        )
    )
    oracle = CachedTrajectoryOracle(
        owner_ids=("o0", "o1"),
        input_hash="game-v1",
        cache_dir=tmp_path,
        evaluator=lambda mask: ({"low": 0.0, "medium": 0.0, "high": 0.0}, 0.0, {}),
    )
    with pytest.raises(ValueError, match="input hash"):
        oracle.value(1, "low")


def test_oracle_validates_masks_fidelities_and_complete_records(tmp_path: Path) -> None:
    oracle = CachedTrajectoryOracle(
        owner_ids=("o0", "o1"),
        input_hash="game-v1",
        cache_dir=tmp_path,
        evaluator=lambda mask: ({"low": 0.1, "high": 0.3}, 0.4, {}),
    )
    with pytest.raises(ValueError, match="fidelity"):
        oracle.value(1, "medium")
    with pytest.raises(ValueError, match="mask"):
        oracle.value(4, "low")


def test_real_factory_selects_owner_rows_and_reuses_one_nested_trajectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = SimpleNamespace(
        dataset_id="toy",
        content_hash="manifest-v1",
        n_owners=2,
        validation_row_ids=("r2",),
        owner_row_ids={"o0": ("r0",), "o1": ("r1",)},
        task="regression",
        split_seed=11,
    )
    features = SimpleNamespace(
        dataset_id="toy",
        feature_hash="features-v1",
        row_ids=("r0", "r1", "r2"),
        values=np.asarray([[1.0], [2.0], [9.0]]),
        targets=np.asarray([1.0, 2.0, 8.0]),
    )
    config = ModelTrajectoryConfig(model_family="boosting", task="regression")
    trained: list[tuple[np.ndarray, np.ndarray, int]] = []

    def fake_build(config, training, evaluation, *, seed, device):
        trained.append((training[0].copy(), evaluation.copy(), seed))
        predictions = {
            name: FidelityPrediction(name, index + 1, np.asarray([value]))
            for index, (name, value) in enumerate(
                (("low", 1.0), ("medium", 2.0), ("high", 3.0))
            )
        }
        return NestedTrajectory(config, predictions, None, 0.5, device)

    monkeypatch.setattr(
        "datamechbench.game_builders.real_oracle.build_trajectory", fake_build
    )
    oracle = make_real_trajectory_oracle(
        manifest,
        features,
        config,
        cache_dir=tmp_path,
        device="cpu",
    )

    assert oracle.value(1, "low") == pytest.approx(-49.0)
    assert oracle.value(1, "high") == pytest.approx(-25.0)
    assert len(trained) == 1
    assert trained[0][0].tolist() == [[1.0]]
    assert trained[0][1].tolist() == [[9.0]]
    assert trained[0][2] == 12
