"""Source-grounded workbench applications with small redistributable samples.

Observed records retain their official source URLs. Monetary values, budgets,
offers and participant strategies are workflow assumptions, not reported sales.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


NYC_TLC_URL = "https://data.cityofnewyork.us/resource/rwwi-khbc.json?$limit=12"
NYC_ZONE_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"
EIA_URL = "https://api.eia.gov/v2/electricity/rto/region-data/data/"
MIMIC_URL = "https://physionet.org/content/mimic-iv-demo/2.2/"
SEC_API_URL = "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/"
FRED_DFF_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFF&cosd=2024-07-01&coed=2024-07-12"


_NYC_TRIPS = [
    {"vendorid": 2, "tpep_pickup_datetime": "2024-01-01T00:57:55.000", "tpep_dropoff_datetime": "2024-01-01T01:17:43.000", "passenger_count": 1, "trip_distance": 1.72, "pulocationid": 186, "dolocationid": 79, "payment_type": 2, "fare_amount": 17.7, "tip_amount": 0.0, "total_amount": 22.7},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:03:00.000", "tpep_dropoff_datetime": "2024-01-01T00:09:36.000", "passenger_count": 1, "trip_distance": 1.8, "pulocationid": 140, "dolocationid": 236, "payment_type": 1, "fare_amount": 10.0, "tip_amount": 3.75, "total_amount": 18.75},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:17:06.000", "tpep_dropoff_datetime": "2024-01-01T00:35:01.000", "passenger_count": 1, "trip_distance": 4.7, "pulocationid": 236, "dolocationid": 79, "payment_type": 1, "fare_amount": 23.3, "tip_amount": 3.0, "total_amount": 31.3},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:36:38.000", "tpep_dropoff_datetime": "2024-01-01T00:44:56.000", "passenger_count": 1, "trip_distance": 1.4, "pulocationid": 79, "dolocationid": 211, "payment_type": 1, "fare_amount": 10.0, "tip_amount": 2.0, "total_amount": 17.0},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:46:51.000", "tpep_dropoff_datetime": "2024-01-01T00:52:57.000", "passenger_count": 1, "trip_distance": 0.8, "pulocationid": 211, "dolocationid": 148, "payment_type": 1, "fare_amount": 7.9, "tip_amount": 3.2, "total_amount": 16.1},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:54:08.000", "tpep_dropoff_datetime": "2024-01-01T01:26:31.000", "passenger_count": 1, "trip_distance": 4.7, "pulocationid": 148, "dolocationid": 141, "payment_type": 1, "fare_amount": 29.6, "tip_amount": 6.9, "total_amount": 41.5},
    {"vendorid": 2, "tpep_pickup_datetime": "2024-01-01T00:49:44.000", "tpep_dropoff_datetime": "2024-01-01T01:15:47.000", "passenger_count": 2, "trip_distance": 10.82, "pulocationid": 138, "dolocationid": 181, "payment_type": 1, "fare_amount": 45.7, "tip_amount": 10.0, "total_amount": 64.95},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:30:40.000", "tpep_dropoff_datetime": "2024-01-01T00:58:40.000", "passenger_count": 0, "trip_distance": 3.0, "pulocationid": 246, "dolocationid": 231, "payment_type": 2, "fare_amount": 25.4, "tip_amount": 0.0, "total_amount": 30.4},
    {"vendorid": 2, "tpep_pickup_datetime": "2024-01-01T00:26:01.000", "tpep_dropoff_datetime": "2024-01-01T00:54:12.000", "passenger_count": 1, "trip_distance": 5.44, "pulocationid": 161, "dolocationid": 261, "payment_type": 2, "fare_amount": 31.0, "tip_amount": 0.0, "total_amount": 36.0},
    {"vendorid": 2, "tpep_pickup_datetime": "2024-01-01T00:28:08.000", "tpep_dropoff_datetime": "2024-01-01T00:29:16.000", "passenger_count": 1, "trip_distance": 0.04, "pulocationid": 113, "dolocationid": 113, "payment_type": 2, "fare_amount": 3.0, "tip_amount": 0.0, "total_amount": 8.0},
    {"vendorid": 2, "tpep_pickup_datetime": "2024-01-01T00:35:22.000", "tpep_dropoff_datetime": "2024-01-01T00:41:41.000", "passenger_count": 2, "trip_distance": 0.75, "pulocationid": 107, "dolocationid": 137, "payment_type": 1, "fare_amount": 7.9, "tip_amount": 0.0, "total_amount": 12.9},
    {"vendorid": 1, "tpep_pickup_datetime": "2024-01-01T00:25:00.000", "tpep_dropoff_datetime": "2024-01-01T00:34:03.000", "passenger_count": 2, "trip_distance": 1.2, "pulocationid": 158, "dolocationid": 246, "payment_type": 1, "fare_amount": 14.9, "tip_amount": 3.95, "total_amount": 23.85},
]

_NYC_ZONES = [
    {"location_id": 1, "borough": "EWR", "zone": "Newark Airport", "service_zone": "EWR"},
    {"location_id": 2, "borough": "Queens", "zone": "Jamaica Bay", "service_zone": "Boro Zone"},
    {"location_id": 3, "borough": "Bronx", "zone": "Allerton/Pelham Gardens", "service_zone": "Boro Zone"},
    {"location_id": 4, "borough": "Manhattan", "zone": "Alphabet City", "service_zone": "Yellow Zone"},
    {"location_id": 5, "borough": "Staten Island", "zone": "Arden Heights", "service_zone": "Boro Zone"},
    {"location_id": 6, "borough": "Staten Island", "zone": "Arrochar/Fort Wadsworth", "service_zone": "Boro Zone"},
    {"location_id": 7, "borough": "Queens", "zone": "Astoria", "service_zone": "Boro Zone"},
    {"location_id": 8, "borough": "Queens", "zone": "Astoria Park", "service_zone": "Boro Zone"},
]


def _trip_features() -> list[dict[str, Any]]:
    result = []
    for row in _NYC_TRIPS:
        started = datetime.fromisoformat(row["tpep_pickup_datetime"])
        finished = datetime.fromisoformat(row["tpep_dropoff_datetime"])
        minutes = (finished - started).total_seconds() / 60
        result.append({
            "pickup_hour": row["tpep_pickup_datetime"][:13],
            "pickup_zone": row["pulocationid"],
            "dropoff_zone": row["dolocationid"],
            "duration_minutes": round(minutes, 2),
            "trip_distance": row["trip_distance"],
            "speed_mph": round(row["trip_distance"] / max(minutes / 60, 1e-9), 2),
            "fare_per_mile": round(row["fare_amount"] / max(row["trip_distance"], 0.01), 2),
        })
    return result


_EIA_DEMAND = [
    {"period": f"2024-07-01T{hour:02d}", "respondent": "PJM", "respondent_name": "PJM Interconnection, LLC", "type": "D", "type_name": "Demand", "value": value, "value_units": "megawatthours"}
    for hour, value in enumerate((114253, 109243, 105028, 99200, 93301, 88285, 84545, 80893, 78698, 78431, 79947, 82934))
]


def _energy_ramps() -> list[dict[str, Any]]:
    values = [row["value"] for row in _EIA_DEMAND]
    return [
        {
            "period": row["period"],
            "demand_mwh": row["value"],
            "change_mwh": row["value"] - (values[index - 1] if index else row["value"]),
            "change_rate": round((row["value"] - (values[index - 1] if index else row["value"])) / max(values[index - 1] if index else row["value"], 1), 6),
            "peak_flag": row["value"] >= 100000,
        }
        for index, row in enumerate(_EIA_DEMAND)
    ]


def _energy_windows() -> list[dict[str, Any]]:
    records = []
    for index in range(6):
        window = _EIA_DEMAND[index : index + 3]
        values = [row["value"] for row in window]
        records.append({"window_start": window[0]["period"], "window_end": window[-1]["period"], "mean_demand_mwh": round(sum(values) / len(values), 2), "minimum_mwh": min(values), "maximum_mwh": max(values), "range_mwh": max(values) - min(values)})
    return records


_MIMIC_ADMISSIONS = [
    {"subject_id": 10004235, "hadm_id": 24181354, "admittime": "2196-02-24 14:38:00", "dischtime": "2196-03-04 14:02:00", "admission_type": "URGENT", "admission_location": "TRANSFER FROM HOSPITAL", "discharge_location": "SKILLED NURSING FACILITY", "insurance": "Medicaid", "language": "ENGLISH", "hospital_expire_flag": 0},
    {"subject_id": 10009628, "hadm_id": 25926192, "admittime": "2153-09-17 17:08:00", "dischtime": "2153-09-25 13:20:00", "admission_type": "URGENT", "admission_location": "TRANSFER FROM HOSPITAL", "discharge_location": "HOME HEALTH CARE", "insurance": "Medicaid", "language": "?", "hospital_expire_flag": 0},
    {"subject_id": 10018081, "hadm_id": 23983182, "admittime": "2134-08-18 02:02:00", "dischtime": "2134-08-23 19:35:00", "admission_type": "URGENT", "admission_location": "TRANSFER FROM HOSPITAL", "discharge_location": "SKILLED NURSING FACILITY", "insurance": "Medicare", "language": "ENGLISH", "hospital_expire_flag": 0},
    {"subject_id": 10006053, "hadm_id": 22942076, "admittime": "2111-11-13 23:39:00", "dischtime": "2111-11-15 17:20:00", "admission_type": "URGENT", "admission_location": "TRANSFER FROM HOSPITAL", "discharge_location": "DIED", "insurance": "Medicaid", "language": "ENGLISH", "hospital_expire_flag": 1},
    {"subject_id": 10031404, "hadm_id": 21606243, "admittime": "2113-08-04 18:46:00", "dischtime": "2113-08-06 20:57:00", "admission_type": "URGENT", "admission_location": "TRANSFER FROM HOSPITAL", "discharge_location": "HOME", "insurance": "Other", "language": "ENGLISH", "hospital_expire_flag": 0},
    {"subject_id": 10005817, "hadm_id": 20626031, "admittime": "2132-12-12 01:43:00", "dischtime": "2132-12-20 15:04:00", "admission_type": "URGENT", "admission_location": "TRANSFER FROM HOSPITAL", "discharge_location": "HOME HEALTH CARE", "insurance": "Medicare", "language": "ENGLISH", "hospital_expire_flag": 0},
]

_MIMIC_DIAGNOSES = [
    {"subject_id": 10035185, "hadm_id": 22580999, "seq_num": 3, "icd_code": "4139", "icd_version": 9},
    {"subject_id": 10035185, "hadm_id": 22580999, "seq_num": 10, "icd_code": "V707", "icd_version": 9},
    {"subject_id": 10035185, "hadm_id": 22580999, "seq_num": 1, "icd_code": "41401", "icd_version": 9},
    {"subject_id": 10035185, "hadm_id": 22580999, "seq_num": 9, "icd_code": "3899", "icd_version": 9},
    {"subject_id": 10035185, "hadm_id": 22580999, "seq_num": 11, "icd_code": "V8532", "icd_version": 9},
    {"subject_id": 10035185, "hadm_id": 22580999, "seq_num": 2, "icd_code": "25002", "icd_version": 9},
    {"subject_id": 10009049, "hadm_id": 22995465, "seq_num": 2, "icd_code": "4829", "icd_version": 9},
    {"subject_id": 10009049, "hadm_id": 22995465, "seq_num": 7, "icd_code": "99592", "icd_version": 9},
]

_MIMIC_LABS = [
    {"labevent_id": 172061, "subject_id": 10014354, "hadm_id": 29600294, "itemid": 51277, "charttime": "2148-08-16 00:00:00", "valuenum": 15.4, "valueuom": "%", "ref_range_lower": 10.5, "ref_range_upper": 15.5, "flag": "", "priority": "ROUTINE"},
    {"labevent_id": 172062, "subject_id": 10014354, "hadm_id": 29600294, "itemid": 51279, "charttime": "2148-08-16 00:00:00", "valuenum": 3.35, "valueuom": "m/uL", "ref_range_lower": 4.6, "ref_range_upper": 6.1, "flag": "abnormal", "priority": "ROUTINE"},
    {"labevent_id": 172068, "subject_id": 10014354, "hadm_id": 29600294, "itemid": 52172, "charttime": "2148-08-16 00:00:00", "valuenum": 49.7, "valueuom": "fL", "ref_range_lower": 35.1, "ref_range_upper": 46.3, "flag": "abnormal", "priority": "ROUTINE"},
    {"labevent_id": 172063, "subject_id": 10014354, "hadm_id": 29600294, "itemid": 51301, "charttime": "2148-08-16 00:00:00", "valuenum": 20.3, "valueuom": "K/uL", "ref_range_lower": 4.0, "ref_range_upper": 10.0, "flag": "abnormal", "priority": "ROUTINE"},
    {"labevent_id": 172050, "subject_id": 10014354, "hadm_id": 29600294, "itemid": 51249, "charttime": "2148-08-16 00:00:00", "valuenum": 31.1, "valueuom": "g/dL", "ref_range_lower": 32.0, "ref_range_upper": 37.0, "flag": "abnormal", "priority": "ROUTINE"},
    {"labevent_id": 172044, "subject_id": 10014354, "hadm_id": 29600294, "itemid": 51221, "charttime": "2148-08-16 00:00:00", "valuenum": 29.6, "valueuom": "%", "ref_range_lower": 40.0, "ref_range_upper": 51.0, "flag": "abnormal", "priority": "ROUTINE"},
]


_SEC_FUNDAMENTALS = [
    {"source_record_id": "SEC:AAPL:2023-12-30", "cik": "0000320193", "ticker": "AAPL", "issuer": "Apple Inc.", "period_start": "2023-10-01", "period_end": "2023-12-30", "assets_usd": 353_514_000_000, "revenue_usd": 119_575_000_000, "form": "10-Q", "filed": "2024-02-02", "accession": "0000320193-24-000006", "fiscal_period": "Q1"},
    {"source_record_id": "SEC:AAPL:2024-03-30", "cik": "0000320193", "ticker": "AAPL", "issuer": "Apple Inc.", "period_start": "2023-12-31", "period_end": "2024-03-30", "assets_usd": 337_411_000_000, "revenue_usd": 90_753_000_000, "form": "10-Q", "filed": "2024-05-03", "accession": "0000320193-24-000069", "fiscal_period": "Q2"},
    {"source_record_id": "SEC:AAPL:2024-06-29", "cik": "0000320193", "ticker": "AAPL", "issuer": "Apple Inc.", "period_start": "2024-03-31", "period_end": "2024-06-29", "assets_usd": 331_612_000_000, "revenue_usd": 85_777_000_000, "form": "10-Q", "filed": "2024-08-02", "accession": "0000320193-24-000081", "fiscal_period": "Q3"},
    {"source_record_id": "SEC:AAPL:2024-09-28", "cik": "0000320193", "ticker": "AAPL", "issuer": "Apple Inc.", "period_start": "2023-10-01", "period_end": "2024-09-28", "assets_usd": 364_980_000_000, "revenue_usd": 391_035_000_000, "form": "10-K", "filed": "2024-11-01", "accession": "0000320193-24-000123", "fiscal_period": "FY"},
    {"source_record_id": "SEC:MSFT:2023-12-31", "cik": "0000789019", "ticker": "MSFT", "issuer": "Microsoft Corporation", "period_start": "2023-10-01", "period_end": "2023-12-31", "assets_usd": 470_558_000_000, "revenue_usd": 62_020_000_000, "form": "10-Q", "filed": "2024-01-30", "accession": "0000950170-24-008814", "fiscal_period": "Q2"},
    {"source_record_id": "SEC:MSFT:2024-03-31", "cik": "0000789019", "ticker": "MSFT", "issuer": "Microsoft Corporation", "period_start": "2024-01-01", "period_end": "2024-03-31", "assets_usd": 484_275_000_000, "revenue_usd": 61_858_000_000, "form": "10-Q", "filed": "2024-04-25", "accession": "0000950170-24-048288", "fiscal_period": "Q3"},
    {"source_record_id": "SEC:MSFT:2024-06-30", "cik": "0000789019", "ticker": "MSFT", "issuer": "Microsoft Corporation", "period_start": "2023-07-01", "period_end": "2024-06-30", "assets_usd": 512_163_000_000, "revenue_usd": 245_122_000_000, "form": "10-K", "filed": "2024-07-30", "accession": "0000950170-24-087843", "fiscal_period": "FY"},
    {"source_record_id": "SEC:MSFT:2024-09-30", "cik": "0000789019", "ticker": "MSFT", "issuer": "Microsoft Corporation", "period_start": "2024-07-01", "period_end": "2024-09-30", "assets_usd": 523_013_000_000, "revenue_usd": 65_585_000_000, "form": "10-Q", "filed": "2024-10-30", "accession": "0000950170-24-118967", "fiscal_period": "Q1"},
]

_FRED_DFF = [
    {"source_record_id": f"DFF:2024-07-{day:02d}", "observation_date": f"2024-07-{day:02d}", "series_id": "DFF", "value": 5.33, "unit": "Percent"}
    for day in range(1, 13)
]


def _finance_point_in_time_signals() -> list[dict[str, Any]]:
    """Build an as-known panel without using filings published after each date."""
    issuer_state = (
        {"ticker": "AAPL", "issuer": "Apple Inc.", "filed": "2024-05-03", "accession": "0000320193-24-000069", "assets_usd": 337_411_000_000, "revenue_usd": 90_753_000_000, "asset_change": -4.5551, "revenue_change": -24.1045},
        {"ticker": "MSFT", "issuer": "Microsoft Corporation", "filed": "2024-04-25", "accession": "0000950170-24-048288", "assets_usd": 484_275_000_000, "revenue_usd": 61_858_000_000, "asset_change": 2.9159, "revenue_change": -0.2612},
    )
    records: list[dict[str, Any]] = []
    for rate in _FRED_DFF:
        as_of = datetime.fromisoformat(rate["observation_date"])
        for issuer in issuer_state:
            records.append({
                "source_record_id": f"PIT:{issuer['ticker']}:{rate['observation_date']}",
                "as_of_date": rate["observation_date"],
                "ticker": issuer["ticker"],
                "issuer": issuer["issuer"],
                "latest_filing_date": issuer["filed"],
                "source_accession": issuer["accession"],
                "filing_lag_days": (as_of - datetime.fromisoformat(issuer["filed"])).days,
                "latest_assets_usd": issuer["assets_usd"],
                "latest_quarter_revenue_usd": issuer["revenue_usd"],
                "asset_change_pct": issuer["asset_change"],
                "revenue_change_pct": issuer["revenue_change"],
                "effective_federal_funds_rate": rate["value"],
                "rate_regime": "restrictive",
                "point_in_time_valid": True,
            })
    return records


def _product(
    product_id: str,
    title: str,
    owner_id: str,
    records: list[dict[str, Any]],
    *,
    source_url: str,
    dataset_id: str,
    publisher: str,
    license_name: str,
    sample_kind: str,
    quality: float,
    freshness: float,
    asking_price: float,
    description: str,
    purposes: list[str],
    tags: list[str],
    commercial_use: bool = True,
) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "title": title,
        "owner_id": owner_id,
        "version": "source-sample-1",
        "description": description,
        "data": {"uri": source_url, "format": "records", "record_count": len(records), "media_type": "application/json"},
        "rights": {"purposes": purposes, "commercial_use": commercial_use, "redistribution": license_name == "ODbL-1.0", "exclusivity": "non_exclusive", "license": license_name, "jurisdictions": ["US"]},
        "tags": tags,
        "metadata": {
            "quality": quality,
            "freshness": freshness,
            "asking_price": asking_price,
            "currency": "USD",
            "provenance": {"dataset_id": dataset_id, "publisher": publisher, "source_url": source_url, "sample_kind": sample_kind, "retrieved_at": "2026-10-27", "license": license_name},
            "pricing_status": "scenario_assumption",
        },
        "records": records,
    }


def _participant(participant_id: str, name: str, role: str, budget: float, product_ids: list[str], scenario_id: str, mechanism: str, description: str) -> dict[str, Any]:
    seller = role == "seller"
    return {
        "participant_id": participant_id,
        "name": name,
        "role": role,
        "budget": budget,
        "currency": "USD",
        "reputation": 0.92,
        "description": description,
        "product_ids": product_ids,
        "scenario_ids": [scenario_id],
        "delegation_mode": "platform_managed",
        "strategy": "cost_plus_reserve" if seller else "budget_pacing",
        "strategy_parameters": {"reserve_target": budget} if seller else {"max_budget": budget},
        "agent_config": {"enabled": True, "rationality": 0.95, "style": "balanced", "model": "reserve_optimizer" if seller else "budget_pacing", "preferred_mechanisms": [mechanism], "bundle_mode": "single" if seller else "and", "preferences": {"quality": 0.4, "freshness": 0.25, "price": 0.25, "rights": 0.1}},
    }


def _real_scenarios() -> tuple[dict[str, Any], ...]:
    mobility_id = "real-nyc-mobility"
    mobility_products = [
        _product("nyc-tlc-yellow-2024-sample", "NYC Yellow Taxi 2024 行程样本", "tlc-feed-provider", _NYC_TRIPS, source_url=NYC_TLC_URL, dataset_id="rwwi-khbc", publisher="NYC Taxi and Limousine Commission", license_name="NYC Open Data Terms", sample_kind="official_records", quality=0.92, freshness=0.55, asking_price=70000, description="TLC 官方 2024 Yellow Taxi 单笔行程记录的可核验小样本。", purposes=["analytics", "forecasting"], tags=["mobility", "trips", "tabular", "official"]),
        _product("nyc-tlc-zone-reference", "TLC Taxi Zone 主数据", "geo-reference-provider", _NYC_ZONES, source_url=NYC_ZONE_URL, dataset_id="taxi-zone-lookup", publisher="NYC Taxi and Limousine Commission", license_name="NYC Open Data Terms", sample_kind="official_records", quality=0.98, freshness=0.8, asking_price=35000, description="TLC 官方区域 ID、行政区、区域名称和服务分区对照。", purposes=["analytics", "forecasting"], tags=["mobility", "geospatial", "reference", "official"]),
        _product("nyc-trip-demand-features", "分区需求与行程有效性特征", "mobility-curation-vendor", _trip_features(), source_url=NYC_TLC_URL, dataset_id="rwwi-khbc-derived-trip-features", publisher="Derived from NYC TLC official records", license_name="NYC Open Data Terms", sample_kind="derived_from_official_records", quality=0.95, freshness=0.56, asking_price=55000, description="由官方行程计算的时长、速度、单位里程价格与分区需求特征，代表市场中的清洗/特征服务。", purposes=["analytics", "forecasting"], tags=["mobility", "features", "curated", "derived"]),
    ]
    mobility_participants = [
        _participant("urban-fleet-planning", "城市运力规划团队", "buyer", 220000, [], mobility_id, "bundle_matching", "按分区小时需求预测增益采购完整数据包。"),
        _participant("tlc-feed-provider", "行程数据交付方", "seller", 70000, ["nyc-tlc-yellow-2024-sample"], mobility_id, "bundle_matching", "交付原始行程数据与更新 SLA。"),
        _participant("geo-reference-provider", "区域主数据服务方", "seller", 35000, ["nyc-tlc-zone-reference"], mobility_id, "bundle_matching", "维护区域映射和版本兼容。"),
        _participant("mobility-curation-vendor", "出行特征加工方", "seller", 55000, ["nyc-trip-demand-features"], mobility_id, "bundle_matching", "提供质量规则、异常处理和小时特征。"),
    ]

    energy_id = "real-pjm-energy"
    energy_products = [
        _product("eia-pjm-hourly-demand", "EIA PJM 小时实际负荷", "eia-feed-integrator", _EIA_DEMAND, source_url=EIA_URL, dataset_id="electricity/rto/region-data:PJM:D", publisher="U.S. Energy Information Administration", license_name="EIA Open Data Terms", sample_kind="official_records", quality=0.99, freshness=0.88, asking_price=90000, description="EIA API 发布的 PJM 小时需求实际值样本。", purposes=["analytics", "forecasting", "energy_trading"], tags=["energy", "load", "time-series", "official"]),
        _product("pjm-load-ramp-features", "PJM 负荷爬坡与峰值特征", "grid-feature-vendor", _energy_ramps(), source_url=EIA_URL, dataset_id="electricity/rto/region-data:PJM:D:ramps", publisher="Derived from U.S. EIA official records", license_name="EIA Open Data Terms", sample_kind="derived_from_official_records", quality=0.97, freshness=0.88, asking_price=65000, description="从 EIA 实际负荷生成的小时变化、变化率和峰值标识。", purposes=["analytics", "forecasting", "energy_trading"], tags=["energy", "ramp", "features", "derived"]),
        _product("pjm-load-window-service", "PJM 滚动负荷窗口服务", "energy-stream-vendor", _energy_windows(), source_url=EIA_URL, dataset_id="electricity/rto/region-data:PJM:D:rolling", publisher="Derived from U.S. EIA official records", license_name="EIA Open Data Terms", sample_kind="derived_from_official_records", quality=0.94, freshness=0.95, asking_price=52000, description="基于官方负荷构造的三小时滚动窗口，代表带更新和交付 SLA 的订阅产品。", purposes=["analytics", "forecasting", "energy_trading"], tags=["energy", "stream", "subscription", "derived"]),
    ]
    energy_participants = [
        _participant("day-ahead-load-desk", "日前负荷决策团队", "buyer", 190000, [], energy_id, "quality_aware_procurement", "以负荷预测误差和峰值捕获改善为采购效用。"),
        _participant("eia-feed-integrator", "公共数据接入服务方", "seller", 90000, ["eia-pjm-hourly-demand"], energy_id, "quality_aware_procurement", "提供 EIA 接入、模式稳定性和审计元数据。"),
        _participant("grid-feature-vendor", "电网特征服务方", "seller", 65000, ["pjm-load-ramp-features"], energy_id, "quality_aware_procurement", "提供爬坡、峰值和异常特征。"),
        _participant("energy-stream-vendor", "连续更新服务方", "seller", 52000, ["pjm-load-window-service"], energy_id, "quality_aware_procurement", "按周期交付滚动窗口和更新 SLA。"),
    ]

    clinical_id = "real-mimic-rwe"
    clinical_products = [
        _product("mimic-admissions-demo", "MIMIC-IV Demo 住院事件", "ehr-license-provider", _MIMIC_ADMISSIONS, source_url=f"{MIMIC_URL}hosp/admissions.csv.gz", dataset_id="mimic-iv-demo-2.2/admissions", publisher="PhysioNet / MIT Laboratory for Computational Physiology", license_name="ODbL-1.0", sample_kind="official_records", quality=0.96, freshness=0.45, asking_price=110000, description="MIMIC-IV Demo 2.2 的去标识化住院记录小样本。", purposes=["clinical_research", "model_evaluation"], tags=["clinical", "admissions", "rwe", "official"], commercial_use=True),
        _product("mimic-diagnoses-demo", "MIMIC-IV Demo ICD 诊断", "coding-license-provider", _MIMIC_DIAGNOSES, source_url=f"{MIMIC_URL}hosp/diagnoses_icd.csv.gz", dataset_id="mimic-iv-demo-2.2/diagnoses_icd", publisher="PhysioNet / MIT Laboratory for Computational Physiology", license_name="ODbL-1.0", sample_kind="official_records", quality=0.93, freshness=0.45, asking_price=85000, description="MIMIC-IV Demo 2.2 的住院级 ICD 编码记录。", purposes=["clinical_research", "model_evaluation"], tags=["clinical", "diagnosis", "icd", "official"], commercial_use=True),
        _product("mimic-labs-demo", "MIMIC-IV Demo 检验事件", "lab-license-provider", _MIMIC_LABS, source_url=f"{MIMIC_URL}hosp/labevents.csv.gz", dataset_id="mimic-iv-demo-2.2/labevents", publisher="PhysioNet / MIT Laboratory for Computational Physiology", license_name="ODbL-1.0", sample_kind="official_records", quality=0.9, freshness=0.45, asking_price=125000, description="MIMIC-IV Demo 2.2 的检验值、单位、参考范围与异常标记样本。", purposes=["clinical_research", "model_evaluation"], tags=["clinical", "laboratory", "longitudinal", "official"], commercial_use=True),
    ]
    clinical_participants = [
        _participant("rwe-safety-study", "药物安全 RWE 研究组", "buyer", 280000, [], clinical_id, "multi_attribute_matching", "按研究问题、链接覆盖和许可适配选择数据。"),
        _participant("ehr-license-provider", "EHR 许可与交付方", "seller", 110000, ["mimic-admissions-demo"], clinical_id, "multi_attribute_matching", "交付住院事件和数据使用审计。"),
        _participant("coding-license-provider", "临床编码服务方", "seller", 85000, ["mimic-diagnoses-demo"], clinical_id, "multi_attribute_matching", "提供诊断编码和版本一致性。"),
        _participant("lab-license-provider", "检验数据服务方", "seller", 125000, ["mimic-labs-demo"], clinical_id, "multi_attribute_matching", "提供检验单位、参考范围和异常标记。"),
    ]

    finance_id = "real-sec-fred-investment"
    finance_products = [
        _product("sec-point-in-time-fundamentals", "SEC 点时财务事实", "filing-normalization-vendor", _SEC_FUNDAMENTALS, source_url=SEC_COMPANYFACTS_URL, dataset_id="sec-companyfacts-aapl-msft-2024", publisher="U.S. Securities and Exchange Commission", license_name="SEC.gov Access Terms", sample_kind="official_records", quality=0.97, freshness=0.82, asking_price=72000, description="从 SEC Company Facts XBRL API 保留申报日和 accession 的 AAPL/MSFT 财务事实样本。", purposes=["analytics", "investment_research", "risk_monitoring"], tags=["finance", "fundamentals", "xbrl", "point-in-time", "official"]),
        _product("fred-dff-rate-regime", "FRED 有效联邦基金利率", "macro-feed-vendor", _FRED_DFF, source_url=FRED_DFF_URL, dataset_id="FRED-DFF-2024-07-01-2024-07-12", publisher="Federal Reserve Bank of St. Louis / Board of Governors", license_name="FRED Terms of Use", sample_kind="official_records", quality=0.99, freshness=0.8, asking_price=38000, description="FRED DFF 日度观测样本，用于刻画研究时点的利率环境。", purposes=["analytics", "investment_research", "risk_monitoring"], tags=["finance", "macro", "interest-rate", "time-series", "official"]),
        _product("issuer-rate-point-in-time-signals", "发行人—利率点时信号面板", "point-in-time-factor-vendor", _finance_point_in_time_signals(), source_url=SEC_API_URL, dataset_id="derived-sec-fred-pit-panel-2024-07", publisher="Derived from SEC Company Facts and FRED DFF", license_name="Source-specific SEC/FRED Terms", sample_kind="derived_from_official_records", quality=0.95, freshness=0.9, asking_price=94000, description="严格按 as-of date 使用已公开申报，连接利率环境并计算申报滞后、资产和收入变化。", purposes=["analytics", "investment_research", "risk_monitoring"], tags=["finance", "factors", "point-in-time", "derived", "no-lookahead"]),
    ]
    finance_participants = [
        _participant("multi-asset-research-desk", "多资产投研与风险团队", "buyer", 260000, [], finance_id, "bundle_matching", "按点时完整性、研究增益与持续交付能力采购数据组合。"),
        _participant("filing-normalization-vendor", "财报标准化服务方", "seller", 72000, ["sec-point-in-time-fundamentals"], finance_id, "bundle_matching", "提供 XBRL 映射、申报版本和修订轨迹。"),
        _participant("macro-feed-vendor", "宏观数据接入服务方", "seller", 38000, ["fred-dff-rate-regime"], finance_id, "bundle_matching", "提供利率序列接入、日历和更新监控。"),
        _participant("point-in-time-factor-vendor", "点时因子加工方", "seller", 94000, ["issuer-rate-point-in-time-signals"], finance_id, "bundle_matching", "提供无前视连接、申报滞后和发行人变化信号。"),
    ]

    common_operations = ["governance", "profile", "evaluation", "valuation", "pricing", "market"]
    return (
        {
            "scenario_id": mobility_id, "name": "真实应用 · NYC 出行需求数据采购", "domain": "城市交通与运力", "icon": "route", "evidence_level": "source_grounded_sample",
            "summary": "用 TLC 官方行程和区域记录完成质量核验、预测增益估值、订阅报价与组合采购。", "decision": "采购能降低分区小时需求预测误差、且具备稳定交付与区域映射的数据组合。", "buyer": "城市运力规划团队", "currency": "USD", "data_notice": "包含 NYC TLC 官方公开记录小样本；报价、预算和策略为可编辑案例假设。",
            "sources": [{"publisher": "NYC Taxi and Limousine Commission", "dataset": "2024 Yellow Taxi Trip Data", "url": "https://data.cityofnewyork.us/d/rwwi-khbc", "license": "NYC Open Data Terms"}, {"publisher": "NYC Taxi and Limousine Commission", "dataset": "Taxi Zone Lookup", "url": NYC_ZONE_URL, "license": "NYC Open Data Terms"}],
            "assumptions": {"prices_are_observed": False, "note": "预算、保留价和订阅费用于复现企业采购决策，不是 NYC 或任何厂商公开报价。"},
            "business_context": {"demand": "运力团队需要在日/小时级决定车辆部署，外部数据必须带来相对仅用历史订单基线的预测误差下降。", "decision_metric": "分区小时需求预测的 WMAPE 改善与高峰召回率", "cadence": "月度订阅、日级更新、小时级使用", "process_steps": ["用途与许可准入", "行程及区域模式校验", "异常行程与区域覆盖评估", "相对基线的预测增益估值", "订阅报价与组合选择", "上线后按实际误差改善复核"], "metric_dimensions": [{"name": "required-field completeness", "meaning": "上下车时间、区域与里程的非空比例"}, {"name": "valid trip ratio", "meaning": "正时长、合理距离和速度的行程占比"}, {"name": "zone coverage", "meaning": "需求区域被区域主数据覆盖的比例"}, {"name": "forecast WMAPE improvement", "meaning": "加入数据后相对历史基线的加权误差下降"}, {"name": "delivery freshness", "meaning": "数据延迟与订阅 SLA 的符合程度"}]},
            "default_operations": common_operations, "participants": mobility_participants, "products": mobility_products,
            "operation_parameters": {"governance": {"operation": "forecasting", "strict_rights": True}, "profile": {"include_examples": True}, "evaluation": {"modality": "tabular", "metrics": ["basic.completeness", "basic.duplicate_rate", "basic.field_validity", "tabular.numeric_statistics", "tabular.outlier_rate"], "required_fields": ["tpep_pickup_datetime", "tpep_dropoff_datetime"]}, "valuation": {"method": "valuation.counterfactual", "base_value": 180000, "currency": "USD", "evaluation_vector": {"wmape_improvement": 0.16, "peak_recall_gain": 0.09}, "baseline_vector": {"wmape_improvement": 0, "peak_recall_gain": 0}, "metric_weights": {"wmape_improvement": 1, "peak_recall_gain": 0.6}}, "pricing": {"model": "pricing.subscription", "currency": "USD", "period_fee": 52000, "included_usage": 1000, "usage": 1200, "overage_unit_price": 18, "commitment_discount": 0.08}, "market": {"mechanism": "bundle_matching", "currency": "USD", "budget": 220000, "bids": [{"buyer_id": "urban-fleet-planning", "product_ids": [item["product_id"] for item in mobility_products], "amount": 190000, "budget": 220000, "currency": "USD", "constraints": {"bundle_mode": "and"}}], "asks": [{"seller_id": item["owner_id"], "product_ids": [item["product_id"]], "reserve": item["metadata"]["asking_price"], "currency": "USD", "metadata": {"quality": item["metadata"]["quality"]}} for item in mobility_products]}},
        },
        {
            "scenario_id": energy_id, "name": "真实应用 · PJM 负荷数据订阅", "domain": "电力调度与交易", "icon": "bolt", "evidence_level": "source_grounded_sample",
            "summary": "用 EIA PJM 小时负荷实测记录评估连续性、峰值效用、更新流价值和质量感知采购。", "decision": "为日前负荷决策选择具有连续更新、低延迟和峰值识别能力的数据服务。", "buyer": "日前负荷决策团队", "currency": "USD", "data_notice": "包含 EIA API 官方实测记录及可复核衍生特征；商业条款为案例假设。",
            "sources": [{"publisher": "U.S. Energy Information Administration", "dataset": "Hourly Electric Grid Monitor / RTO Region Data", "url": "https://www.eia.gov/opendata/v1/", "license": "EIA Open Data Terms"}, {"publisher": "PJM Interconnection", "dataset": "Data Miner terms and market feeds", "url": "https://www.pjm.com/markets-and-operations/etools/data-miner-2", "license": "PJM Data Miner Terms"}],
            "assumptions": {"prices_are_observed": False, "note": "服务费、预算和卖方保留价表示接入、清洗、更新与 SLA 成本，并非 EIA/PJM 的报价。"},
            "business_context": {"demand": "零售负荷与调度团队在日前采购和头寸管理前，需要校正峰值、爬坡与更新延迟风险。", "decision_metric": "负荷预测 MAPE 改善、峰值捕获率和不平衡成本降低", "cadence": "小时数据、日内更新、年度或月度订阅", "process_steps": ["核验 API 与再分发权利", "检查时间戳连续性和单位", "评估峰值/爬坡覆盖", "折现未来更新流价值", "比较订阅与按量报价", "质量成本比采购并监测 SLA"], "metric_dimensions": [{"name": "timestamp continuity", "meaning": "小时序列无缺口比例"}, {"name": "unit consistency", "meaning": "负荷单位与数值范围一致性"}, {"name": "forecast MAPE improvement", "meaning": "相对内部基线的负荷预测误差下降"}, {"name": "peak capture", "meaning": "关键峰值和爬坡事件的召回"}, {"name": "delivery reliability", "meaning": "按约定频率准时交付的概率"}]},
            "default_operations": common_operations, "participants": energy_participants, "products": energy_products,
            "operation_parameters": {"governance": {"operation": "energy_trading", "strict_rights": True}, "profile": {"include_examples": True}, "evaluation": {"modality": "tabular", "metrics": ["basic.completeness", "basic.duplicate_rate", "basic.field_validity", "tabular.numeric_statistics", "tabular.outlier_rate"], "required_fields": ["period", "value"]}, "valuation": {"method": "valuation.update_stream", "base_value": 160000, "currency": "USD", "updates": [{"period": 0, "marginal_value": 65000, "delivery_probability": 0.99, "quality": 0.97}, {"period": 1, "marginal_value": 52000, "delivery_probability": 0.96, "quality": 0.95}, {"period": 2, "marginal_value": 42000, "delivery_probability": 0.94, "quality": 0.94}], "discount_rate": 0.04}, "pricing": {"model": "pricing.expected_revenue", "currency": "USD", "candidate_prices": [45000, 65000, 85000, 105000], "buyer_budget": 190000, "quality": 0.96, "freshness": 0.9}, "market": {"mechanism": "quality_aware_procurement", "currency": "USD", "budget": 190000, "buyer_id": "day-ahead-load-desk", "bids": [{"buyer_id": "day-ahead-load-desk", "product_ids": [item["product_id"] for item in energy_products], "amount": 190000, "budget": 190000, "currency": "USD", "constraints": {"bundle_mode": "xor"}}], "asks": [{"seller_id": item["owner_id"], "product_ids": [item["product_id"]], "reserve": item["metadata"]["asking_price"], "currency": "USD", "metadata": {"quality": item["metadata"]["quality"]}} for item in energy_products]}},
        },
        {
            "scenario_id": clinical_id, "name": "真实应用 · 临床 RWE 数据许可", "domain": "临床研究与药物安全", "icon": "cross", "evidence_level": "source_grounded_sample",
            "summary": "用 MIMIC-IV Demo 的真实去标识记录演示研究适用性、链接覆盖、风险估值和多属性许可选择。", "decision": "选择能够回答药物安全研究问题、关键变量完整且许可可审计的住院/诊断/检验组合。", "buyer": "药物安全 RWE 研究组", "currency": "USD", "data_notice": "包含 PhysioNet MIMIC-IV Demo 2.2 官方记录；患者标识已由发布方去标识，场景价格不是 PhysioNet 报价。",
            "sources": [{"publisher": "PhysioNet / MIT Laboratory for Computational Physiology", "dataset": "MIMIC-IV Clinical Database Demo v2.2", "url": MIMIC_URL, "license": "ODbL-1.0"}, {"publisher": "U.S. Food and Drug Administration", "dataset": "Real-World Evidence guidance", "url": "https://www.fda.gov/science-research/science-and-research-special-topics/real-world-evidence", "license": "U.S. Government publication"}],
            "assumptions": {"prices_are_observed": False, "note": "价值基数、许可报价和研究预算只用于演示 RWE 数据采购决策；PhysioNet Demo 本身依 ODbL 开放。"},
            "business_context": {"demand": "研究组必须证明数据对具体安全性问题 fit-for-purpose，并在锁库前确认链接率、关键元素、时序与许可。", "decision_metric": "可纳入队列规模、关键元素完整性、跨表链接率及研究周期缩短", "cadence": "研究项目制许可与版本化快照", "process_steps": ["研究用途和许可准入", "关键数据元素画像", "跨表链接与时间一致性评估", "按不确定性和权利风险估值", "权利差异报价", "多属性选择并保留审计证据"], "metric_dimensions": [{"name": "cohort coverage", "meaning": "满足纳排标准的住院事件覆盖"}, {"name": "key-element completeness", "meaning": "研究关键变量的非空比例"}, {"name": "linkage rate", "meaning": "admission、diagnosis 与 lab 可连接比例"}, {"name": "temporal consistency", "meaning": "事件时间相对住院窗口的合理性"}, {"name": "unit and flag validity", "meaning": "检验单位、参考范围和异常标记一致性"}, {"name": "rights fit", "meaning": "研究、衍生和再分发权利与方案一致"}]},
            "default_operations": common_operations, "participants": clinical_participants, "products": clinical_products,
            "operation_parameters": {"governance": {"operation": "clinical_research", "strict_rights": True}, "profile": {"include_examples": True}, "evaluation": {"modality": "tabular", "metrics": ["basic.completeness", "basic.duplicate_rate", "basic.field_validity", "tabular.schema_consistency", "tabular.numeric_statistics"], "required_fields": ["subject_id", "hadm_id"]}, "valuation": {"method": "valuation.risk_adjusted", "base_value": 260000, "currency": "USD", "evaluation_vector": {"quality": 0.91}, "uncertainty": {"std_error": 0.08}, "risk_aversion": 0.65}, "pricing": {"model": "pricing.rights_differentiated", "currency": "USD", "base_price": 90000, "commercial_premium": 0.2, "redistribution_premium": 0.3, "exclusivity_premium": 0.5, "per_jurisdiction_premium": 0.02, "per_year_premium": 0.05}, "market": {"mechanism": "multi_attribute_matching", "currency": "USD", "match_weights": {"price": 0.2, "quality": 0.3, "freshness": 0.1, "reputation": 0.1, "rights": 0.3}, "bids": [{"buyer_id": "rwe-safety-study", "product_ids": [item["product_id"] for item in clinical_products], "amount": 280000, "budget": 280000, "currency": "USD", "constraints": {"bundle_mode": "and"}}], "asks": [{"seller_id": item["owner_id"], "product_ids": [item["product_id"]], "reserve": item["metadata"]["asking_price"], "currency": "USD", "metadata": {"quality": item["metadata"]["quality"], "reputation": 0.94}} for item in clinical_products]}},
        },
        {
            "scenario_id": finance_id, "name": "真实应用 · 金融投研数据采购", "domain": "资产管理与风险研究", "icon": "chart", "evidence_level": "source_grounded_sample",
            "summary": "用 SEC 点时财务事实与 FRED 利率观测评估数据完整性、前视偏差、投研效用、订阅报价和组合采购。", "decision": "为发行人筛选、组合复核和下行风险监测采购可点时复现、更新稳定且能在影子回测中产生增量效用的数据组合。", "buyer": "多资产投研与风险团队", "currency": "USD", "data_notice": "包含 SEC EDGAR 与 FRED 官方记录及无前视衍生面板；预算、报价和回测增益为可编辑案例假设，不构成投资建议。",
            "sources": [{"publisher": "U.S. Securities and Exchange Commission", "dataset": "EDGAR XBRL Company Facts API", "url": SEC_API_URL, "license": "SEC.gov Access Terms"}, {"publisher": "Federal Reserve Bank of St. Louis / Board of Governors", "dataset": "Effective Federal Funds Rate (DFF)", "url": "https://fred.stlouisfed.org/series/DFF", "license": "FRED Terms of Use"}],
            "assumptions": {"prices_are_observed": False, "note": "数据值、申报日和 accession 来自官方来源；订阅费、预算、保留价、影子回测增益和 SLA 是用于复现采购决策的假设。"},
            "business_context": {"demand": "投研团队需要把公开财报和利率数据转化为可按历史时点复现的研究输入，并避免使用当时尚未发布的申报或后来修订值。采购评审先做影子回测，再决定是否订阅标准化与持续更新服务。", "decision_metric": "无前视的横截面排序增益、下行预警召回、点时覆盖和交付延迟", "cadence": "财报事件触发更新、宏观日更、月度订阅与季度续约", "process_steps": ["核验来源访问条件与研究用途", "保留 accession、申报日和版本谱系", "检查发行人—期间覆盖及字段一致性", "构造无前视影子回测数据集", "估计排序与风险监测的增量效用", "比较订阅报价并完成组合采购", "上线后监测延迟、修订和实际研究增益"], "metric_dimensions": [{"name": "point-in-time integrity", "meaning": "每个历史时点只使用当时已经公开的申报与宏观观测"}, {"name": "filing latency", "meaning": "报告期结束至申报发布、以及发布至平台可用的时间"}, {"name": "issuer-period coverage", "meaning": "目标发行人和研究期间被标准化事实覆盖的比例"}, {"name": "restatement traceability", "meaning": "原始 accession、后续重报和修订值可以区分并追溯"}, {"name": "shadow ranking gain", "meaning": "加入数据后相对内部基线的无前视排序质量改善"}, {"name": "downside alert recall", "meaning": "对预先定义的下行风险事件的召回改善"}, {"name": "delivery reliability", "meaning": "财报和宏观更新在约定 SLA 内可用的比例"}]},
            "default_operations": common_operations, "participants": finance_participants, "products": finance_products,
            "operation_parameters": {"governance": {"operation": "investment_research", "strict_rights": True}, "profile": {"include_examples": True}, "evaluation": {"modality": "tabular", "metrics": ["basic.completeness", "basic.duplicate_rate", "basic.field_validity", "tabular.schema_consistency", "tabular.numeric_statistics", "tabular.outlier_rate"], "required_fields": ["source_record_id"]}, "valuation": {"method": "valuation.counterfactual", "base_value": 260000, "currency": "USD", "evaluation_vector": {"rank_ic_improvement": 0.032, "downside_alert_recall_gain": 0.08, "point_in_time_coverage": 0.97}, "baseline_vector": {"rank_ic_improvement": 0, "downside_alert_recall_gain": 0, "point_in_time_coverage": 0.78}, "metric_weights": {"rank_ic_improvement": 1.0, "downside_alert_recall_gain": 0.7, "point_in_time_coverage": 0.5}}, "pricing": {"model": "pricing.subscription", "currency": "USD", "period_fee": 68000, "included_usage": 1200, "usage": 1400, "overage_unit_price": 12, "commitment_discount": 0.05}, "market": {"mechanism": "bundle_matching", "currency": "USD", "budget": 260000, "bids": [{"buyer_id": "multi-asset-research-desk", "product_ids": [item["product_id"] for item in finance_products], "amount": 240000, "budget": 260000, "currency": "USD", "constraints": {"bundle_mode": "and"}}], "asks": [{"seller_id": item["owner_id"], "product_ids": [item["product_id"]], "reserve": item["metadata"]["asking_price"], "currency": "USD", "metadata": {"quality": item["metadata"]["quality"], "freshness": item["metadata"]["freshness"]}} for item in finance_products]}},
        },
    )


_SCENARIOS = _real_scenarios()


def real_world_scenarios() -> list[dict[str, Any]]:
    """Return isolated copies of the source-grounded applications."""
    return deepcopy(list(_SCENARIOS))


__all__ = ["real_world_scenarios"]
