"""Deterministic data and case factories for the benchmark MVP."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Iterable, Mapping

import numpy as np
from sklearn.datasets import load_breast_cancer, load_digits, load_wine
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .models import (
    ProcurementCase,
    ProcurementInput,
    TradeCase,
    TradeInput,
    ValuationCase,
)

OWNER_IDS = tuple(f"o{index}" for index in range(8))
BUYER_MULTIPLIERS = (0.55, 0.65, 0.75, 0.85, 0.95, 1.05, 1.15, 1.25, 1.35, 1.45)
SELLER_MULTIPLIERS = (0.20, 0.28, 0.36, 0.44, 0.52, 0.60, 0.68, 0.76, 0.84, 0.92)


def _majority_accuracy(labels: np.ndarray) -> float:
    values, counts = np.unique(labels, return_counts=True)
    majority = values[int(np.argmax(counts))]
    return float(np.mean(labels == majority))


@dataclass
class OwnerDataset:
    """A fixed split whose training rows are grouped into data-owner bundles.

    Owner row indices are local to ``x_train``.  The source indices are kept
    separately so split reproducibility and leakage can be audited.
    """

    dataset_id: str
    source_shape: tuple[int, int]
    train_indices: np.ndarray
    validation_indices: np.ndarray
    test_indices: np.ndarray
    x_train: np.ndarray
    y_train: np.ndarray
    x_validation: np.ndarray
    y_validation: np.ndarray
    x_test: np.ndarray
    y_test: np.ndarray
    owner_rows: Mapping[str, tuple[int, ...]]
    noise_rates: Mapping[str, float]
    duplicate_of: Mapping[str, str] = field(default_factory=dict)
    split_seed: int = 42
    dataset_hash: str = ""
    _validation_cache: dict[tuple[int, ...], float] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    _test_cache: dict[tuple[int, ...], float] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @property
    def owner_ids(self) -> tuple[str, ...]:
        return tuple(self.owner_rows)

    def utility_for_rows(self, rows: Iterable[int], *, use_test: bool = False) -> float:
        row_key = tuple(sorted(int(row) for row in rows))
        cache = self._test_cache if use_test else self._validation_cache
        if row_key in cache:
            return cache[row_key]

        evaluation_x = self.x_test if use_test else self.x_validation
        evaluation_y = self.y_test if use_test else self.y_validation
        if not row_key or len(np.unique(self.y_train[list(row_key)])) < 2:
            result = _majority_accuracy(evaluation_y)
        else:
            model = Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "model",
                        LogisticRegression(
                            C=1.0,
                            max_iter=2000,
                            random_state=self.split_seed,
                        ),
                    ),
                ]
            )
            model.fit(self.x_train[list(row_key)], self.y_train[list(row_key)])
            result = float(accuracy_score(evaluation_y, model.predict(evaluation_x)))
        cache[row_key] = result
        return result

    def utility_for_owners(
        self, owner_ids: Iterable[str], *, use_test: bool = False
    ) -> float:
        ordered = tuple(sorted(set(owner_ids)))
        unknown = set(ordered).difference(self.owner_rows)
        if unknown:
            raise KeyError(f"unknown owner IDs: {sorted(unknown)}")
        rows = [row for owner in ordered for row in self.owner_rows[owner]]
        return self.utility_for_rows(rows, use_test=use_test)


def _dataset_hash(*arrays: np.ndarray) -> str:
    digest = hashlib.sha256()
    for array in arrays:
        contiguous = np.ascontiguousarray(array)
        digest.update(str(contiguous.shape).encode("ascii"))
        digest.update(contiguous.dtype.str.encode("ascii"))
        digest.update(contiguous.tobytes())
    return digest.hexdigest()


def load_owner_dataset(seed: int = 42, dataset_name: str = "breast_cancer") -> OwnerDataset:
    """Load a bundled sklearn dataset and construct a stratified owner split."""

    loaders = {
        "breast_cancer": (load_breast_cancer, "sklearn-breast-cancer-wisconsin-diagnostic"),
        "wine": (load_wine, "sklearn-wine"),
        "digits": (load_digits, "sklearn-digits"),
    }
    try:
        loader, dataset_id = loaders[dataset_name]
    except KeyError as exc:
        raise ValueError(f"unsupported owner dataset: {dataset_name}") from exc
    source = loader()
    all_indices = np.arange(len(source.target))
    train_validation, test_indices = train_test_split(
        all_indices,
        test_size=0.20,
        stratify=source.target,
        random_state=seed,
    )
    train_indices, validation_indices = train_test_split(
        train_validation,
        test_size=0.25,
        stratify=source.target[train_validation],
        random_state=seed,
    )

    x_train = np.asarray(source.data[train_indices], dtype=float)
    y_train = np.asarray(source.target[train_indices], dtype=int)
    owner_lists: dict[str, list[int]] = {owner: [] for owner in OWNER_IDS}
    for label in sorted(np.unique(y_train)):
        local_rows = np.flatnonzero(y_train == label)
        for offset, local_row in enumerate(local_rows):
            owner_lists[OWNER_IDS[offset % len(OWNER_IDS)]].append(int(local_row))
    owner_rows = {owner: tuple(rows) for owner, rows in owner_lists.items()}

    return OwnerDataset(
        dataset_id=dataset_id,
        source_shape=tuple(source.data.shape),
        train_indices=np.asarray(train_indices),
        validation_indices=np.asarray(validation_indices),
        test_indices=np.asarray(test_indices),
        x_train=x_train,
        y_train=y_train,
        x_validation=np.asarray(source.data[validation_indices], dtype=float),
        y_validation=np.asarray(source.target[validation_indices], dtype=int),
        x_test=np.asarray(source.data[test_indices], dtype=float),
        y_test=np.asarray(source.target[test_indices], dtype=int),
        owner_rows=owner_rows,
        noise_rates={owner: 0.0 for owner in OWNER_IDS},
        split_seed=seed,
        dataset_hash=_dataset_hash(source.data, source.target, train_indices, validation_indices, test_indices),
    )


def make_analytic_valuation_cases() -> tuple[ValuationCase, ...]:
    owner_ids = tuple(f"o{index}" for index in range(6))
    qualities = dict(zip(owner_ids, (1.0, 2.0, 3.0, 4.0, 5.0, 6.0), strict=True))

    def additive(coalition: tuple[str, ...]) -> float:
        return float(sum(qualities[owner] for owner in set(coalition)))

    def duplicate(coalition: tuple[str, ...]) -> float:
        members = set(coalition)
        shared_information = 4.0 if members.intersection({"o0", "o1"}) else 0.0
        return shared_information + sum(qualities[owner] for owner in members - {"o0", "o1"})

    def complementary(coalition: tuple[str, ...]) -> float:
        members = set(coalition)
        bonus = 10.0 if {"o2", "o3"}.issubset(members) else 0.0
        return float(sum(qualities[owner] for owner in members) + bonus)

    def harmful(coalition: tuple[str, ...]) -> float:
        members = set(coalition)
        penalty = 15.0 if "o5" in members else 0.0
        return float(sum(qualities[owner] for owner in members) - penalty)

    return (
        ValuationCase(
            case_id="C-add",
            owner_ids=owner_ids,
            utility=additive,
            case_type="analytic",
            truth_scores=qualities,
            metadata={
                "setting": "S1",
                "benchmark_setting": "valuation_game",
                "pilot": False,
                "property": "additive",
            },
        ),
        ValuationCase(
            case_id="C-dup",
            owner_ids=owner_ids,
            utility=duplicate,
            case_type="analytic",
            metadata={
                "setting": "S1",
                "benchmark_setting": "valuation_game",
                "pilot": False,
                "property": "duplicate",
                "duplicate_pair": ("o0", "o1"),
            },
        ),
        ValuationCase(
            case_id="C-comp",
            owner_ids=owner_ids,
            utility=complementary,
            case_type="analytic",
            metadata={
                "setting": "S1",
                "benchmark_setting": "valuation_game",
                "pilot": False,
                "property": "complementary",
                "complementary_pair": ("o2", "o3"),
            },
        ),
        ValuationCase(
            case_id="C-harmful",
            owner_ids=owner_ids,
            utility=harmful,
            case_type="analytic",
            truth_scores={**qualities, "o5": qualities["o5"] - 15.0},
            metadata={
                "setting": "S1",
                "benchmark_setting": "valuation_game",
                "pilot": True,
                "property": "non_monotone_harmful_owner",
                "bad_owner": "o5",
            },
        ),
    )


def _duplicate_dataset(clean: OwnerDataset) -> OwnerDataset:
    source_rows = clean.owner_rows["o0"]
    start = len(clean.x_train)
    copied_rows = tuple(range(start, start + len(source_rows)))
    return replace(
        clean,
        dataset_id=f"{clean.dataset_id}-duplicate-o0",
        x_train=np.concatenate((clean.x_train, clean.x_train[list(source_rows)]), axis=0),
        y_train=np.concatenate((clean.y_train, clean.y_train[list(source_rows)]), axis=0),
        owner_rows={**clean.owner_rows, "o8": copied_rows},
        noise_rates={**clean.noise_rates, "o8": 0.0},
        duplicate_of={"o8": "o0"},
        dataset_hash=_dataset_hash(clean.x_train, clean.y_train, np.asarray(source_rows)),
    )


def _noisy_dataset(clean: OwnerDataset) -> OwnerDataset:
    noisy_y = clean.y_train.copy()
    owner_rows = np.asarray(clean.owner_rows["o7"], dtype=int)
    flip_count = round(0.4 * len(owner_rows))
    selected = np.random.default_rng(43).choice(owner_rows, size=flip_count, replace=False)
    noisy_y[selected] = 1 - noisy_y[selected]
    return replace(
        clean,
        dataset_id=f"{clean.dataset_id}-noise-o7",
        y_train=noisy_y,
        noise_rates={**clean.noise_rates, "o7": 0.4},
        dataset_hash=_dataset_hash(clean.x_train, noisy_y, clean.train_indices),
    )


def _size_skewed_dataset(clean: OwnerDataset) -> OwnerDataset:
    rng = np.random.default_rng(clean.split_seed + 101)
    shuffled = rng.permutation(len(clean.x_train))
    fixed_sizes = (12, 16, 24, 32, 40, 48, 64)
    final_size = len(shuffled) - sum(fixed_sizes)
    sizes = (*fixed_sizes, final_size)
    if final_size <= 0:
        raise ValueError("owner-size pilot requires at least 237 training rows")
    owner_rows: dict[str, tuple[int, ...]] = {}
    start = 0
    for owner, size in zip(OWNER_IDS, sizes, strict=True):
        owner_rows[owner] = tuple(sorted(int(row) for row in shuffled[start : start + size]))
        start += size
    assignment = np.asarray(
        [row for owner in OWNER_IDS for row in owner_rows[owner]], dtype=int
    )
    return replace(
        clean,
        dataset_id=f"{clean.dataset_id}-owner-size-skew",
        owner_rows=owner_rows,
        dataset_hash=_dataset_hash(clean.x_train, clean.y_train, assignment),
    )


def _real_case(case_id: str, dataset: OwnerDataset, **metadata: object) -> ValuationCase:
    return ValuationCase(
        case_id=case_id,
        owner_ids=dataset.owner_ids,
        utility=lambda coalition: dataset.utility_for_owners(coalition),
        case_type="real_owner_data",
        metadata={
            "setting": "S2",
            "benchmark_setting": "valuation_owner_ml",
            "pilot": False,
            "owner_dataset": dataset,
            "dataset_hash": dataset.dataset_hash,
            **metadata,
        },
    )


def make_real_valuation_cases(seed: int = 42) -> tuple[ValuationCase, ...]:
    clean = load_owner_dataset(seed)
    wine = load_owner_dataset(seed, "wine")
    digits = load_owner_dataset(seed, "digits")
    duplicate = _duplicate_dataset(clean)
    noisy = _noisy_dataset(clean)
    size_skewed = _size_skewed_dataset(clean)
    return (
        _real_case("C-real-clean", clean),
        _real_case("C-real-dup", duplicate, duplicate_pair=("o0", "o8")),
        _real_case("C-real-noise", noisy, bad_owner="o7"),
        _real_case("C-real-wine-clean", wine),
        _real_case("C-real-digits-clean", digits),
        _real_case(
            "C-real-size-skew",
            size_skewed,
            pilot=True,
            property="heterogeneous_owner_size",
        ),
    )


def _cost_for_owner(case: ValuationCase, owner: str) -> Decimal:
    dataset = case.metadata.get("owner_dataset")
    if isinstance(dataset, OwnerDataset):
        sample_count = len(dataset.owner_rows[owner])
        noise_rate = dataset.noise_rates[owner]
    else:
        sample_count = 1
        noise_rate = 0.0
    return Decimal(str(10 + 0.05 * sample_count + 20 * noise_rate))


def make_procurement_cases(
    valuation_cases: Iterable[ValuationCase] | None = None, *, seed: int = 42
) -> tuple[ProcurementCase, ...]:
    """Derive truthful public reports and evaluator-only costs for S3/S4."""

    source_candidates = tuple(
        valuation_cases
        or (*make_analytic_valuation_cases(), *make_real_valuation_cases(seed))
    )
    sources = tuple(
        source for source in source_candidates if not source.metadata.get("pilot", False)
    )
    cases: list[ProcurementCase] = []
    for source in sources:
        true_costs = {owner: _cost_for_owner(source, owner) for owner in source.owner_ids}
        total_cost = sum(true_costs.values(), Decimal("0"))
        empty_utility = source.utility(())
        seller_values = {
            owner: max(0.0, source.utility((owner,)) - empty_utility)
            for owner in source.owner_ids
        }
        for ratio in (0.3, 0.5, 0.7):
            ratio_decimal = Decimal(str(ratio))
            public = ProcurementInput(
                seller_ids=source.owner_ids,
                reported_costs=dict(true_costs),
                budget=total_cost * ratio_decimal,
                utility=source.utility,
                seller_values=seller_values,
                metadata={"source_case_id": source.case_id},
            )
            metadata = {
                "setting": "S3" if source.case_type == "analytic" else "S4",
                "benchmark_setting": (
                    "procurement_additive"
                    if source.case_type == "analytic"
                    else "procurement_ml"
                ),
                "pilot": False,
                "source_case_id": source.case_id,
                "budget_ratio": ratio,
            }
            if "owner_dataset" in source.metadata:
                metadata["owner_dataset"] = source.metadata["owner_dataset"]
            cases.append(
                ProcurementCase(
                    case_id=f"P-{source.case_id}-b{int(ratio * 100)}",
                    public=public,
                    true_costs=true_costs,
                    case_type=source.case_type,
                    metadata=metadata,
                    attack_labels={owner: "truthful" for owner in source.owner_ids},
                )
            )
    coverage_dataset = load_owner_dataset(seed)
    feature_count = min(6, coverage_dataset.x_train.shape[1])
    cuts = np.quantile(
        coverage_dataset.x_train[:, :feature_count],
        np.linspace(0.125, 0.875, 7),
        axis=0,
    )
    coverage_sets: dict[str, set[int]] = {}
    for index, (owner, rows) in enumerate(coverage_dataset.owner_rows.items()):
        cells: set[int] = set()
        for row in rows:
            cells.add(1000 + int(coverage_dataset.y_train[row]))
            for feature in range(feature_count):
                label = int(coverage_dataset.y_train[row])
                bin_index = int(
                    np.digitize(
                        coverage_dataset.x_train[row, feature], cuts[:, feature]
                    )
                )
                cells.add(feature * 16 + label * 8 + bin_index)
        coverage_sets[f"c{index}"] = cells
    coverage_costs = {
        f"c{index}": Decimal(str(3 + 0.05 * len(rows)))
        for index, rows in enumerate(coverage_dataset.owner_rows.values())
    }

    def coverage_utility(selected: tuple[str, ...]) -> float:
        covered: set[int] = set()
        for seller in set(selected):
            covered.update(coverage_sets[seller])
        return float(len(covered))

    total_coverage_cost = sum(coverage_costs.values(), Decimal("0"))
    coverage_values = {
        seller: coverage_utility((seller,)) for seller in coverage_sets
    }
    for ratio in (0.3, 0.5, 0.7):
        public = ProcurementInput(
            seller_ids=tuple(coverage_sets),
            reported_costs=dict(coverage_costs),
            budget=total_coverage_cost * Decimal(str(ratio)),
            utility=coverage_utility,
            seller_values=coverage_values,
            metadata={
                "utility_class": "monotone_submodular_coverage",
                "coverage_construction": "label_feature_quantile_cells",
                "dataset_id": coverage_dataset.dataset_id,
            },
        )
        cases.append(
            ProcurementCase(
                case_id=f"P-C-coverage-b{int(ratio * 100)}",
                public=public,
                true_costs=dict(coverage_costs),
                case_type="submodular",
                metadata={
                    "setting": "P2",
                    "benchmark_setting": "procurement_submodular",
                    "pilot": False,
                    "source_case_id": "C-coverage",
                    "budget_ratio": ratio,
                    "utility_class": "monotone_submodular_coverage",
                    "coverage_construction": "label_feature_quantile_cells",
                    "dataset_id": coverage_dataset.dataset_id,
                },
                attack_labels={seller: "truthful" for seller in coverage_sets},
            )
        )

    maximum_value = max(coverage_values.values())
    correlated_profiles = {
        "positive": {
            seller: Decimal(str(2.0 + coverage_values[seller] * 0.1))
            for seller in coverage_sets
        },
        "negative": {
            seller: Decimal(str(2.0 + (maximum_value - coverage_values[seller]) * 0.1))
            for seller in coverage_sets
        },
    }
    for direction, costs in correlated_profiles.items():
        public = ProcurementInput(
            seller_ids=tuple(coverage_sets),
            reported_costs=dict(costs),
            budget=sum(costs.values(), Decimal("0")) * Decimal("0.5"),
            utility=coverage_utility,
            seller_values=coverage_values,
            metadata={
                "utility_class": "monotone_submodular_coverage",
                "cost_quality_correlation": direction,
                "dataset_id": coverage_dataset.dataset_id,
            },
        )
        cases.append(
            ProcurementCase(
                case_id=f"P-C-coverage-{direction}-corr-b50",
                public=public,
                true_costs=dict(costs),
                case_type="submodular",
                metadata={
                    "setting": "P2",
                    "benchmark_setting": "procurement_submodular",
                    "pilot": True,
                    "source_case_id": "C-coverage",
                    "budget_ratio": 0.5,
                    "property": f"{direction}_cost_quality_correlation",
                    "dataset_id": coverage_dataset.dataset_id,
                },
                attack_labels={seller: "truthful" for seller in coverage_sets},
            )
        )
    return tuple(cases)


def _scaled_decimal(base: Decimal, multiplier: float) -> Decimal:
    return (base * Decimal(str(multiplier))).quantize(Decimal("0.000001"))


def make_trade_cases(seed: int = 42) -> tuple[TradeCase, ...]:
    """Create the data-utility-calibrated single-sale and double-auction cases."""

    clean = _by_case_id(make_real_valuation_cases(seed))["C-real-clean"]
    utility_lift = clean.utility(clean.owner_ids) - clean.utility(())
    base_value = Decimal(str(max(utility_lift * 1000.0, 1e-6))).quantize(Decimal("0.000001"))
    buyer_ids = tuple(f"b{index}" for index in range(len(BUYER_MULTIPLIERS)))
    seller_ids = tuple(f"s{index}" for index in range(len(SELLER_MULTIPLIERS)))
    true_values = {
        buyer: _scaled_decimal(base_value, multiplier)
        for buyer, multiplier in zip(buyer_ids, BUYER_MULTIPLIERS, strict=True)
    }
    true_costs = {
        seller: _scaled_decimal(base_value, multiplier)
        for seller, multiplier in zip(seller_ids, SELLER_MULTIPLIERS, strict=True)
    }
    middle_values = sorted(true_values.values())[4:6]
    posted_price = sum(middle_values, Decimal("0")) / Decimal("2")
    common_metadata = {
        "calibration_case_id": clean.case_id,
        "base_value": base_value,
        "split_seed": seed,
    }

    single_costs = {"s0": true_costs["s0"]}
    single_public = TradeInput(
        product_id="C-real-clean-access",
        buyer_ids=buyer_ids,
        seller_ids=("s0",),
        bids=dict(true_values),
        asks=dict(single_costs),
        posted_price=posted_price,
        metadata={
            "setting": "S5",
            "prior_values": tuple(str(value) for value in true_values.values()),
            "prior_semantics": "public_empirical_calibration_distribution",
        },
    )
    double_public = TradeInput(
        product_id="C-real-clean-access",
        buyer_ids=buyer_ids,
        seller_ids=seller_ids,
        bids=dict(true_values),
        asks=dict(true_costs),
        metadata={"setting": "S6"},
    )
    return (
        TradeCase(
            case_id="S5-single-sale",
            public=single_public,
            true_values=true_values,
            true_costs=single_costs,
            case_type="single_sale",
            metadata={
                "setting": "S5",
                "benchmark_setting": "single_sale",
                "pilot": False,
                **common_metadata,
            },
            attack_labels={actor: "truthful" for actor in (*buyer_ids, "s0")},
        ),
        TradeCase(
            case_id="S6-double-auction",
            public=double_public,
            true_values=true_values,
            true_costs=true_costs,
            case_type="double_auction",
            metadata={
                "setting": "S6",
                "benchmark_setting": "double_auction",
                "pilot": False,
                **common_metadata,
            },
            attack_labels={actor: "truthful" for actor in (*buyer_ids, *seller_ids)},
        ),
        _trade_case(
            "S5-single-sale-no-trade",
            "single_sale",
            {buyer: _scaled_decimal(base_value, 0.10 + index * 0.01) for index, buyer in enumerate(buyer_ids)},
            {"s0": _scaled_decimal(base_value, 0.90)},
            base_value,
            common_metadata,
            regime="low_demand_no_trade",
        ),
        _trade_case(
            "S6-double-thin",
            "double_auction",
            {buyer: true_values[buyer] for buyer in buyer_ids[:2]},
            {seller: true_costs[seller] for seller in seller_ids[:2]},
            base_value,
            common_metadata,
            regime="thin_2x2",
        ),
        _trade_case(
            "S6-double-buyer-heavy",
            "double_auction",
            true_values,
            {seller: true_costs[seller] for seller in seller_ids[:3]},
            base_value,
            common_metadata,
            regime="buyer_heavy_10x3",
        ),
        _trade_case(
            "S6-double-low-overlap",
            "double_auction",
            {buyer: _scaled_decimal(base_value, 0.10 + index * 0.02) for index, buyer in enumerate(buyer_ids)},
            {seller: _scaled_decimal(base_value, 0.80 + index * 0.015) for index, seller in enumerate(seller_ids)},
            base_value,
            common_metadata,
            regime="low_overlap_no_trade",
        ),
    )


def _trade_case(
    case_id: str,
    case_type: str,
    true_values: Mapping[str, Decimal],
    true_costs: Mapping[str, Decimal],
    base_value: Decimal,
    common_metadata: Mapping[str, object],
    *,
    regime: str,
) -> TradeCase:
    buyer_ids = tuple(true_values)
    seller_ids = tuple(true_costs)
    posted_price = base_value * Decimal("0.5") if case_type == "single_sale" else None
    setting = "S5" if case_type == "single_sale" else "S6"
    public = TradeInput(
        product_id="C-real-clean-access",
        buyer_ids=buyer_ids,
        seller_ids=seller_ids,
        bids=dict(true_values),
        asks=dict(true_costs),
        posted_price=posted_price,
        metadata={"setting": setting, "regime": regime},
    )
    return TradeCase(
        case_id=case_id,
        public=public,
        true_values=dict(true_values),
        true_costs=dict(true_costs),
        case_type=case_type,
        metadata={
            "setting": setting,
            "benchmark_setting": case_type,
            "pilot": True,
            "regime": regime,
            **common_metadata,
        },
        attack_labels={actor: "truthful" for actor in (*buyer_ids, *seller_ids)},
    )


def _by_case_id(cases: Iterable[ValuationCase]) -> dict[str, ValuationCase]:
    return {case.case_id: case for case in cases}


__all__ = [
    "BUYER_MULTIPLIERS",
    "OWNER_IDS",
    "SELLER_MULTIPLIERS",
    "OwnerDataset",
    "load_owner_dataset",
    "make_analytic_valuation_cases",
    "make_procurement_cases",
    "make_real_valuation_cases",
    "make_trade_cases",
]
