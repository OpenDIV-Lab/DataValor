#!/usr/bin/env python3
"""Stream the frozen ChileCompra bulk snapshot into anonymous cost blocks."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from datamechbench.heldout_sources import (
    calibrate_procurement_costs,
    extract_chilecompra_award_amounts,
)
from datamechbench.real_experiment import authorize_kdd_heldout_protocol

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "benchmark"
CONFIG = BENCHMARK / "configs" / "kdd_heldout_confirmatory.yaml"
PROTOCOL = BENCHMARK / "evidence" / "kdd_heldout_protocol_v6.json"
SNAPSHOT = BENCHMARK / "data" / "heldout" / "raw" / "chilecompra" / "chilecompra-2024.jsonl.gz"
DATA_ROOT = BENCHMARK / "data" / "heldout"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Process a frozen ChileCompra snapshot with native Python."
    )
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL)
    parser.add_argument("--snapshot", type=Path, default=SNAPSHOT)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    return parser.parse_args(argv)


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _candidate_records(outer: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    releases = outer.get("releases")
    if isinstance(releases, list):
        return tuple(record for record in releases if isinstance(record, Mapping))
    return (outer,)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_relative(path: Path) -> str:
    """Store provenance paths relative to the portable repository root."""

    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"provenance path escapes repository root: {path}") from exc


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    protocol = authorize_kdd_heldout_protocol(
        args.protocol, expected_sources=config["sources"]
    )
    expected_size = config["sources"]["procurement"][0]["expected_content_length"]
    actual_size = args.snapshot.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(f"snapshot size {actual_size} != frozen {expected_size}")
    source_hash = _sha256_file(args.snapshot)
    cohorts = {
        source["cohort_date"]: {"source": source, "amounts": [], "matched_records": 0}
        for source in config["sources"]["procurement"]
    }
    source_lines = invalid_lines = release_records = 0
    with gzip.open(args.snapshot, "rt", encoding="utf-8") as handle:
        for line in handle:
            source_lines += 1
            try:
                outer = json.loads(line)
            except json.JSONDecodeError:
                invalid_lines += 1
                continue
            if not isinstance(outer, Mapping):
                continue
            for record in _candidate_records(outer):
                release_records += 1
                release_date = str(record.get("date", ""))[:10]
                if release_date not in cohorts:
                    continue
                cohort = cohorts[release_date]
                cohort["matched_records"] += 1
                cohort["amounts"].extend(
                    extract_chilecompra_award_amounts(
                        [record], cohort_date=release_date
                    )
                )
    receipt_path = (
        args.data_root
        / "raw"
        / "chilecompra"
        / "chilecompra-2024-source-receipt.json"
    )
    receipt = {
        "schema_version": "1.0",
        "artifact_kind": "immutable_bulk_source_receipt",
        "protocol_hash": protocol.protocol_hash,
        "source_url": config["sources"]["procurement"][0]["snapshot_url"],
        "source_path": _repository_relative(args.snapshot),
        "source_sha256": source_hash,
        "content_length": actual_size,
        "expected_etag": config["sources"]["procurement"][0]["expected_etag"],
        "jsonl_lines": source_lines,
        "invalid_json_lines": invalid_lines,
        "release_records": release_records,
    }
    _atomic_json(receipt_path, receipt)
    for date, cohort in cohorts.items():
        source = cohort["source"]
        amounts = tuple(float(value) for value in cohort["amounts"])
        costs = calibrate_procurement_costs(amounts, seller_count=8)
        output = {
            "schema_version": "1.0",
            "artifact_kind": "anonymous_procurement_cost_calibration",
            "source_id": source["source_id"],
            "block_id": source["block_id"],
            "cohort_date": date,
            "protocol_hash": protocol.protocol_hash,
            "source_receipt": _repository_relative(receipt_path),
            "source_receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "anonymous_amounts": sorted(amounts),
            "calibrated_costs": {owner: str(value) for owner, value in costs.items()},
            "coverage": {
                "matched_release_records": cohort["matched_records"],
                "positive_clp_award_amounts": len(amounts),
            },
            "identity_policy": "process, organization, tenderer, and supplier fields discarded",
            "type_interpretation": "observed award values are cost-distribution proxies, not latent data-seller costs",
        }
        target = args.data_root / "processed" / f"{source['source_id']}-costs.json"
        _atomic_json(target, output)
        print(f"{source['source_id']}: {len(amounts)} amounts -> {target}")


if __name__ == "__main__":
    main()
