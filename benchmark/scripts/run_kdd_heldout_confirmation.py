#!/usr/bin/env python3
"""Build the frozen held-out case bank, run mechanisms, and emit evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

import yaml
from datamechbench.confirmatory import (
    ContrastResult,
    ContrastSpec,
    analyze_confirmatory_contrasts,
    quantify_representativeness,
)
from datamechbench.heldout_sources import (
    build_owner_dataset_from_arff,
    calibrate_elexon_profile,
)
from datamechbench.real_experiment import authorize_kdd_heldout_protocol
from datamechbench.replication import audit_replication_protocol
from datamechbench.report import (
    load_jsonl_results,
    write_jsonl,
    write_leaderboard_csvs,
    write_markdown_report,
    write_track_csvs,
)
from datamechbench.reference_evaluation import write_reference_outcome_audit
from datamechbench.reproduction import resolve_repository_file
from datamechbench.runner import BenchmarkConfig, build_cases, run_benchmark
from datamechbench.settings.heldout import (
    make_heldout_procurement_cases,
    make_heldout_trading_cases,
    make_heldout_valuation_cases,
)

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "benchmark"
CONFIG_PATH = BENCHMARK / "configs" / "kdd_heldout_confirmatory.yaml"
PROTOCOL_PATH = BENCHMARK / "evidence" / "kdd_heldout_protocol_v6.json"
OUTPUT = BENCHMARK / "outputs" / "kdd_heldout_confirmatory"
MANIFEST_PATH = BENCHMARK / "evidence" / "kdd_heldout_confirmatory_v1.json"
DATA_ROOT = BENCHMARK / "data" / "heldout"

OPENML_FILES = {
    44: ("spambase-44.arff", "class"),
    31: ("credit-g-31.arff", "class"),
    1461: ("bank-marketing-1461.arff", "Class"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a frozen DataMechBench held-out wave with native Python."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--protocol", type=Path, default=PROTOCOL_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--run-name", default="datamechbench-kdd-heldout-v1")
    parser.add_argument(
        "--reuse-results",
        action="store_true",
        help="Build evidence from an already completed frozen run without rerunning mechanisms.",
    )
    return parser.parse_args(argv)


def guard_output_separation(
    config: Mapping[str, Any], output: Path, manifest: Path
) -> None:
    """Prevent a replication wave from mutating the frozen v1 evidence."""

    if str(config.get("replication_wave", "")).strip() and (
        output.resolve() == OUTPUT.resolve()
        or manifest.resolve() == MANIFEST_PATH.resolve()
    ):
        raise ValueError("replication wave must not overwrite v1 outputs or manifest")


def valuation_source_location(
    source: Mapping[str, Any], data_root: Path
) -> tuple[Path, str]:
    """Resolve a source from its frozen config, retaining v1 compatibility."""

    raw_filename = str(source.get("raw_filename", "")).strip()
    target = str(source.get("target_attribute", "")).strip()
    if not raw_filename or not target:
        try:
            raw_filename, target = OPENML_FILES[int(source["openml_id"])]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"OpenML source requires raw_filename and target_attribute: {source}"
            ) from exc
    candidate = Path(raw_filename)
    if candidate.is_absolute() or len(candidate.parts) != 1:
        raise ValueError(f"unsafe OpenML raw filename: {raw_filename}")
    return data_root.resolve() / "raw" / "openml" / candidate, target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"artifact path escapes repository root: {path}") from exc
    return {"path": str(relative), "sha256": _sha256(resolved)}


def result_row_count(path: Path) -> int:
    return sum(
        bool(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _load_valuation_sources(config: Mapping[str, Any], data_root: Path):
    data_root = data_root.resolve()
    datasets = {}
    artifacts = {}
    processed_dir = data_root / "processed"
    for source in config["sources"]["valuation"]:
        raw_path, target = valuation_source_location(source, data_root)
        if _md5(raw_path) != source["expected_md5"]:
            raise RuntimeError(f"OpenML checksum mismatch: {raw_path}")
        dataset = build_owner_dataset_from_arff(
            raw_path,
            dataset_id=source["source_id"],
            target_attribute=target,
            seed=int(config["transformations"]["valuation"]["split_seed"]),
            maximum_rows=int(config["transformations"]["valuation"]["maximum_rows"]),
        )
        datasets[source["source_id"]] = dataset
        processed_path = processed_dir / f"{source['source_id']}-owner-game.json"
        processed = {
            "schema_version": "1.0",
            "artifact_kind": "owner_partitioned_prediction_game",
            "source_id": source["source_id"],
            "source_sha256": _sha256(raw_path),
            "dataset_hash": dataset.dataset_hash,
            "target_attribute": target,
            "source_shape": list(dataset.source_shape),
            "split_sizes": {
                "train": len(dataset.train_indices),
                "validation": len(dataset.validation_indices),
                "test": len(dataset.test_indices),
            },
            "owner_row_counts": {
                owner: len(rows) for owner, rows in dataset.owner_rows.items()
            },
            "identity_policy": "OpenML rows contain no benchmark participant identities; owner IDs are synthetic partitions",
        }
        _atomic_json(processed_path, processed)
        artifacts[source["source_id"]] = (raw_path, processed_path)
    return datasets, artifacts


def _load_procurement_costs(config: Mapping[str, Any], data_root: Path):
    data_root = data_root.resolve()
    costs = {}
    artifacts = {}
    for source in config["sources"]["procurement"]:
        processed_path = data_root / "processed" / f"{source['source_id']}-costs.json"
        payload = json.loads(processed_path.read_text(encoding="utf-8"))
        costs[source["block_id"]] = payload["calibrated_costs"]
        receipt_path = resolve_repository_file(
            payload["source_receipt"],
            ROOT,
            label="ChileCompra source receipt",
        )
        if _sha256(receipt_path) != payload["source_receipt_sha256"]:
            raise RuntimeError(f"ChileCompra receipt mismatch: {processed_path}")
        artifacts[source["source_id"]] = (receipt_path, processed_path, payload)
    return costs, artifacts


def _load_trading_profiles(config: Mapping[str, Any], data_root: Path):
    data_root = data_root.resolve()
    raw_dir = data_root / "raw" / "elexon"
    processed_dir = data_root / "processed"
    source = config["sources"]["trading"][-1]
    profiles = {}
    independent_blocks = {}
    artifacts = {}
    for cohort in config["sources"]["trading"][:-1]:
        date = cohort["date"]
        payload = {"data": []}
        source_files = []
        for period in cohort["settlement_periods"]:
            path = raw_dir / f"bod-{date}-sp{period}.json"
            part = json.loads(path.read_text(encoding="utf-8"))
            payload["data"].extend(part.get("data", []))
            source_files.append({"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)})
        block = str(cohort.get("block_id", f"THO-elexon-{date.replace('-', '')}"))
        receipt_path = raw_dir / f"elexon-{date}-source-receipt.json"
        _atomic_json(receipt_path, {
            "schema_version": "1.0",
            "artifact_kind": "official_api_source_receipt",
            "source_id": source["source_id"],
            "date": date,
            "settlement_periods": cohort["settlement_periods"],
            "endpoint_template": source["endpoint_template"],
            "source_files": source_files,
        })
        processed_profiles = {}
        for market_size in config["transformations"]["trading"]["balanced_market_sizes"]:
            case_id = f"{block}-n{market_size}"
            profile = calibrate_elexon_profile(payload, market_size=int(market_size))
            profiles[case_id] = profile
            independent_blocks[case_id] = block
            processed_profiles[str(market_size)] = {
                "buyer_values": profile.buyer_values,
                "seller_costs": profile.seller_costs,
                "source_row_count": profile.source_row_count,
                "retained_bid_count": profile.retained_bid_count,
                "retained_offer_count": profile.retained_offer_count,
            }
        processed_path = processed_dir / f"elexon-{date}-type-profiles.json"
        _atomic_json(processed_path, {
            "schema_version": "1.0",
            "artifact_kind": "anonymous_double_auction_type_profiles",
            "block_id": block,
            "source_receipt_sha256": _sha256(receipt_path),
            "profiles": processed_profiles,
            "identity_policy": "BM-unit and pair identifiers discarded",
            "type_interpretation": "normalized submissions are empirical type proxies, not revealed private values or costs",
        })
        artifacts[block] = (receipt_path, processed_path, processed_profiles)
    return profiles, independent_blocks, artifacts


def _metric_records(values: Mapping[str, float]) -> list[dict[str, Any]]:
    return [
        {"name": name, "value": value, "reference": "development_distribution"}
        for name, value in sorted(values.items())
    ]


def _realism(track: str) -> dict[str, dict[str, str]]:
    records = {
        "valuation": {
            "data": ("Observed OpenML/UCI feature-label rows.", "Historical datasets may not represent modern deployment populations."),
            "utility": ("Logistic models are trained on frozen train splits and scored on validation/test splits.", "A single model class and owner partition do not exhaust task uncertainty."),
            "participant_type": ("Data rows are deterministically partitioned into eight owner bundles.", "Owner identities and bundles are benchmark constructs, not observed data sellers."),
            "institutional": ("The game exposes coalition-dependent predictive utility.", "The source datasets were not collected in a data market."),
        },
        "procurement": {
            "data": ("ChileCompra amounts and OpenML prediction rows are observed open data.", "The two sources come from different institutions and are joined only for calibration."),
            "utility": ("Coalition utility is measured by the frozen OpenML validation task.", "Measured ML utility need not satisfy the monotone-submodular assumptions of every paper mechanism."),
            "participant_type": ("Seller costs follow the shape of observed positive CLP award values.", "Award values are normalized procurement-spend proxies, not latent data-owner reservation costs."),
            "institutional": ("A hard-budget buyer selects single-parameter sellers.", "Public procurement is not a data market; cross-domain conclusions are mechanism stress tests."),
        },
        "trading": {
            "data": ("Elexon Bid Offer Data are observed market submissions.", "Quantities, network constraints, and unit commitment are omitted."),
            "utility": ("Efficient gain from trade is computed from complete frozen proxy types.", "This welfare objective does not reproduce GB balancing settlement."),
            "participant_type": ("Buyer and seller profiles preserve normalized empirical bid/offer ordering and spread.", "Submitted prices are not directly observed private values or marginal costs."),
            "institutional": ("Mechanisms clear a balanced, single-unit, two-sided market.", "The original electricity institution is multi-unit and operationally constrained."),
        },
    }
    return {
        dimension: {"evidence": evidence, "limitation": limitation}
        for dimension, (evidence, limitation) in records[track].items()
    }


def _economic_observable(track: str) -> dict[str, Any]:
    """Declare what the source observes and which economic claims it cannot support."""

    records = {
        "valuation": {
            "semantic": "task_utility",
            "observed_measure": "held-out predictive utility from a trained model",
            "benchmark_role": "coalition utility",
            "claims_supported": ["task_utility"],
        },
        "procurement": {
            "semantic": "proxy",
            "observed_measure": "positive public-procurement award amount",
            "benchmark_role": "seller-cost distribution shape calibration",
            "claims_supported": ["proxy_calibration"],
        },
        "trading": {
            "semantic": "proxy",
            "observed_measure": "submitted balancing bid or offer price",
            "benchmark_role": "buyer-value and seller-cost distribution shape calibration",
            "claims_supported": ["proxy_calibration"],
        },
    }
    return {
        **records[track],
        "claims_forbidden": [
            "listing_ask",
            "transaction_price",
            "reservation_value",
            "buyer_value",
        ],
    }


def _make_manifest(
    config: Mapping[str, Any],
    protocol,
    protocol_path: Path,
    results_path: Path,
    cases: Mapping[str, tuple[Any, ...]],
    valuation_artifacts,
    procurement_artifacts,
    trading_artifacts,
    contrasts,
    representativeness,
) -> dict[str, Any]:
    contrast_specs = {item["contrast_id"]: item for item in config["contrasts"]}
    contrast_by_track: dict[str, list[dict[str, Any]]] = {
        "valuation": [], "procurement": [], "trading": []
    }
    for result in contrasts:
        spec = contrast_specs[result.contrast_id]
        record = {**spec, **asdict(result)}
        contrast_by_track[result.track].append(record)
    source_by_valuation = {item["source_id"]: item for item in config["sources"]["valuation"]}
    source_by_procurement = {item["block_id"]: item for item in config["sources"]["procurement"]}
    blocks = {"valuation": [], "procurement": [], "trading": []}
    for case in cases["valuation"]:
        block = case.metadata["independent_block"]
        if any(item["block_id"] == block for item in blocks["valuation"]):
            continue
        source_id = case.metadata["source_id"]
        raw_path, processed_path = valuation_artifacts[source_id]
        source = source_by_valuation[source_id]
        block_cases = [item.case_id for item in cases["valuation"] if item.metadata["independent_block"] == block]
        blocks["valuation"].append({
            "block_id": block,
            "source_kind": "open_dataset",
            "source_uri": source["canonical_source"],
            "license_id": source["license_id"],
            "source_artifact": _artifact(raw_path),
            "processed_artifact": _artifact(processed_path),
            "case_ids": block_cases,
            "economic_observable": _economic_observable("valuation"),
            "realism": _realism("valuation"),
        })
    for case in cases["procurement"]:
        block = case.metadata["independent_block"]
        if any(item["block_id"] == block for item in blocks["procurement"]):
            continue
        source = source_by_procurement[block]
        receipt, processed_path, _ = procurement_artifacts[source["source_id"]]
        block_cases = [item.case_id for item in cases["procurement"] if item.metadata["independent_block"] == block]
        blocks["procurement"].append({
            "block_id": block,
            "source_kind": "market_calibrated_open_data",
            "source_uri": source["registry_url"],
            "license_id": source["license_id"],
            "source_artifact": _artifact(receipt),
            "processed_artifact": _artifact(processed_path),
            "case_ids": block_cases,
            "economic_observable": _economic_observable("procurement"),
            "realism": _realism("procurement"),
        })
    for block, (receipt, processed_path, _) in trading_artifacts.items():
        block_cases = [item.case_id for item in cases["trading"] if item.metadata["independent_block"] == block]
        blocks["trading"].append({
            "block_id": block,
            "source_kind": "observed_market_submissions",
            "source_uri": config["sources"]["trading"][-1]["documentation"],
            "license_id": config["sources"]["trading"][-1]["license_id"],
            "source_artifact": _artifact(receipt),
            "processed_artifact": _artifact(processed_path),
            "case_ids": block_cases,
            "economic_observable": _economic_observable("trading"),
            "realism": _realism("trading"),
        })
    return {
        "schema_version": "1.0",
        "manifest_kind": "confirmatory_evidence",
        "cohort": "heldout",
        "evidence_scope": "real_trained_game",
        "replication_wave": config.get("replication_wave", "v1"),
        "release_id": config.get("replication_release_id", "kdd2027-heldout-v1"),
        "protocol": {
            **_artifact(protocol_path),
            "protocol_hash": protocol.protocol_hash,
        },
        "results": _artifact(results_path),
        "tracks": {
            track: {
                "setting_id": {
                    "valuation": "V-REPLICATION-ROBUSTNESS",
                    "procurement": "P-MARKET-CONCENTRATION",
                    "trading": "T-MARKET-THICKNESS",
                }[track],
                "blocks": blocks[track],
                "representativeness": representativeness[track],
                "contrasts": contrast_by_track[track],
            }
            for track in ("valuation", "procurement", "trading")
        },
    }


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    guard_output_separation(config, args.output, args.manifest)
    protocol = authorize_kdd_heldout_protocol(
        args.protocol, expected_sources=config["sources"]
    )
    if config.get("replication_wave"):
        replication_audit = audit_replication_protocol(
            args.config,
            args.protocol,
            MANIFEST_PATH,
            ROOT,
        )
        if replication_audit.errors:
            raise RuntimeError(
                "invalid replication protocol: " + ", ".join(replication_audit.errors)
            )
    valuation_datasets, valuation_artifacts = _load_valuation_sources(
        config, args.data_root
    )
    procurement_costs, procurement_artifacts = _load_procurement_costs(
        config, args.data_root
    )
    trading_profiles, trading_blocks, trading_artifacts = _load_trading_profiles(
        config, args.data_root
    )
    valuation_blocks = {
        source["source_id"]: source["block_id"]
        for source in config["sources"]["valuation"]
    }
    cases = {
        "valuation": make_heldout_valuation_cases(
            valuation_datasets,
            independent_blocks=valuation_blocks,
        ),
        "procurement": make_heldout_procurement_cases(valuation_datasets, procurement_costs),
        "trading": make_heldout_trading_cases(
            trading_profiles, independent_blocks=trading_blocks
        ),
    }
    methods = {
        track: {method: {} for method in method_ids}
        for track, method_ids in config["headline_methods"].items()
    }
    methods["procurement"]["budget_optimum"] = {}
    methods["trading"]["efficient_clearing"] = {}
    result_contract = config["result_contract"]
    run_config = BenchmarkConfig(
        name=args.run_name,
        output_dir=str(args.output),
        seeds=tuple(config["random_seeds"]),
        methods=methods,
        case_ids={track: tuple(case.case_id for case in track_cases) for track, track_cases in cases.items()},
        strategic_audit=True,
        result_metric_ids={
            track: tuple(result_contract["metric_ids"][track])
            for track in ("valuation", "procurement", "trading")
        },
        result_diagnostic_keys=tuple(result_contract["diagnostic_keys"]),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    results_path = args.output / "raw_results.jsonl"
    contrast_path = args.output / "confirmatory_contrasts.json"
    if args.reuse_results:
        if not results_path.is_file() or not contrast_path.is_file():
            raise RuntimeError("--reuse-results requires completed raw results and contrasts")
        contrast_rows = json.loads(contrast_path.read_text(encoding="utf-8"))
        contrasts = tuple(
            ContrastResult(
                **{
                    **row,
                    "missing_blocks": tuple(row.get("missing_blocks", [])),
                }
            )
            for row in contrast_rows
        )
        results = load_jsonl_results(results_path)
    else:
        results = run_benchmark(run_config, cases=cases)
        results_path = write_jsonl(results, results_path)
        write_track_csvs(results, args.output)
        write_leaderboard_csvs(results, args.output)
        write_markdown_report(results, args.output / "report.md")
        failures = [row for row in results if row.status != "completed"]
        if failures:
            summary = "\n".join(
                f"{row.track}/{row.case_id}/{row.method_id}: {row.status} {row.error or ''}"
                for row in failures[:20]
            )
            raise RuntimeError(
                f"held-out run has {len(failures)} incomplete rows:\n{summary}"
            )
        contrast_specs = tuple(ContrastSpec(**item) for item in config["contrasts"])
        contrasts = analyze_confirmatory_contrasts(results, contrast_specs)
        if any(result.effect is None for result in contrasts):
            raise RuntimeError(f"confirmatory contrast is not auditable: {contrasts}")
        _atomic_json(contrast_path, [asdict(item) for item in contrasts])

    write_reference_outcome_audit(
        results_path,
        args.output / "reference_outcome_audit.json",
        cases=cases,
    )

    development = build_cases(seed=42)
    valuation_repr = quantify_representativeness(
        [569, 178, 1797],
        [dataset.source_shape[0] for dataset in valuation_datasets.values()],
    )
    development_costs = [
        float(value)
        for case in development["procurement"]
        if case.metadata.get("benchmark_setting") == "P-MARKET-CONCENTRATION"
        for value in case.public.reported_costs.values()
    ]
    heldout_costs = [
        float(value)
        for costs in procurement_costs.values()
        for value in costs.values()
    ]
    procurement_repr = quantify_representativeness(development_costs, heldout_costs)
    development_types = [
        float(value)
        for case in development["trading"]
        if case.metadata.get("benchmark_setting") == "T-MARKET-THICKNESS"
        for value in (*case.true_values.values(), *case.true_costs.values())
    ]
    heldout_types = [
        value
        for case_id, profile in trading_profiles.items()
        if case_id.endswith("-n16")
        for value in (*profile.buyer_values, *profile.seller_costs)
    ]
    trading_repr = quantify_representativeness(development_types, heldout_types)
    procurement_coverage = min(1.0, min(
        artifact[2]["coverage"]["positive_clp_award_amounts"]
        / max(1, artifact[2]["coverage"]["matched_release_records"])
        for artifact in procurement_artifacts.values()
    ))
    trading_coverage = min(
        (profile.retained_bid_count + profile.retained_offer_count)
        / max(1, 2 * profile.source_row_count)
        for case_id, profile in trading_profiles.items()
        if case_id.endswith("-n16")
    )
    representativeness = {
        "valuation": {
            "metrics": _metric_records(valuation_repr),
            "coverage": 1.0,
            "limitations": "Sample-size distance is not semantic population similarity; class and feature shifts remain separate source-card limitations.",
        },
        "procurement": {
            "metrics": _metric_records(procurement_repr),
            "coverage": procurement_coverage,
            "limitations": "Distances compare normalized synthetic development costs with ChileCompra award-value proxies; they do not validate latent seller costs.",
        },
        "trading": {
            "metrics": _metric_records(trading_repr),
            "coverage": trading_coverage,
            "limitations": "Distances compare normalized single-unit benchmark types; quantity and institutional constraints are deliberately out of scope.",
        },
    }
    manifest = _make_manifest(
        config, protocol, args.protocol, results_path, cases,
        valuation_artifacts, procurement_artifacts, trading_artifacts,
        contrasts, representativeness,
    )
    manifest_path = _atomic_json(args.manifest, manifest)
    print(f"completed {result_row_count(results_path)} rows; evidence: {manifest_path}")


if __name__ == "__main__":
    main()
