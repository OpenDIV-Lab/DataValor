"""Deterministic, anonymizing transforms for frozen held-out sources."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
from scipy.io import arff
from sklearn.model_selection import train_test_split

from .data import OWNER_IDS, OwnerDataset, _dataset_hash


@dataclass(frozen=True)
class CalibratedTradeProfile:
    buyer_values: tuple[float, ...]
    seller_costs: tuple[float, ...]
    source_row_count: int
    retained_bid_count: int
    retained_offer_count: int


def _text(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def build_owner_dataset_from_arff(
    path: str | Path,
    *,
    dataset_id: str,
    target_attribute: str,
    seed: int,
    maximum_rows: int,
) -> OwnerDataset:
    """Create an owner game using train-only preprocessing statistics."""

    records, _ = arff.loadarff(Path(path))
    columns = tuple(records.dtype.names or ())
    if target_attribute not in columns:
        raise ValueError(f"target attribute {target_attribute!r} is absent")
    feature_columns = tuple(column for column in columns if column != target_attribute)
    raw_target = np.asarray([_text(value) for value in records[target_attribute]])
    source_indices = np.arange(len(records))
    if len(records) > maximum_rows:
        source_indices, _ = train_test_split(
            source_indices,
            train_size=maximum_rows,
            stratify=raw_target,
            random_state=seed,
        )
        source_indices = np.sort(source_indices)
    capped_target = raw_target[source_indices]
    capped_indices = np.arange(len(source_indices))
    train_validation, test_indices = train_test_split(
        capped_indices,
        test_size=0.20,
        stratify=capped_target,
        random_state=seed,
    )
    train_indices, validation_indices = train_test_split(
        train_validation,
        test_size=0.25,
        stratify=capped_target[train_validation],
        random_state=seed,
    )

    transformed: list[np.ndarray] = []
    for column in feature_columns:
        values = np.asarray(records[column])[source_indices]
        if values.dtype.kind in "iuf":
            numeric = values.astype(float)
            finite_train = numeric[train_indices][np.isfinite(numeric[train_indices])]
            fill = float(np.median(finite_train)) if len(finite_train) else 0.0
            numeric = np.where(np.isfinite(numeric), numeric, fill)
            transformed.append(numeric)
            continue
        text_values = np.asarray([_text(value) for value in values])
        categories = tuple(sorted(set(text_values[train_indices])))
        encoding = {category: index for index, category in enumerate(categories)}
        transformed.append(
            np.asarray([float(encoding.get(value, -1)) for value in text_values])
        )
    matrix = np.column_stack(transformed).astype(float)
    target_labels = tuple(sorted(set(capped_target[train_indices])))
    target_encoding = {label: index for index, label in enumerate(target_labels)}
    if any(label not in target_encoding for label in capped_target):
        raise ValueError("validation/test target contains a class absent from training")
    encoded_target = np.asarray([target_encoding[label] for label in capped_target], dtype=int)

    x_train = matrix[train_indices]
    y_train = encoded_target[train_indices]
    owner_lists: dict[str, list[int]] = {owner: [] for owner in OWNER_IDS}
    for label in sorted(np.unique(y_train)):
        local_rows = np.flatnonzero(y_train == label)
        for offset, local_row in enumerate(local_rows):
            owner_lists[OWNER_IDS[offset % len(OWNER_IDS)]].append(int(local_row))
    owner_rows = {owner: tuple(rows) for owner, rows in owner_lists.items()}
    dataset_hash = _dataset_hash(
        matrix,
        encoded_target,
        source_indices,
        train_indices,
        validation_indices,
        test_indices,
    )
    return OwnerDataset(
        dataset_id=dataset_id,
        source_shape=(len(source_indices), len(feature_columns)),
        train_indices=np.asarray(train_indices),
        validation_indices=np.asarray(validation_indices),
        test_indices=np.asarray(test_indices),
        x_train=x_train,
        y_train=y_train,
        x_validation=matrix[validation_indices],
        y_validation=encoded_target[validation_indices],
        x_test=matrix[test_indices],
        y_test=encoded_target[test_indices],
        owner_rows=owner_rows,
        noise_rates={owner: 0.0 for owner in OWNER_IDS},
        split_seed=seed,
        dataset_hash=dataset_hash,
    )


def _record_date(record: Mapping[str, Any]) -> str:
    tender = record.get("tender")
    if isinstance(tender, Mapping):
        period = tender.get("tenderPeriod")
        if isinstance(period, Mapping):
            tender_start = str(period.get("startDate", ""))[:10]
            if tender_start:
                return tender_start
    return str(record.get("date", ""))[:10]


def _bid_amounts(record: Mapping[str, Any], currency: str) -> list[float]:
    bids = record.get("bids")
    details = bids.get("details") if isinstance(bids, Mapping) else None
    if not isinstance(details, list):
        return []
    amounts: list[float] = []
    for bid in details:
        value = bid.get("value") if isinstance(bid, Mapping) else None
        if not isinstance(value, Mapping) or str(value.get("currency", "")) != currency:
            continue
        try:
            amount = float(value.get("amount"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(amount) and amount > 0:
            amounts.append(amount)
    return amounts


def extract_chilecompra_amounts(
    records: Iterable[Mapping[str, Any]],
    *,
    cohort_date: str,
    currency: str = "CLP",
) -> tuple[float, ...]:
    """Extract anonymous same-currency bid amounts for one frozen day."""

    amounts: list[float] = []
    for outer in records:
        releases = outer.get("releases") if isinstance(outer, Mapping) else None
        candidates = releases if isinstance(releases, list) else (outer,)
        for record in candidates:
            if not isinstance(record, Mapping) or _record_date(record) != cohort_date:
                continue
            amounts.extend(_bid_amounts(record, currency))
    return tuple(sorted(amounts))


def extract_chilecompra_award_amounts(
    records: Iterable[Mapping[str, Any]],
    *,
    cohort_date: str,
    currency: str = "CLP",
) -> tuple[float, ...]:
    """Extract anonymous same-currency award values by OCDS release date."""

    amounts: list[float] = []
    for outer in records:
        releases = outer.get("releases") if isinstance(outer, Mapping) else None
        candidates = releases if isinstance(releases, list) else (outer,)
        for record in candidates:
            if not isinstance(record, Mapping):
                continue
            if str(record.get("date", ""))[:10] != cohort_date:
                continue
            awards = record.get("awards")
            if not isinstance(awards, list):
                continue
            for award in awards:
                value = award.get("value") if isinstance(award, Mapping) else None
                if not isinstance(value, Mapping) or str(value.get("currency", "")) != currency:
                    continue
                try:
                    amount = float(value.get("amount"))
                except (TypeError, ValueError):
                    continue
                if math.isfinite(amount) and amount > 0:
                    amounts.append(amount)
    return tuple(sorted(amounts))


def extract_chilecompra_order_totals(
    payloads: Iterable[Mapping[str, Any]],
    *,
    currency: str = "CLP",
    accepted_states: tuple[str, ...] = ("Aceptada",),
) -> tuple[float, ...]:
    """Extract anonymous order totals from official MercadoPublico details."""

    amounts: list[float] = []
    for payload in payloads:
        orders = payload.get("Listado") if isinstance(payload, Mapping) else None
        if not isinstance(orders, list):
            continue
        for order in orders:
            if not isinstance(order, Mapping):
                continue
            if str(order.get("TipoMoneda", "")) != currency:
                continue
            if str(order.get("Estado", "")) not in accepted_states:
                continue
            try:
                amount = float(order.get("Total"))
            except (TypeError, ValueError):
                continue
            if math.isfinite(amount) and amount > 0:
                amounts.append(amount)
    return tuple(sorted(amounts))


def select_chilecompra_order_codes(
    payload: Mapping[str, Any], *, sample_size: int = 64
) -> tuple[str, ...]:
    """Freeze a result-independent order sample using identifiers only."""

    orders = payload.get("Listado") if isinstance(payload, Mapping) else None
    if not isinstance(orders, list):
        raise ValueError("ChileCompra list payload is missing Listado")
    codes = sorted({
        str(order.get("Codigo", "")).strip()
        for order in orders
        if isinstance(order, Mapping) and str(order.get("Codigo", "")).strip()
    })
    if len(codes) < sample_size:
        raise ValueError(f"need at least {sample_size} unique ChileCompra orders")
    return tuple(codes[:sample_size])


def _winsorized(values: Iterable[float]) -> np.ndarray:
    array = np.asarray(tuple(values), dtype=float)
    array = array[np.isfinite(array) & (array > 0)]
    if not len(array):
        raise ValueError("calibration requires positive finite values")
    low, high = np.quantile(array, (0.025, 0.975))
    return np.clip(array, low, high)


def calibrate_procurement_costs(
    amounts: Iterable[float], *, seller_count: int = 8
) -> dict[str, Decimal]:
    """Turn an empirical spend distribution into anonymous normalized costs."""

    transformed = np.log1p(_winsorized(amounts))
    if len(transformed) < seller_count:
        raise ValueError(f"need at least {seller_count} procurement amounts")
    quantiles = (np.arange(seller_count, dtype=float) + 0.5) / seller_count
    selected = np.quantile(transformed, quantiles)
    median = float(np.median(selected))
    normalized = selected / median
    return {
        f"o{index}": Decimal(str(round(float(value), 9)))
        for index, value in enumerate(normalized)
    }


def _unit_medians(payload: Mapping[str, Any], field: str) -> np.ndarray:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise ValueError("Elexon payload is missing data rows")
    grouped: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        try:
            raw = float(row.get(field))
        except (TypeError, ValueError):
            continue
        value = abs(raw) if field == "bid" else raw
        if not math.isfinite(value) or value <= 0:
            continue
        key = (str(row.get("bmUnit", "")), str(row.get("pairId", "")))
        grouped.setdefault(key, []).append(value)
    return np.asarray([np.median(values) for values in grouped.values()], dtype=float)


def _unit_interval(values: np.ndarray) -> np.ndarray:
    clipped = _winsorized(values)
    low, high = float(np.min(clipped)), float(np.max(clipped))
    if high == low:
        return np.full_like(clipped, 0.5)
    return (clipped - low) / (high - low)


def calibrate_elexon_profile(
    payload: Mapping[str, Any], *, market_size: int
) -> CalibratedTradeProfile:
    """Build an identity-free balanced type profile from Elexon BOD prices."""

    rows = payload.get("data")
    source_count = len(rows) if isinstance(rows, list) else 0
    bids = _unit_interval(_unit_medians(payload, "bid"))
    offers = _unit_interval(_unit_medians(payload, "offer"))
    if len(bids) < market_size or len(offers) < market_size:
        raise ValueError(f"Elexon profile requires {market_size} bids and offers")
    buyer_values = tuple(float(value) for value in sorted(bids, reverse=True)[:market_size])
    seller_costs = tuple(float(value) for value in sorted(offers)[:market_size])
    return CalibratedTradeProfile(
        buyer_values,
        seller_costs,
        source_count,
        len(bids),
        len(offers),
    )


__all__ = [
    "CalibratedTradeProfile",
    "build_owner_dataset_from_arff",
    "calibrate_elexon_profile",
    "calibrate_procurement_costs",
    "extract_chilecompra_award_amounts",
    "extract_chilecompra_amounts",
    "extract_chilecompra_order_totals",
    "select_chilecompra_order_codes",
]
