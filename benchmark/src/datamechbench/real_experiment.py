"""Frozen-protocol gate and orchestration for real valuation experiments."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

import yaml


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _contains_test_derived_field(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            "test" in str(key).lower() or _contains_test_derived_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_test_derived_field(child) for child in value)
    return False


def _contains_outcome_derived_field(value: Any) -> bool:
    forbidden = (
        "selected_after",
        "observed_effect",
        "test_metric",
        "test_utility",
        "heldout_metric",
        "confirmatory_result",
        "confirmatory_outcome",
    )
    if isinstance(value, Mapping):
        return any(
            any(token in str(key).lower() for token in forbidden)
            or _contains_outcome_derived_field(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_outcome_derived_field(child) for child in value)
    return False


@dataclass(frozen=True)
class ProtocolFreeze:
    path: Path
    protocol_hash: str
    payload: Mapping[str, Any]


_PG_ELR_REQUIRED_HASHES = frozenset(
    {
        "selection_record",
        "method_source",
        "development_config",
        "confirmatory_config",
        "statistics_source",
        "report_template",
    }
)


def freeze_pg_elr_protocol(
    path: Path,
    *,
    selection: Mapping[str, Any],
    methods: Sequence[str],
    budgets: Mapping[str, Sequence[int]],
    metrics: Sequence[str],
    source_hashes: Mapping[str, str],
    feature_model_hashes: Mapping[str, str],
) -> ProtocolFreeze:
    """Freeze every choice that could alter the PG-ELR confirmatory claim."""

    if _contains_outcome_derived_field(selection):
        raise ValueError("outcome-derived fields are forbidden in the PG-ELR selection")
    if set(source_hashes) != _PG_ELR_REQUIRED_HASHES:
        missing = sorted(_PG_ELR_REQUIRED_HASHES - set(source_hashes))
        extra = sorted(set(source_hashes) - _PG_ELR_REQUIRED_HASHES)
        raise ValueError(f"PG-ELR source hashes mismatch; missing={missing}, extra={extra}")
    if not methods or not metrics:
        raise ValueError("PG-ELR methods and metrics must not be empty")
    if "probe_players" not in selection or "calibration_seeds" not in selection:
        raise ValueError("PG-ELR selection must contain probe_players and calibration_seeds")
    payload = {
        "schema_version": "1.0",
        "manifest_kind": "pg_elr_confirmatory_protocol",
        "selection": dict(selection),
        "methods": list(methods),
        "budgets": {name: list(values) for name, values in budgets.items()},
        "metrics": list(metrics),
        "source_hashes": dict(source_hashes),
        "feature_model_hashes": dict(feature_model_hashes),
        "confirmatory_utilities": None,
    }
    protocol_hash = _hash_payload(payload)
    record = {**payload, "protocol_hash": protocol_hash}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, target)
    return ProtocolFreeze(target, protocol_hash, record)


def authorize_pg_elr_confirmatory(
    marker_path: Path,
    *,
    expected_source_hashes: Mapping[str, str],
) -> ProtocolFreeze:
    """Authorize held-out access only for the exact frozen PG-ELR sources."""

    path = Path(marker_path)
    if not path.is_file():
        raise RuntimeError("PG-ELR freeze marker is required")
    record = json.loads(path.read_text())
    protocol_hash = record.pop("protocol_hash", None)
    if protocol_hash != _hash_payload(record):
        raise RuntimeError("PG-ELR freeze marker hash is invalid")
    if record.get("manifest_kind") != "pg_elr_confirmatory_protocol":
        raise RuntimeError("PG-ELR freeze marker kind is invalid")
    if record.get("source_hashes") != dict(expected_source_hashes):
        raise RuntimeError("current PG-ELR source hashes differ from the frozen hashes")
    if record.get("confirmatory_utilities") is not None:
        raise RuntimeError("PG-ELR freeze marker must not contain confirmatory utilities")
    return ProtocolFreeze(path, protocol_hash, {**record, "protocol_hash": protocol_hash})


_PG_ELR_ROW_FIELDS = frozenset(
    {
        "run_id",
        "config_hash",
        "status",
        "preprocessing_seconds",
        "calibration_seconds",
        "production_seconds",
        "logical_calls",
        "physical_calls",
        "unique_masks",
        "cost_ratio_median",
        "cost_ratio_q1",
        "cost_ratio_q3",
        "source_hash",
        "feature_hash",
        "model_hash",
    }
)


def _read_pg_elr_rows(
    path: Path,
    *,
    expected_config_hash: str,
) -> tuple[dict[str, Any], ...]:
    if not path.exists():
        return ()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"corrupt append-only row at line {line_number}") from exc
        if not isinstance(raw, Mapping):
            raise ValueError(f"corrupt append-only row at line {line_number}")
        row = dict(raw)
        missing = _PG_ELR_ROW_FIELDS - set(row)
        if missing:
            raise ValueError(
                f"corrupt append-only row at line {line_number}: missing {sorted(missing)}"
            )
        if row["config_hash"] != expected_config_hash:
            raise ValueError("append-only row config hash is incompatible")
        run_id = str(row["run_id"])
        if run_id in seen:
            raise ValueError(f"duplicate run_id in append-only rows: {run_id}")
        seen.add(run_id)
        rows.append(row)
    return tuple(rows)


def append_pg_elr_rows(
    path: Path,
    rows: Iterable[Mapping[str, Any]],
    *,
    expected_config_hash: str,
) -> int:
    """Append new evidence rows once, rejecting incompatible provenance."""

    target = Path(path)
    existing = _read_pg_elr_rows(
        target,
        expected_config_hash=expected_config_hash,
    )
    seen = {str(row["run_id"]) for row in existing}
    additions: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        missing = _PG_ELR_ROW_FIELDS - set(row)
        if missing:
            raise ValueError(f"result row is missing required fields: {sorted(missing)}")
        if row["config_hash"] != expected_config_hash:
            raise ValueError("result row config hash is incompatible")
        run_id = str(row["run_id"])
        if run_id in seen:
            continue
        seen.add(run_id)
        additions.append(row)
    if additions:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as stream:
            for row in additions:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return len(additions)


def _pg_elr_tasks(config: Mapping[str, Any], config_hash: str) -> tuple[dict[str, Any], ...]:
    seed_spec = config["estimator_seeds"]
    seeds = range(int(seed_spec["start"]), int(seed_spec["stop"]))
    partitions = config.get("partitions")
    methods = config.get("methods")
    if not isinstance(methods, list):
        raise ValueError("phase config methods must be an explicit frozen list")
    probe_grid = config.get("probe_grid", {})
    tasks: list[dict[str, Any]] = []
    for dataset in config["datasets"]:
        owner_count = int(dataset["owners"])
        dataset_partitions = (
            ((str(dataset["partition"]), None),)
            if "partition" in dataset
            else tuple(
                (str(name), int(spec["seed"]))
                for name, spec in partitions.items()
            )
        )
        budgets = config["budgets"][f"n{owner_count}"]
        for partition, declared_seed in dataset_partitions:
            split_seed = declared_seed
            if split_seed is None:
                split_seed = {"iid": 11, "label_skew": 29, "quantity_skew": 47}[partition]
            for budget in budgets:
                for estimator_seed in seeds:
                    for method in methods:
                        configs = (
                            tuple(
                                (int(k), int(m))
                                for k in probe_grid.get("players", ())
                                for m in probe_grid.get("seeds", ())
                            )
                            if method == "bd_pg_elr"
                            else ((None, None),)
                        )
                        for probe_players, calibration_seed_count in configs:
                            task = {
                                "dataset_id": str(dataset["id"]),
                                "owner_count": owner_count,
                                "partition": partition,
                                "split_seed": split_seed,
                                "budget": int(budget),
                                "estimator_seed": estimator_seed,
                                "method_id": str(method),
                                "probe_players": probe_players,
                                "calibration_seed_count": calibration_seed_count,
                                "config_hash": config_hash,
                            }
                            encoded = json.dumps(
                                task, sort_keys=True, separators=(",", ":")
                            ).encode()
                            task["run_id"] = hashlib.sha256(encoded).hexdigest()[:24]
                            tasks.append(task)
    return tuple(tasks)


def run_pg_elr_phase(
    config_path: Path,
    *,
    phase: Literal["development", "confirmatory"],
    output_dir: Path,
    resume: bool,
    gpu_ids: Sequence[int],
    dry_run: bool = False,
) -> Mapping[str, Any]:
    """Expand and audit one frozen paper phase without hiding incomplete work."""

    devices = tuple(int(device) for device in gpu_ids)
    if not devices or len(set(devices)) != len(devices) or any(
        device not in range(1, 8) for device in devices
    ):
        raise ValueError("physical GPU IDs must be unique members of 1..7")
    path = Path(config_path)
    config = yaml.safe_load(path.read_text())
    if not isinstance(config, Mapping) or config.get("phase") != phase:
        raise ValueError("phase config does not match requested phase")
    if phase == "development" and config.get("confirmatory_utilities") is not None:
        raise ValueError("development phase cannot load confirmatory utilities")
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    config_hash = hashlib.sha256(canonical.encode()).hexdigest()
    tasks = _pg_elr_tasks(config, config_hash)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    raw_path = target / "raw_results.jsonl"
    if raw_path.exists() and not resume:
        raise ValueError("append-only results exist; resume=True is required")
    completed_rows = _read_pg_elr_rows(
        raw_path,
        expected_config_hash=config_hash,
    ) if resume else ()
    completed_ids = {str(row["run_id"]) for row in completed_rows}
    task_ids = {str(task["run_id"]) for task in tasks}
    unknown = completed_ids - task_ids
    if unknown:
        raise ValueError(f"resume rows do not belong to current task matrix: {sorted(unknown)}")
    manifest = {
        "schema_version": "1.0",
        "study_id": config.get("study_id"),
        "phase": phase,
        "config_hash": config_hash,
        "physical_gpus": list(devices),
        "dry_run": bool(dry_run),
        "task_count": len(tasks),
        "remaining_task_count": len(tasks) - len(completed_ids),
        "run_ids": [str(task["run_id"]) for task in tasks],
        "completed_run_ids": sorted(completed_ids),
        "raw_results": str(raw_path),
        "required_result_fields": sorted(_PG_ELR_ROW_FIELDS),
    }
    temporary = target / f"task_manifest.json.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, target / "task_manifest.json")
    return manifest


def freeze_real_protocol(
    path: Path,
    *,
    input_hashes: Mapping[str, str],
    selected_fidelity_rule: str,
    budgets: Mapping[str, Sequence[int]],
    methods: Sequence[str],
    metrics: Sequence[str],
    development_artifact_hashes: Mapping[str, str],
    fidelity_record: Mapping[str, Any],
) -> ProtocolFreeze:
    if _contains_test_derived_field(fidelity_record):
        raise ValueError("test-derived fields are forbidden in the fidelity record")
    payload = {
        "schema_version": "1.0",
        "input_hashes": dict(input_hashes),
        "selected_fidelity_rule": selected_fidelity_rule,
        "budgets": {name: list(values) for name, values in budgets.items()},
        "methods": list(methods),
        "metrics": list(metrics),
        "development_artifact_hashes": dict(development_artifact_hashes),
        "fidelity_record": dict(fidelity_record),
        "confirmatory_utilities": None,
    }
    protocol_hash = _hash_payload(payload)
    record = {**payload, "protocol_hash": protocol_hash}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    os.replace(temporary, target)
    return ProtocolFreeze(target, protocol_hash, record)


def authorize_confirmatory(
    marker_path: Path,
    *,
    expected_input_hashes: Mapping[str, str],
) -> ProtocolFreeze:
    path = Path(marker_path)
    if not path.exists():
        raise RuntimeError("development freeze marker is required")
    record = json.loads(path.read_text())
    protocol_hash = record.pop("protocol_hash", None)
    if protocol_hash != _hash_payload(record):
        raise RuntimeError("development freeze marker hash is invalid")
    if record.get("input_hashes") != dict(expected_input_hashes):
        raise RuntimeError("current input hashes differ from the frozen protocol")
    if record.get("confirmatory_utilities") is not None:
        raise RuntimeError("freeze marker must not contain confirmatory utilities")
    return ProtocolFreeze(path, protocol_hash, {**record, "protocol_hash": protocol_hash})


def freeze_kdd_heldout_protocol(
    path: Path,
    *,
    sources: Mapping[str, Any],
    transformations: Mapping[str, Any],
    contrasts: Sequence[Mapping[str, Any]],
    headline_methods: Mapping[str, Sequence[str]],
    development_artifact_hashes: Mapping[str, str],
    protocol_revision: str = "1",
    amendment: Mapping[str, Any] | None = None,
) -> ProtocolFreeze:
    """Atomically freeze source and analysis choices before held-out access."""

    frozen_choices = {
        "sources": dict(sources),
        "transformations": dict(transformations),
        "contrasts": [dict(contrast) for contrast in contrasts],
        "headline_methods": {
            track: list(methods) for track, methods in headline_methods.items()
        },
    }
    if _contains_outcome_derived_field(frozen_choices) or (
        amendment is not None and _contains_outcome_derived_field(amendment)
    ):
        raise ValueError("outcome-derived fields are forbidden in the held-out protocol")
    payload = {
        "schema_version": "1.0",
        "manifest_kind": "confirmatory_protocol",
        "protocol_revision": str(protocol_revision),
        **frozen_choices,
        "development_artifact_hashes": dict(development_artifact_hashes),
        "confirmatory_outcomes": None,
    }
    if amendment is not None:
        payload["amendment"] = dict(amendment)
    protocol_hash = _hash_payload(payload)
    record = {**payload, "protocol_hash": protocol_hash}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)
    return ProtocolFreeze(target, protocol_hash, record)


def authorize_kdd_heldout_protocol(
    marker_path: Path,
    *,
    expected_sources: Mapping[str, Any],
) -> ProtocolFreeze:
    """Verify an untampered KDD held-out freeze without revealing outcomes."""

    path = Path(marker_path)
    if not path.is_file():
        raise RuntimeError("held-out freeze marker is required")
    record = json.loads(path.read_text(encoding="utf-8"))
    protocol_hash = record.pop("protocol_hash", None)
    if protocol_hash != _hash_payload(record):
        raise RuntimeError("held-out freeze marker hash is invalid")
    if record.get("manifest_kind") != "confirmatory_protocol":
        raise RuntimeError("held-out freeze marker kind is invalid")
    if record.get("sources") != dict(expected_sources):
        raise RuntimeError("held-out sources differ from the frozen protocol")
    if record.get("confirmatory_outcomes") is not None:
        raise RuntimeError("freeze marker must not contain confirmatory outcomes")
    return ProtocolFreeze(path, protocol_hash, {**record, "protocol_hash": protocol_hash})


__all__ = [
    "ProtocolFreeze",
    "append_pg_elr_rows",
    "authorize_confirmatory",
    "authorize_kdd_heldout_protocol",
    "authorize_pg_elr_confirmatory",
    "freeze_kdd_heldout_protocol",
    "freeze_pg_elr_protocol",
    "freeze_real_protocol",
    "run_pg_elr_phase",
]
