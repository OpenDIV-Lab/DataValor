"""Pure stress transformations and unilateral report grids."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from decimal import Decimal
from typing import Iterable

import numpy as np

from .data import OwnerDataset
from .models import ProcurementCase, ProcurementInput, TradeCase, TradeInput, ValuationCase

REPORT_MULTIPLIERS = (0.5, 0.75, 1.0, 1.25, 1.5)


def duplicate_case(case: ValuationCase, owner_id: str) -> ValuationCase:
    """Add a perfect substitute without mutating the source characteristic game."""

    if owner_id not in case.owner_ids:
        raise KeyError(f"unknown owner: {owner_id}")
    duplicate_id = f"{owner_id}__duplicate"
    if duplicate_id in case.owner_ids:
        raise ValueError(f"duplicate owner ID already exists: {duplicate_id}")

    def utility(coalition: tuple[str, ...]) -> float:
        mapped = {owner_id if owner == duplicate_id else owner for owner in coalition}
        return float(case.utility(tuple(owner for owner in case.owner_ids if owner in mapped)))

    return ValuationCase(
        case_id=f"{case.case_id}-duplicate-{owner_id}",
        owner_ids=(*case.owner_ids, duplicate_id),
        utility=utility,
        case_type=case.case_type,
        metadata={**case.metadata, "duplicate_pair": (owner_id, duplicate_id), "stress": "duplicate"},
    )


def noise_case(
    case: ValuationCase,
    owner_id: str,
    rate: float,
    seed: int,
) -> ValuationCase:
    """Flip a deterministic fraction of one real owner's training labels."""

    dataset = case.metadata.get("owner_dataset")
    if not isinstance(dataset, OwnerDataset):
        raise ValueError("noise stress requires an OwnerDataset-backed case")
    if owner_id not in dataset.owner_rows:
        raise KeyError(f"unknown owner: {owner_id}")
    if not 0.0 <= rate <= 1.0:
        raise ValueError("noise rate must be in [0, 1]")

    labels = dataset.y_train.copy()
    rows = np.asarray(dataset.owner_rows[owner_id], dtype=int)
    flip_count = round(rate * len(rows))
    if flip_count:
        selected = np.random.default_rng(seed).choice(rows, size=flip_count, replace=False)
        classes = np.unique(labels)
        if len(classes) != 2:
            raise ValueError("label flipping currently requires binary labels")
        low, high = classes
        labels[selected] = np.where(labels[selected] == low, high, low)
    digest = hashlib.sha256(dataset.dataset_hash.encode("ascii"))
    digest.update(labels.tobytes())
    digest.update(f"{owner_id}:{rate}:{seed}".encode("ascii"))
    stressed = replace(
        dataset,
        dataset_id=f"{dataset.dataset_id}-noise-{owner_id}-{rate}",
        y_train=labels,
        noise_rates={**dataset.noise_rates, owner_id: float(rate)},
        dataset_hash=digest.hexdigest(),
    )
    return ValuationCase(
        case_id=f"{case.case_id}-noise-{owner_id}-{rate}",
        owner_ids=case.owner_ids,
        utility=lambda coalition: stressed.utility_for_owners(coalition),
        case_type=case.case_type,
        metadata={
            **case.metadata,
            "owner_dataset": stressed,
            "dataset_hash": stressed.dataset_hash,
            "bad_owner": owner_id,
            "stress": "label_noise",
            "noise_rate": float(rate),
            "noise_seed": seed,
        },
    )


def cost_reports(
    case: ProcurementCase,
    multipliers: Iterable[float] = REPORT_MULTIPLIERS,
) -> dict[tuple[str, float], ProcurementInput]:
    """Return every one-seller deviation while all other reports stay truthful."""

    result: dict[tuple[str, float], ProcurementInput] = {}
    for seller in case.public.seller_ids:
        if seller not in case.true_costs:
            continue
        for raw_multiplier in multipliers:
            multiplier = float(raw_multiplier)
            reports = dict(case.true_costs)
            reports[seller] = case.true_costs[seller] * Decimal(str(multiplier))
            result[(seller, multiplier)] = replace(case.public, reported_costs=reports)
    return result


def bid_reports(
    case: TradeCase,
    multipliers: Iterable[float] = REPORT_MULTIPLIERS,
) -> dict[tuple[str, float], TradeInput]:
    """Return unilateral buyer-bid and seller-ask deviations from true types."""

    result: dict[tuple[str, float], TradeInput] = {}
    for buyer in case.public.buyer_ids:
        if buyer not in case.true_values:
            continue
        for raw_multiplier in multipliers:
            multiplier = float(raw_multiplier)
            bids = dict(case.true_values)
            bids[buyer] = case.true_values[buyer] * Decimal(str(multiplier))
            result[(buyer, multiplier)] = replace(
                case.public,
                bids=bids,
                asks=dict(case.true_costs),
            )
    for seller in case.public.seller_ids:
        if seller not in case.true_costs:
            continue
        for raw_multiplier in multipliers:
            multiplier = float(raw_multiplier)
            asks = dict(case.true_costs)
            asks[seller] = case.true_costs[seller] * Decimal(str(multiplier))
            result[(seller, multiplier)] = replace(
                case.public,
                bids=dict(case.true_values),
                asks=asks,
            )
    return result


__all__ = [
    "REPORT_MULTIPLIERS",
    "bid_reports",
    "cost_reports",
    "duplicate_case",
    "noise_case",
]
