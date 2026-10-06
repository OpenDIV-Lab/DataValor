from __future__ import annotations

import numpy as np
from datamechbench.data import OwnerDataset
from datamechbench.settings.valuation import (
    make_valuation_axiom_cases,
    make_valuation_contribution_cases,
    make_valuation_corruption_cases,
    make_valuation_noise_cases,
    make_valuation_structural_cases,
)


def test_axiom_settings_declare_exact_assumptions_and_properties() -> None:
    cases = make_valuation_axiom_cases()

    assert {case.metadata["property"] for case in cases} >= {
        "additive",
        "dummy",
        "symmetric",
        "complementary",
        "harmful",
    }
    assert all(case.metadata["benchmark_setting"] == "V-AXIOM" for case in cases)
    assert all("exact_coalition_utility" in case.metadata["assumptions"] for case in cases)


def test_corruption_settings_are_reproducible_and_keep_truth_evaluator_only() -> None:
    first = make_valuation_corruption_cases(17)
    second = make_valuation_corruption_cases(17)

    assert len(first) >= 5
    assert [case.case_id for case in first] == [case.case_id for case in second]
    for left, right in zip(first, second, strict=True):
        left_data = left.metadata["owner_dataset"]
        right_data = right.metadata["owner_dataset"]
        assert isinstance(left_data, OwnerDataset)
        assert left_data.dataset_hash == right_data.dataset_hash
        assert np.array_equal(left_data.y_train, right_data.y_train)
        assert case_truth_is_not_in_public_utility_metadata(left)
        assert left.metadata["corrupted_owners"]
        assert left.metadata["benchmark_setting"] == "V-CORRUPTION"


def case_truth_is_not_in_public_utility_metadata(case) -> bool:
    dataset = case.metadata["owner_dataset"]
    return not hasattr(dataset, "corrupted_owners")


def test_contribution_noise_and_structural_settings_are_distinct() -> None:
    contribution = make_valuation_contribution_cases(5)
    noise = make_valuation_noise_cases(5)
    structural = make_valuation_structural_cases(5)

    assert contribution and noise and structural
    assert {case.metadata["benchmark_setting"] for case in contribution} == {"V-CONTRIBUTION"}
    assert {case.metadata["benchmark_setting"] for case in noise} == {"V-UTILITY-NOISE"}
    assert {case.metadata["benchmark_setting"] for case in structural} == {"V-STRUCTURAL"}
    assert any("split_pair" in case.metadata for case in structural)
    assert any("duplicate_pair" in case.metadata for case in structural)
    assert all("utility_noise_sigma" in case.metadata for case in noise)


def test_default_case_catalog_includes_all_formal_valuation_settings() -> None:
    from datamechbench.runner import build_cases

    settings = {
        case.metadata.get("benchmark_setting") for case in build_cases(seed=2)["valuation"]
    }

    assert {
        "V-AXIOM",
        "V-CORRUPTION",
        "V-CONTRIBUTION",
        "V-UTILITY-NOISE",
        "V-STRUCTURAL",
    } <= settings
