from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from datamechbench.data import OwnerDataset
from datamechbench.metrics import evaluate_valuation_metrics
from datamechbench.models import ValuationCase, ValuationOutput
from datamechbench.runner import build_registry
from datamechbench.settings import valuation as valuation_settings


def _tiny_dataset() -> OwnerDataset:
    x = np.asarray([[1.0], [1.0], [2.0], [2.0]])
    y = np.asarray([0, 0, 1, 1])
    return OwnerDataset(
        dataset_id="tiny-volume",
        source_shape=x.shape,
        train_indices=np.arange(len(x)),
        validation_indices=np.asarray([0, 1]),
        test_indices=np.asarray([2, 3]),
        x_train=x,
        y_train=y,
        x_validation=np.asarray([[1.0], [2.0]]),
        y_validation=np.asarray([0, 1]),
        x_test=np.asarray([[1.0], [2.0]]),
        y_test=np.asarray([0, 1]),
        owner_rows={"a": (0, 1), "b": (2, 3)},
        noise_rates={"a": 0.0, "b": 0.0},
        dataset_hash="tiny",
    )


def _case(dataset: OwnerDataset, case_id: str = "tiny") -> ValuationCase:
    return ValuationCase(
        case_id=case_id,
        owner_ids=dataset.owner_ids,
        utility=lambda coalition: dataset.utility_for_owners(coalition),
        case_type="real_owner_data",
        metadata={"owner_dataset": dataset, "benchmark_setting": "V-REPLICATION-ROBUSTNESS"},
    )


def _three_owner_dataset(
    dataset_id: str,
    x: np.ndarray,
    owner_rows: dict[str, tuple[int, ...]],
) -> OwnerDataset:
    labels = np.arange(len(x), dtype=int) % 2
    return OwnerDataset(
        dataset_id=dataset_id,
        source_shape=x.shape,
        train_indices=np.arange(len(x)),
        validation_indices=np.asarray([0, 1]),
        test_indices=np.asarray([0, 1]),
        x_train=np.asarray(x, dtype=float),
        y_train=labels,
        x_validation=np.asarray(x[:2], dtype=float),
        y_validation=labels[:2],
        x_test=np.asarray(x[:2], dtype=float),
        y_test=labels[:2],
        owner_rows=owner_rows,
        noise_rates={owner: 0.0 for owner in owner_rows},
        dataset_hash=f"{dataset_id}-hash",
    )


def test_replication_cases_keep_owner_identity_and_control_factor() -> None:
    assert hasattr(valuation_settings, "make_valuation_replication_cases")
    cases = valuation_settings.make_valuation_replication_cases(seed=4)

    assert len(cases) == 27
    assert len({case.case_id for case in cases}) == 27
    assert {case.metadata["dataset_name"] for case in cases} == {
        "breast_cancer",
        "wine",
        "digits",
    }
    assert {case.metadata["replication_factor"] for case in cases} == {1, 2, 4}
    attacks = [case for case in cases if case.metadata["replication_factor"] > 1]
    assert len(attacks) == 24
    assert {case.metadata["replicated_owner"] for case in attacks} == {
        "o0",
        "o2",
        "o4",
        "o6",
    }
    assert {case.metadata["benchmark_setting"] for case in cases} == {
        "V-REPLICATION-ROBUSTNESS"
    }
    for dataset_name in ("breast_cancer", "wine", "digits"):
        cohort = [
            case for case in cases if case.metadata["dataset_name"] == dataset_name
        ]
        (baseline,) = [
            case for case in cohort if case.metadata["replication_factor"] == 1
        ]
        base_data = baseline.metadata["owner_dataset"]
        assert baseline.case_id == f"VREP-{dataset_name}-c1"
        for case in (item for item in cohort if item is not baseline):
            dataset = case.metadata["owner_dataset"]
            factor = case.metadata["replication_factor"]
            owner = case.metadata["replicated_owner"]
            assert dataset.owner_ids == base_data.owner_ids
            assert len(dataset.owner_rows[owner]) == len(base_data.owner_rows[owner]) * factor
            assert all(
                len(dataset.owner_rows[other]) == len(base_data.owner_rows[other])
                for other in base_data.owner_ids
                if other != owner
            )
            assert case.metadata["replication_baseline_case_id"] == baseline.case_id
            assert case.metadata["replication_group_id"] == (
                f"VREP-{dataset_name}-{owner}"
            )

    case_ids = {case.case_id for case in cases}
    assert {
        "VREP-breast_cancer-c2",
        "VREP-breast_cancer-c4",
        "VREP-wine-c2",
        "VREP-wine-c4",
        "VREP-digits-c2",
        "VREP-digits-c4",
    } <= case_ids


def test_volume_shapley_matches_hand_derived_two_owner_values() -> None:
    registry = build_registry()
    method = registry.create(
        "volume_shapley",
        {"standardize": False, "pca_components": 0},
    )
    output = method.evaluate(_case(_tiny_dataset()), seed=0)

    root2 = np.sqrt(2.0)
    root8 = np.sqrt(8.0)
    root10 = np.sqrt(10.0)
    assert output.scores["a"] == pytest.approx((root2 + root10 - root8) / 2)
    assert output.scores["b"] == pytest.approx((root8 + root10 - root2) / 2)
    assert sum(output.scores.values()) == pytest.approx(root10)
    assert output.diagnostics["characteristic_value"] == pytest.approx(root10)


def test_volume_shapley_matches_equation_three_on_three_owner_fixture() -> None:
    dataset = _three_owner_dataset(
        "volume-paper-golden",
        np.asarray(
            [
                [1.0, 0.0],
                [0.0, 1.0],
                [1.0, 1.0],
                [2.0, 0.0],
                [0.0, 2.0],
                [2.0, 2.0],
            ]
        ),
        {"a": (0, 1), "b": (2, 3), "c": (4, 5)},
    )
    method = build_registry().create(
        "volume_shapley",
        {"standardize": False, "pca_components": 0},
    )

    output = method.evaluate(_case(dataset, "volume-paper-golden"), seed=0)

    assert output.diagnostics["characteristic_value"] == pytest.approx(
        8.660254038421735
    )
    assert output.scores == pytest.approx(
        {
            "a": 1.1759446890978889,
            "b": 2.7250196709244174,
            "c": 4.759289678399428,
        }
    )
    assert sum(output.scores.values()) == pytest.approx(8.660254038421735)


def test_robust_volume_characteristic_is_bounded_under_exact_replication() -> None:
    base = _tiny_dataset()
    repeated = replace(
        base,
        dataset_id="tiny-volume-repeated",
        x_train=np.repeat(base.x_train, 4, axis=0),
        y_train=np.repeat(base.y_train, 4, axis=0),
        owner_rows={"a": tuple(range(0, 8)), "b": tuple(range(8, 16))},
    )
    method = build_registry().create(
        "robust_volume_shapley",
        {"standardize": False, "pca_components": 0, "omega": 0.1},
    )

    clean = method.evaluate(_case(base, "clean"), seed=0)
    replicated = method.evaluate(_case(repeated, "replicated"), seed=0)

    inflation = (
        replicated.diagnostics["characteristic_value"]
        / clean.diagnostics["characteristic_value"]
    )
    assert 1.0 <= inflation <= 1.1


def test_robust_volume_shapley_matches_official_cube_density_formula() -> None:
    dataset = _three_owner_dataset(
        "robust-volume-paper-golden",
        np.asarray(
            [
                [0.1, 0.1],
                [0.2, 0.2],
                [1.2, 0.1],
                [0.1, 1.2],
                [0.2, 1.1],
                [1.2, 1.2],
                [2.1, 0.1],
                [2.2, 0.2],
            ]
        ),
        {"a": (0, 1, 2), "b": (3, 4, 5), "c": (6, 7)},
    )
    method = build_registry().create(
        "robust_volume_shapley",
        {"standardize": False, "pca_components": 0, "omega": 1.0},
    )

    output = method.evaluate(_case(dataset, "robust-volume-paper-golden"), seed=0)

    assert output.diagnostics["compressed_point_count"] == 5
    assert output.diagnostics["density_alpha"] == pytest.approx(0.02)
    assert output.diagnostics["base_volume"] == pytest.approx(4.116925431678355)
    assert output.diagnostics["density_multiplier"] == pytest.approx(
        1.1053802312384255
    )
    assert output.diagnostics["characteristic_value"] == pytest.approx(
        4.5507679856599745
    )
    assert output.scores == pytest.approx(
        {
            "a": 0.4966149347721257,
            "b": 2.887112278798953,
            "c": 1.1670407720888956,
        }
    )
    assert sum(output.scores.values()) == pytest.approx(4.5507679856599745)


def test_replication_metrics_use_factor_one_peer_and_keep_distinct_meanings() -> None:
    dataset = _tiny_dataset()
    baseline = _case(dataset, "VREP-tiny-c1")
    attacked = replace(
        baseline,
        case_id="VREP-tiny-c4",
        metadata={
            **baseline.metadata,
            "replicated_owner": "a",
            "replication_factor": 4,
            "replication_baseline_case_id": baseline.case_id,
        },
    )
    clean_output = ValuationOutput(
        {"a": 1.0, "b": 2.0}, diagnostics={"characteristic_value": 2.0}
    )
    attacked_output = ValuationOutput(
        {"a": 3.0, "b": 1.0}, diagnostics={"characteristic_value": 2.1}
    )

    metrics = evaluate_valuation_metrics(
        attacked,
        attacked_output,
        peer_outputs=((baseline, clean_output),),
    )

    assert metrics["replication_reward_share_gain"].value == pytest.approx(5 / 12)
    assert metrics["replication_score_inflation_ratio"].value == pytest.approx(3.0)
    assert metrics["characteristic_replication_inflation_ratio"].value == pytest.approx(1.05)
    assert metrics["replication_owner_rank_change"].value == pytest.approx(1.0)
