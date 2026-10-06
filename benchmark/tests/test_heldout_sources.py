from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from datamechbench.heldout_sources import (
    build_owner_dataset_from_arff,
    calibrate_elexon_profile,
    calibrate_procurement_costs,
    extract_chilecompra_amounts,
    extract_chilecompra_award_amounts,
    extract_chilecompra_order_totals,
    select_chilecompra_order_codes,
)


def _write_arff(path: Path) -> None:
    rows = []
    for index in range(80):
        label = "yes" if index % 2 else "no"
        category = ("a", "b", "c")[index % 3]
        rows.append(f"{index / 10:.1f},{category},{label}")
    path.write_text(
        "@relation fixture\n"
        "@attribute numeric numeric\n"
        "@attribute category {a,b,c}\n"
        "@attribute class {no,yes}\n"
        "@data\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )


def test_openml_arff_builds_leak_free_numeric_owner_dataset(tmp_path: Path) -> None:
    source = tmp_path / "fixture.arff"
    _write_arff(source)

    dataset = build_owner_dataset_from_arff(
        source,
        dataset_id="openml-fixture",
        target_attribute="class",
        seed=1701,
        maximum_rows=60,
    )

    assert dataset.source_shape == (60, 2)
    assert dataset.x_train.dtype.kind == "f"
    assert len(dataset.owner_ids) == 8
    assert set(dataset.train_indices).isdisjoint(dataset.validation_indices)
    assert set(dataset.train_indices).isdisjoint(dataset.test_indices)
    assert set(dataset.validation_indices).isdisjoint(dataset.test_indices)
    assert sum(len(rows) for rows in dataset.owner_rows.values()) == len(dataset.x_train)
    assert len(dataset.dataset_hash) == 64


def test_chilecompra_extractor_uses_only_positive_comparable_amounts() -> None:
    records = [
        {
            "date": "2024-03-15T10:00:00Z",
            "bids": {"details": [
                {"value": {"amount": 100, "currency": "CLP"}, "tenderers": [{"name": "secret"}]},
                {"value": {"amount": 250, "currency": "CLP"}},
                {"value": {"amount": -2, "currency": "CLP"}},
                {"value": {"amount": 10, "currency": "USD"}},
            ]},
        },
        {
            "date": "2024-03-16T10:00:00Z",
            "bids": {"details": [{"value": {"amount": 999, "currency": "CLP"}}]},
        },
    ]

    amounts = extract_chilecompra_amounts(
        records, cohort_date="2024-03-15", currency="CLP"
    )

    assert amounts == (100.0, 250.0)
    assert "secret" not in json.dumps(amounts)


def test_chilecompra_cohort_uses_tender_start_not_release_update_date() -> None:
    records = [{
        "date": "2024-09-13T00:00:00Z",
        "tender": {"tenderPeriod": {"startDate": "2024-06-14T12:00:00Z"}},
        "bids": {"details": [{"value": {"amount": 321, "currency": "CLP"}}]},
    }]

    assert extract_chilecompra_amounts(
        records, cohort_date="2024-06-14"
    ) == (321.0,)
    assert extract_chilecompra_amounts(
        records, cohort_date="2024-09-13"
    ) == ()


def test_chilecompra_award_extractor_uses_release_date_and_clp_value() -> None:
    records = [{
        "date": "2024-06-14T12:00:00Z",
        "awards": [
            {"value": {"amount": 123, "currency": "CLP"}, "suppliers": [{"name": "private"}]},
            {"value": {"amount": 456, "currency": "USD"}},
            {"value": {"amount": -2, "currency": "CLP"}},
        ],
    }, {
        "date": "2024-06-15T12:00:00Z",
        "awards": [{"value": {"amount": 999, "currency": "CLP"}}],
    }]

    amounts = extract_chilecompra_award_amounts(
        records, cohort_date="2024-06-14"
    )

    assert amounts == (123.0,)
    assert "private" not in json.dumps(amounts)


def test_chilecompra_order_extractor_keeps_only_accepted_clp_totals() -> None:
    payloads = [
        {"Listado": [{
            "Codigo": "private-code-1",
            "Proveedor": {"Nombre": "private-supplier"},
            "TipoMoneda": "CLP",
            "Estado": "Aceptada",
            "Total": 3_979_800,
        }]},
        {"Listado": [{
            "Codigo": "private-code-2",
            "TipoMoneda": "USD",
            "Estado": "Aceptada",
            "Total": 999,
        }]},
        {"Listado": [{
            "Codigo": "private-code-3",
            "TipoMoneda": "CLP",
            "Estado": "Cancelada",
            "Total": 888,
        }]},
        {"Listado": [{
            "Codigo": "private-code-4",
            "TipoMoneda": "CLP",
            "Estado": "Aceptada",
            "Total": -1,
        }]},
    ]

    amounts = extract_chilecompra_order_totals(payloads)

    assert amounts == (3_979_800.0,)
    assert "private" not in json.dumps(amounts)


def test_chilecompra_code_selection_is_unique_sorted_and_outcome_blind() -> None:
    payload = {"Listado": [
        {"Codigo": "z-2", "Nombre": "expensive"},
        {"Codigo": "a-1", "Nombre": "cheap"},
        {"Codigo": "z-2", "Nombre": "duplicate"},
        {"Codigo": "m-3", "Nombre": "unknown"},
    ]}

    assert select_chilecompra_order_codes(payload, sample_size=2) == ("a-1", "m-3")


def test_procurement_calibration_is_deterministic_positive_and_median_normalized() -> None:
    amounts = tuple(float(value) for value in range(10, 210, 10))

    first = calibrate_procurement_costs(amounts, seller_count=8)
    second = calibrate_procurement_costs(tuple(reversed(amounts)), seller_count=8)

    assert first == second
    assert tuple(first) == tuple(f"o{index}" for index in range(8))
    values = np.asarray([float(value) for value in first.values()])
    assert np.all(values > 0)
    assert np.isclose(np.median(values), 1.0)


def test_elexon_calibration_anonymizes_units_and_preserves_price_order() -> None:
    rows = []
    for index in range(24):
        rows.append({
            "bmUnit": f"private-unit-{index}",
            "pairId": 1,
            "bid": float(30 + index),
            "offer": float(10 + index),
        })
    payload = {"metadata": {"datasets": ["BOD"]}, "data": rows}

    profile = calibrate_elexon_profile(payload, market_size=16)

    assert len(profile.buyer_values) == len(profile.seller_costs) == 16
    assert profile.buyer_values == tuple(sorted(profile.buyer_values, reverse=True))
    assert profile.seller_costs == tuple(sorted(profile.seller_costs))
    assert min(profile.buyer_values + profile.seller_costs) >= 0.0
    assert max(profile.buyer_values + profile.seller_costs) <= 1.0
    assert not hasattr(profile, "unit_ids")
    assert profile.source_row_count == 24
