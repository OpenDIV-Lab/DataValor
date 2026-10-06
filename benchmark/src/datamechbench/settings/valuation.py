"""Valuation settings aligned with axioms and data-valuation experiments."""

from __future__ import annotations

import hashlib
from dataclasses import replace

import numpy as np

from ..data import OwnerDataset, _dataset_hash, load_owner_dataset
from ..models import ValuationCase


def _case(
    case_id: str,
    owners: tuple[str, ...],
    utility,
    setting: str,
    *,
    case_type: str = "analytic",
    assumptions: tuple[str, ...] = (),
    **metadata,
) -> ValuationCase:
    return ValuationCase(
        case_id=case_id,
        owner_ids=owners,
        utility=utility,
        case_type=case_type,
        metadata={
            "benchmark_setting": setting,
            "assumptions": assumptions,
            "pilot": False,
            **metadata,
        },
    )


def make_valuation_axiom_cases() -> tuple[ValuationCase, ...]:
    owners = ("a", "b", "c", "d")
    weights = {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0}
    assumptions = ("exact_coalition_utility", "complete_coalition_constraints")

    def additive(coalition):
        return sum(weights[item] for item in set(coalition))

    def dummy(coalition):
        return sum(weights[item] for item in set(coalition) if item != "d")

    def symmetric(coalition):
        members = set(coalition)
        return float("a" in members) * 2 + float("b" in members) * 2 + sum(
            weights[item] for item in members - {"a", "b"}
        )

    def complementary(coalition):
        members = set(coalition)
        return sum(weights[item] for item in members) + (
            8.0 if {"a", "b"}.issubset(members) else 0.0
        )

    def harmful(coalition):
        members = set(coalition)
        return sum(weights[item] for item in members) - (7.0 if "d" in members else 0.0)

    return (
        _case("VAX-additive", owners, additive, "V-AXIOM", assumptions=assumptions, property="additive"),
        _case("VAX-dummy", owners, dummy, "V-AXIOM", assumptions=assumptions, property="dummy", dummy_owners=("d",)),
        _case("VAX-symmetric", owners, symmetric, "V-AXIOM", assumptions=assumptions, property="symmetric", symmetric_groups=(("a", "b"),)),
        _case("VAX-complementary", owners, complementary, "V-AXIOM", assumptions=assumptions, property="complementary", complementary_pair=("a", "b")),
        _case("VAX-harmful", owners, harmful, "V-AXIOM", assumptions=assumptions, property="harmful", bad_owner="d"),
    )


def _mutate_owner(
    clean: OwnerDataset,
    owner: str,
    rate: float,
    kind: str,
    seed: int,
) -> OwnerDataset:
    rng = np.random.default_rng(seed)
    rows = np.asarray(clean.owner_rows[owner], dtype=int)
    count = max(1, int(round(rate * len(rows))))
    selected = np.sort(rng.choice(rows, size=count, replace=False))
    x_train = clean.x_train.copy()
    y_train = clean.y_train.copy()
    if kind == "label":
        classes = np.unique(y_train)
        mapping = {value: classes[(index + 1) % len(classes)] for index, value in enumerate(classes)}
        y_train[selected] = np.asarray([mapping[value] for value in y_train[selected]])
    elif kind == "feature":
        scale = np.std(x_train, axis=0, ddof=0)
        scale[scale == 0] = 1.0
        x_train[selected] += rng.normal(0.0, 2.0, size=x_train[selected].shape) * scale
    else:
        raise ValueError(f"unsupported corruption kind: {kind}")
    return replace(
        clean,
        dataset_id=f"{clean.dataset_id}-{kind}-{owner}-{int(rate * 100)}",
        x_train=x_train,
        y_train=y_train,
        noise_rates={**clean.noise_rates, owner: rate},
        dataset_hash=_dataset_hash(x_train, y_train, clean.train_indices),
    )


def _dataset_case(
    case_id: str,
    dataset: OwnerDataset,
    setting: str,
    *,
    assumptions: tuple[str, ...] = (),
    **metadata,
) -> ValuationCase:
    return _case(
        case_id,
        dataset.owner_ids,
        lambda coalition: dataset.utility_for_owners(coalition),
        setting,
        case_type="real_owner_data",
        assumptions=assumptions,
        owner_dataset=dataset,
        dataset_id=dataset.dataset_id,
        dataset_hash=dataset.dataset_hash,
        **metadata,
    )


def make_valuation_corruption_cases(seed: int = 42) -> tuple[ValuationCase, ...]:
    specifications = (
        ("breast_cancer", "o7", 0.2, "label"),
        ("breast_cancer", "o7", 0.4, "label"),
        ("breast_cancer", "o6", 0.4, "feature"),
        ("wine", "o7", 0.4, "label"),
        ("digits", "o7", 0.4, "label"),
    )
    cases = []
    for index, (dataset_name, owner, rate, kind) in enumerate(specifications):
        dataset = _mutate_owner(
            load_owner_dataset(seed, dataset_name), owner, rate, kind, seed + 100 + index
        )
        cases.append(
            _dataset_case(
                f"VCORR-{dataset_name}-{kind}-{int(rate * 100)}",
                dataset,
                "V-CORRUPTION",
                assumptions=("fixed_train_validation_test_split",),
                corrupted_owners=(owner,),
                corruption_kind=kind,
                corruption_rate=rate,
                bad_owner=owner,
            )
        )
    return tuple(cases)


def make_valuation_contribution_cases(seed: int = 42) -> tuple[ValuationCase, ...]:
    cases = []
    for name in ("breast_cancer", "wine", "digits"):
        dataset = load_owner_dataset(seed, name)
        grand = dataset.utility_for_owners(dataset.owner_ids)
        effects = {
            owner: grand
            - dataset.utility_for_owners(item for item in dataset.owner_ids if item != owner)
            for owner in dataset.owner_ids
        }
        cases.append(
            _dataset_case(
                f"VCONT-{name}",
                dataset,
                "V-CONTRIBUTION",
                assumptions=("fixed_train_validation_test_split",),
                owner_deletion_effects=effects,
            )
        )
    return tuple(cases)


def make_valuation_noise_cases(seed: int = 42) -> tuple[ValuationCase, ...]:
    base = make_valuation_axiom_cases()[0]
    cases = []
    for sigma in (0.01, 0.05, 0.10):
        def noisy_utility(coalition, sigma=sigma):
            key = "|".join(sorted(set(coalition)))
            digest = hashlib.sha256(f"{seed}|{sigma}|{key}".encode()).digest()
            local_seed = int.from_bytes(digest[:8], "big")
            noise = np.random.default_rng(local_seed).normal(0.0, sigma)
            return base.utility(tuple(coalition)) + float(noise)

        cases.append(
            _case(
                f"VNOISE-gaussian-{int(sigma * 1000):03d}",
                base.owner_ids,
                noisy_utility,
                "V-UTILITY-NOISE",
                assumptions=("isotropic_gaussian_utility_noise",),
                property="utility_noise",
                utility_noise_sigma=sigma,
            )
        )
    return tuple(cases)


def make_valuation_structural_cases(seed: int = 42) -> tuple[ValuationCase, ...]:
    del seed
    duplicate_owners = ("a", "a_copy", "b", "c")

    def duplicate_utility(coalition):
        members = set(coalition)
        return (3.0 if members & {"a", "a_copy"} else 0.0) + 2.0 * ("b" in members) + 1.0 * ("c" in members)

    split_owners = ("a_left", "a_right", "b", "c")

    def split_utility(coalition):
        members = set(coalition)
        return 1.5 * ("a_left" in members) + 1.5 * ("a_right" in members) + 2.0 * ("b" in members) + 1.0 * ("c" in members)

    assumptions = ("exact_coalition_utility",)
    return (
        _case("VSTRUCT-duplicate", duplicate_owners, duplicate_utility, "V-STRUCTURAL", assumptions=assumptions, property="replication", duplicate_pair=("a", "a_copy")),
        _case("VSTRUCT-split", split_owners, split_utility, "V-STRUCTURAL", assumptions=assumptions, property="owner_split", split_pair=("a_left", "a_right"), unsplit_value=3.0),
    )


def _replicate_owner_dataset(
    clean: OwnerDataset, owner: str, factor: int
) -> OwnerDataset:
    if factor < 1:
        raise ValueError("replication factor must be at least one")
    if factor == 1:
        return clean
    source_rows = np.asarray(clean.owner_rows[owner], dtype=int)
    repeated_x = np.concatenate(
        [clean.x_train, *[clean.x_train[source_rows] for _ in range(factor - 1)]],
        axis=0,
    )
    repeated_y = np.concatenate(
        [clean.y_train, *[clean.y_train[source_rows] for _ in range(factor - 1)]],
        axis=0,
    )
    repeated_indices = np.concatenate(
        [clean.train_indices, *[clean.train_indices[source_rows] for _ in range(factor - 1)]]
    )
    appended = tuple(range(len(clean.x_train), len(repeated_x)))
    owner_rows = {
        **clean.owner_rows,
        owner: tuple(clean.owner_rows[owner]) + appended,
    }
    return replace(
        clean,
        dataset_id=f"{clean.dataset_id}-replicate-{owner}-c{factor}",
        train_indices=repeated_indices,
        x_train=repeated_x,
        y_train=repeated_y,
        owner_rows=owner_rows,
        dataset_hash=_dataset_hash(repeated_x, repeated_y, repeated_indices),
    )


def make_valuation_replication_cases(seed: int = 42) -> tuple[ValuationCase, ...]:
    """Owner-preserving exact-copy attacks from Xu et al. (NeurIPS 2021)."""

    cases: list[ValuationCase] = []
    for dataset_name in ("breast_cancer", "wine", "digits"):
        clean = load_owner_dataset(seed, dataset_name)
        baseline_id = f"VREP-{dataset_name}-c1"
        cases.append(
            _dataset_case(
                baseline_id,
                clean,
                "V-REPLICATION-ROBUSTNESS",
                assumptions=(
                    "fixed_train_validation_test_split",
                    "exact_row_replication",
                    "fixed_owner_identity",
                ),
                dataset_name=dataset_name,
                replicated_owner="o0",
                replication_factor=1,
                replication_baseline_case_id=baseline_id,
                replication_group_id=f"VREP-{dataset_name}-clean",
                replication_mode="full_owner_bundle",
                primary_metric_eligible=False,
            )
        )
        for owner in ("o0", "o2", "o4", "o6"):
            for factor in (2, 4):
                dataset = _replicate_owner_dataset(clean, owner, factor)
                suffix = f"c{factor}" if owner == "o0" else f"{owner}-c{factor}"
                cases.append(
                    _dataset_case(
                        f"VREP-{dataset_name}-{suffix}",
                        dataset,
                        "V-REPLICATION-ROBUSTNESS",
                        assumptions=(
                            "fixed_train_validation_test_split",
                            "exact_row_replication",
                            "fixed_owner_identity",
                        ),
                        dataset_name=dataset_name,
                        replicated_owner=owner,
                        replication_factor=factor,
                        replication_baseline_case_id=baseline_id,
                        replication_group_id=f"VREP-{dataset_name}-{owner}",
                        replication_mode="full_owner_bundle",
                        primary_metric_eligible=True,
                    )
                )
    return tuple(cases)


__all__ = [
    "make_valuation_axiom_cases",
    "make_valuation_contribution_cases",
    "make_valuation_corruption_cases",
    "make_valuation_noise_cases",
    "make_valuation_replication_cases",
    "make_valuation_structural_cases",
]
