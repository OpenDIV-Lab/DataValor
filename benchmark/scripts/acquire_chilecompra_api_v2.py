#!/usr/bin/env python3
"""Reproduce superseded protocol-v2 API acquisition (not confirmation evidence)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml
from datamechbench.heldout_sources import (
    calibrate_procurement_costs,
    extract_chilecompra_order_totals,
    select_chilecompra_order_codes,
)
from datamechbench.real_experiment import authorize_kdd_heldout_protocol


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(_canonical_bytes(value))
    os.replace(temporary, path)


def _request_json(url: str, ticket: str, *, attempts: int = 8) -> tuple[Any, str]:
    separator = "&" if "?" in url else "?"
    request_url = f"{url}{separator}{urllib.parse.urlencode({'ticket': ticket})}"
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "DataMechBench-KDD-heldout/1.0"},
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = response.read()
            return json.loads(payload), hashlib.sha256(payload).hexdigest()
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt + 1 == attempts:
                raise
            retry_after = error.headers.get("Retry-After", "")
            delay = float(retry_after) if retry_after.isdigit() else min(30, 2 ** attempt)
            time.sleep(delay)
    raise RuntimeError("unreachable acquisition retry state")


def _load_receipt(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def acquire_cohort(
    source: dict[str, Any],
    *,
    ticket: str,
    protocol_hash: str,
    raw_directory: Path,
    processed_directory: Path,
    repository_root: Path,
    sample_size: int,
) -> tuple[Path, Path]:
    source_id = source["source_id"]
    receipt_path = raw_directory / f"{source_id}-receipt.json"
    processed_path = processed_directory / f"{source_id}-costs.json"
    receipt = _load_receipt(receipt_path)
    if receipt is None:
        listing, listing_hash = _request_json(source["list_endpoint"], ticket)
        selected = select_chilecompra_order_codes(listing, sample_size=sample_size)
        receipt = {
            "schema_version": "1.0",
            "artifact_kind": "official_api_acquisition_receipt",
            "source_id": source_id,
            "cohort_date": source["cohort_date"],
            "protocol_hash": protocol_hash,
            "list_endpoint": source["list_endpoint"],
            "list_response_sha256": listing_hash,
            "reported_order_count": int(listing.get("Cantidad", len(listing["Listado"]))),
            "sampling_rule": f"first_{sample_size}_unique_order_codes_in_lexicographic_order",
            "selected_codes": list(selected),
            "details": [],
        }
        _atomic_json(receipt_path, receipt)
    if receipt.get("protocol_hash") != protocol_hash:
        raise RuntimeError(f"{receipt_path} was acquired under another protocol")

    completed = {detail["code"] for detail in receipt["details"]}
    template = source["detail_endpoint_template"]
    for code in receipt["selected_codes"]:
        if code in completed:
            continue
        payload, response_hash = _request_json(
            template.format(code=urllib.parse.quote(code, safe="")), ticket
        )
        orders = payload.get("Listado") if isinstance(payload, dict) else None
        order = orders[0] if isinstance(orders, list) and orders else {}
        amounts = extract_chilecompra_order_totals([payload])
        receipt["details"].append({
            "code": code,
            "response_sha256": response_hash,
            "response_count": int(payload.get("Cantidad", len(orders or []))),
            "state": str(order.get("Estado", "")),
            "currency": str(order.get("TipoMoneda", "")),
            "accepted_clp_total": amounts[0] if amounts else None,
        })
        _atomic_json(receipt_path, receipt)
        time.sleep(0.2)

    amounts = tuple(
        float(detail["accepted_clp_total"])
        for detail in receipt["details"]
        if detail.get("accepted_clp_total") is not None
    )
    costs = calibrate_procurement_costs(amounts, seller_count=8)
    processed = {
        "schema_version": "1.0",
        "artifact_kind": "anonymous_procurement_cost_calibration",
        "source_id": source_id,
        "block_id": source["block_id"],
        "protocol_hash": protocol_hash,
        "source_receipt": receipt_path.resolve().relative_to(
            repository_root.resolve()
        ).as_posix(),
        "source_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "anonymous_amounts": sorted(amounts),
        "calibrated_costs": {owner: str(value) for owner, value in costs.items()},
        "coverage": {
            "listed_orders": receipt["reported_order_count"],
            "prespecified_sample": len(receipt["selected_codes"]),
            "detail_responses": len(receipt["details"]),
            "accepted_clp_totals": len(amounts),
            "retained_fraction": len(amounts) / len(receipt["selected_codes"]),
        },
        "identity_policy": "organization and supplier fields discarded",
        "type_interpretation": "observed accepted order totals are cost-distribution proxies, not latent data-seller costs",
    }
    _atomic_json(processed_path, processed)
    return receipt_path, processed_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("benchmark/configs/kdd_heldout_confirmatory_v2.yaml"),
    )
    parser.add_argument("--sample-size", type=int, default=64)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    benchmark = args.config.parents[1]
    repository_root = benchmark.resolve().parent
    protocol_path = benchmark / "evidence" / "kdd_heldout_protocol_v2.json"
    protocol = authorize_kdd_heldout_protocol(
        protocol_path, expected_sources=config["sources"]
    )
    ticket = os.environ.get("CHILECOMPRA_API_TICKET", "")
    if not ticket:
        raise RuntimeError("CHILECOMPRA_API_TICKET is required")
    for source in config["sources"]["procurement"]:
        receipt, processed = acquire_cohort(
            source,
            ticket=ticket,
            protocol_hash=protocol.protocol_hash,
            raw_directory=benchmark / "data" / "heldout" / "raw" / "chilecompra",
            processed_directory=benchmark / "data" / "heldout" / "processed",
            repository_root=repository_root,
            sample_size=args.sample_size,
        )
        print(f"{source['source_id']}: {receipt} -> {processed}")


if __name__ == "__main__":
    main()
