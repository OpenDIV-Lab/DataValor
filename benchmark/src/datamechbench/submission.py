"""Static validation of third-party result packages."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import yaml

from .metrics import (
    evaluate_procurement_metrics,
    evaluate_trading_metrics,
    evaluate_valuation_metrics,
)
from .models import (
    AllocationRecord,
    MarketOutcome,
    MethodSpec,
    PaymentRecord,
    ValuationOutput,
)
from .provenance import load_provenance
from .registry import validate_output
from .release import load_release_metadata
from .runner import build_cases, build_registry

REQUIRED_METADATA = (
    "submitter", "method_id", "family_id", "track", "source_url",
    "implementation_version", "implementation_license", "division",
    "benchmark_version", "result_schema_version", "submission_schema_version",
    "environment", "supported_settings", "seeds",
)
REQUIRED_RESULT_FIELDS = (
    "run_id", "track", "method_id", "case_id", "seed", "status", "metrics",
    "runtime_seconds", "error", "metadata", "schema_version",
)
SUBMISSION_SCHEMA_VERSION = "1.1"


@dataclass(frozen=True)
class SettingCoverage:
    setting: str
    expected_case_count: int
    expected_row_count: int
    observed_row_count: int
    missing_case_seed_pairs: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class SubmissionValidation:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    division: str
    row_count: int
    settings: tuple[str, ...]
    cases: tuple[str, ...]
    seeds: tuple[int, ...]
    coverage: tuple[SettingCoverage, ...]
    package_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@lru_cache(maxsize=1)
def _known_cases() -> dict[str, tuple[str, str]]:
    output = {}
    for track, cases in build_cases().items():
        for case in cases:
            setting = str(case.metadata.get("benchmark_setting", ""))
            output[case.case_id] = (track, setting)
    return output


@lru_cache(maxsize=1)
def _case_objects() -> dict[str, tuple[str, Any]]:
    return {
        case.case_id: (track, case)
        for track, cases in build_cases().items()
        for case in cases
    }


def _digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard numeric constant {value}")


def _numeric_values(value: Any):
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        yield float(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _numeric_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _numeric_values(item)


def _decimal(value: Any, label: str) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} must be decimal-compatible") from exc
    if not converted.is_finite():
        raise ValueError(f"{label} must be finite")
    return converted


def _parse_outcome(track: str, case: Any, raw: Any) -> ValuationOutput | MarketOutcome:
    if not isinstance(raw, Mapping):
        raise ValueError("raw outcome must be an object")
    diagnostics = raw.get("diagnostics", {})
    if not isinstance(diagnostics, Mapping):
        raise ValueError("outcome diagnostics must be an object")
    if track == "valuation":
        scores = raw.get("scores")
        if not isinstance(scores, Mapping) or set(map(str, scores)) != set(case.owner_ids):
            raise ValueError("valuation outcome scores must exactly match owner IDs")
        converted = {str(owner): float(value) for owner, value in scores.items()}
        if any(not math.isfinite(value) for value in converted.values()):
            raise ValueError("valuation outcome scores must be finite")
        utility_calls = raw.get("utility_calls")
        if utility_calls is not None and (
            isinstance(utility_calls, bool)
            or not isinstance(utility_calls, int)
            or utility_calls < 0
        ):
            raise ValueError("utility_calls must be null or a non-negative integer")
        return ValuationOutput(converted, dict(diagnostics), utility_calls)

    selected = raw.get("selected_ids", [])
    allocations = raw.get("allocations", [])
    payments = raw.get("payments", [])
    if not isinstance(selected, list) or not isinstance(allocations, list) or not isinstance(payments, list):
        raise ValueError("market outcome selected_ids, allocations, and payments must be lists")
    allocation_records = tuple(
        AllocationRecord(
            actor_id=str(item["actor_id"]),
            counterparty_id=(
                str(item["counterparty_id"])
                if item.get("counterparty_id") is not None
                else None
            ),
            product_ids=tuple(str(value) for value in item.get("product_ids", ())),
            quantity=_decimal(item.get("quantity", "1"), "allocation quantity"),
            metadata=dict(item.get("metadata", {})),
        )
        for item in allocations
        if isinstance(item, Mapping)
    )
    if len(allocation_records) != len(allocations):
        raise ValueError("every allocation must be an object")
    payment_records = tuple(
        PaymentRecord(
            payer_id=str(item["payer_id"]),
            payee_id=str(item["payee_id"]),
            amount=_decimal(item["amount"], "payment amount"),
            reason=str(item.get("reason", "external_submission")),
            product_ids=tuple(str(value) for value in item.get("product_ids", ())),
            metadata=dict(item.get("metadata", {})),
        )
        for item in payments
        if isinstance(item, Mapping)
    )
    if len(payment_records) != len(payments):
        raise ValueError("every payment must be an object")
    return MarketOutcome(
        selected_ids=tuple(str(value) for value in selected),
        allocations=allocation_records,
        payments=payment_records,
        diagnostics=dict(diagnostics),
    )


def _external_spec(metadata: Mapping[str, Any], track: str, case_type: str) -> MethodSpec:
    capabilities = (
        frozenset({"truthful_payments"})
        if track == "procurement"
        else frozenset({"payments"}) if track == "trading" else frozenset()
    )
    return MethodSpec(
        method_id=str(metadata["method_id"]),
        family_id=str(metadata["family_id"]),
        track=track,
        role="method",
        source=str(metadata["source_url"]),
        version=str(metadata["implementation_version"]),
        capabilities=capabilities,
        supported_case_types=frozenset({case_type}),
        provenance_kind="project_implementation",
        algorithm_location="external submission outcome",
    )


def _oracle_output(track: str, case: Any, seed: int) -> Any | None:
    registry = build_registry()
    candidates = [
        spec
        for spec in registry.compatible(track, case.case_type)
        if spec.role == "oracle"
    ]
    if not candidates:
        return None
    method = registry.create(sorted(candidates, key=lambda spec: spec.method_id)[0].method_id)
    if track == "valuation":
        return method.evaluate(case, seed)
    if track == "procurement":
        return method.allocate(case.public, seed)
    return method.clear(case.public, seed)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "to_dict"):
        return _json_ready(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def validate_submission(path: str | Path) -> SubmissionValidation:
    package = Path(path)
    metadata_path = package / "submission.yaml"
    results_path = package / "results.jsonl"
    errors: list[str] = []
    warnings: list[str] = []
    metadata: dict[str, Any] = {}
    if not metadata_path.is_file():
        errors.append("missing submission.yaml")
    else:
        try:
            loaded = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
            metadata = dict(loaded) if isinstance(loaded, Mapping) else {}
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"invalid submission.yaml: {exc}")
    for field in REQUIRED_METADATA:
        if field not in metadata or metadata[field] in (None, "", [], {}):
            errors.append(f"missing required metadata: {field}")
    source_url = str(metadata.get("source_url", ""))
    if source_url and urlparse(source_url).scheme not in {"http", "https"}:
        errors.append("source_url must use http or https")
    division = str(metadata.get("division", ""))
    if division and division not in {"reference", "open"}:
        errors.append("division must be reference or open")
    method_id = str(metadata.get("method_id", ""))
    family_id = str(metadata.get("family_id", ""))
    catalog_method = load_provenance().mechanisms.get(method_id)
    if division == "reference":
        if catalog_method is None:
            errors.append("reference division requires a registered method_id")
        else:
            if family_id != catalog_method.family_id:
                errors.append("reference division family_id does not match the catalog")
            if str(metadata.get("track", "")) != catalog_method.track:
                errors.append("reference division track does not match the catalog")
    elif division == "open" and catalog_method is not None:
        errors.append("open division method_id collides with a registered method")
    release = load_release_metadata()
    if metadata.get("benchmark_version") not in (None, "") and str(metadata.get("benchmark_version")) != release["benchmark_version"]:
        errors.append(
            f"benchmark version mismatch: {metadata.get('benchmark_version')} != {release['benchmark_version']}"
        )
    if metadata.get("result_schema_version") not in (None, "") and str(metadata.get("result_schema_version")) != release["result_schema_version"]:
        errors.append(
            f"result schema version mismatch: {metadata.get('result_schema_version')} != {release['result_schema_version']}"
        )
    if (
        metadata.get("submission_schema_version") not in (None, "")
        and str(metadata.get("submission_schema_version"))
        != SUBMISSION_SCHEMA_VERSION
    ):
        errors.append(
            "submission schema version mismatch: "
            f"{metadata.get('submission_schema_version')} != "
            f"{SUBMISSION_SCHEMA_VERSION}"
        )
    declared_track = str(metadata.get("track", ""))
    if declared_track and declared_track not in {"valuation", "procurement", "trading"}:
        errors.append(f"unknown track: {declared_track}")
    if metadata.get("environment") not in (None, "") and not isinstance(metadata.get("environment"), Mapping):
        errors.append("environment must be a mapping")
    supported_settings = metadata.get("supported_settings")
    if supported_settings not in (None, "") and not isinstance(supported_settings, (list, tuple)):
        errors.append("supported_settings must be a list")
    declared_settings = {str(value) for value in supported_settings} if isinstance(supported_settings, (list, tuple)) else set()
    declared_seed_values = metadata.get("seeds")
    declared_seeds: tuple[int, ...] = ()
    if not isinstance(declared_seed_values, (list, tuple)) or not declared_seed_values:
        errors.append("seeds must be a non-empty list of unique integers")
    elif (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in declared_seed_values
        )
        or len(set(declared_seed_values)) != len(declared_seed_values)
    ):
        errors.append("seeds must contain unique integers")
        declared_seeds = tuple(
            sorted(
                {
                    value
                    for value in declared_seed_values
                    if isinstance(value, int) and not isinstance(value, bool)
                }
            )
        )
    else:
        declared_seeds = tuple(sorted(declared_seed_values))
    known = _known_cases()
    known_settings = {setting for _, setting in known.values() if setting}
    for setting in sorted(declared_settings - known_settings):
        errors.append(f"unknown setting in supported_settings: {setting}")

    parsed_rows: list[dict[str, Any]] = []
    if not results_path.is_file():
        errors.append("missing results.jsonl")
    else:
        for line_number, line in enumerate(results_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line, parse_constant=_reject_constant)
                if not isinstance(raw, Mapping):
                    raise ValueError("row must be a JSON object")
                parsed_rows.append(dict(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(f"row {line_number}: {exc}")

    seen: set[tuple[str, int]] = set()
    observed_settings: set[str] = set()
    observed_cases: set[str] = set()
    observed_seeds: set[int] = set()
    observed_pairs: dict[str, set[tuple[str, int]]] = {}
    structurally_valid = 0
    for row_number, row in enumerate(parsed_rows, start=1):
        row_errors = 0

        def add(message: str) -> None:
            nonlocal row_errors
            row_errors += 1
            errors.append(f"row {row_number}: {message}")

        for field in REQUIRED_RESULT_FIELDS:
            if field not in row or (
                field not in {"metrics", "error"}
                and (row[field] is None or row[field] == "")
            ):
                add(f"missing result field: {field}")

        case_id = str(row.get("case_id", ""))
        raw_seed = row.get("seed")
        if isinstance(raw_seed, bool) or not isinstance(raw_seed, int):
            seed: int | None = None
            add("seed must be an integer")
        else:
            seed = raw_seed
            if declared_seeds and seed not in declared_seeds:
                add(f"seed not declared in seeds: {seed}")
            key = (case_id, seed)
            if key in seen:
                add(f"duplicate case/seed row: {case_id}/{seed}")
            seen.add(key)
        case_info = known.get(case_id)
        if case_info is None:
            add(f"unknown case: {case_id}")
        else:
            observed_cases.add(case_id)
            expected_track, expected_setting = case_info
            if str(row.get("track", "")) != expected_track:
                add(f"case track mismatch for {case_id}")
            if declared_track and expected_track != declared_track:
                add(f"submission track mismatch for {case_id}")
        row_metadata = row.get("metadata") if isinstance(row.get("metadata"), Mapping) else {}
        setting = str(row_metadata.get("benchmark_setting", ""))
        if setting:
            observed_settings.add(setting)
        if setting not in known_settings:
            add(f"unknown setting: {setting}")
        elif case_info is not None and setting != case_info[1]:
            add(f"case/setting mismatch for {case_id}: {setting} != {case_info[1]}")
        if declared_settings and setting not in declared_settings:
            add(f"setting not declared in supported_settings: {setting}")
        if case_info is not None and seed is not None and setting in declared_settings:
            observed_pairs.setdefault(setting, set()).add((case_id, seed))
        if str(row.get("method_id", "")) != str(metadata.get("method_id", "")):
            add("method mismatch between submission and result")
        if str(row_metadata.get("method_family", "")) != str(metadata.get("family_id", "")):
            add("family mismatch between submission and result")
        if str(row.get("schema_version", "")) != release["result_schema_version"]:
            add(f"schema version mismatch: {row.get('schema_version')}")
        status = str(row.get("status", ""))
        if status not in {"completed", "skipped", "failed"}:
            add(f"invalid status: {status}")
        metrics = row.get("metrics")
        error = row.get("error")
        if status == "completed":
            if not isinstance(metrics, Mapping) or not metrics:
                add("completed result requires metrics")
            if error is not None and error != "":
                add("completed result requires an empty error")
            if "outcome" not in row:
                add("completed result requires a raw outcome")
            elif case_info is not None:
                try:
                    _, case = _case_objects()[case_id]
                    output = _parse_outcome(expected_track, case, row.get("outcome"))
                    spec = _external_spec(metadata, expected_track, case.case_type)
                    public_case = case if expected_track == "valuation" else case.public
                    validate_output(spec, public_case, output)
                except (KeyError, TypeError, ValueError) as exc:
                    add(f"invalid raw outcome: {exc}")
        elif status in {"skipped", "failed"}:
            if not isinstance(metrics, Mapping) or metrics:
                add(f"{status} result requires empty metrics")
            if not isinstance(error, str) or not error.strip():
                add(f"{status} result requires a non-empty error/reason")
        try:
            runtime = float(row.get("runtime_seconds"))
            if not math.isfinite(runtime) or runtime < 0:
                raise ValueError
        except (TypeError, ValueError):
            add("runtime_seconds must be finite and non-negative")
        if isinstance(metrics, Mapping) and any(not math.isfinite(value) for value in _numeric_values(metrics)):
            add("metrics contain non-finite numeric value")
        if seed is not None:
            observed_seeds.add(seed)
        if row_errors == 0:
            structurally_valid += 1
    coverage: list[SettingCoverage] = []
    for setting in sorted(declared_settings):
        expected_cases = tuple(
            sorted(
                case_id
                for case_id, (track, case_setting) in known.items()
                if track == declared_track and case_setting == setting
            )
        )
        expected_pairs = {
            (case_id, seed)
            for case_id in expected_cases
            for seed in declared_seeds
        }
        actual_pairs = observed_pairs.get(setting, set())
        missing = tuple(sorted(expected_pairs - actual_pairs))
        for case_id, seed in missing:
            errors.append(f"missing declared case/seed result: {case_id}/{seed}")
        coverage.append(
            SettingCoverage(
                setting=setting,
                expected_case_count=len(expected_cases),
                expected_row_count=len(expected_pairs),
                observed_row_count=len(actual_pairs & expected_pairs),
                missing_case_seed_pairs=missing,
            )
        )
    if structurally_valid == 0:
        errors.append("submission contains zero valid results")
    return SubmissionValidation(
        not errors,
        tuple(errors),
        tuple(warnings),
        division,
        len(parsed_rows),
        tuple(sorted(observed_settings)),
        tuple(sorted(observed_cases)),
        tuple(sorted(observed_seeds)),
        tuple(coverage),
        _digest((metadata_path, results_path)),
    )


def evaluate_submission(path: str | Path) -> dict[str, Any]:
    """Recompute authoritative metrics from submitted raw outcomes.

    The `metrics` field in `results.jsonl` is treated only as submitter-side
    diagnostic output.  Returned metrics are produced by this evaluator.
    """

    validation = validate_submission(path)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "authoritative_metrics": "evaluator_recomputed",
        "validation": validation.to_dict(),
        "results": [],
    }
    if not validation.valid:
        return payload
    package = Path(path)
    metadata = yaml.safe_load((package / "submission.yaml").read_text(encoding="utf-8"))
    rows = [
        json.loads(line, parse_constant=_reject_constant)
        for line in (package / "results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    parsed: dict[tuple[str, int], Any] = {}
    for row in rows:
        if row["status"] != "completed":
            continue
        track, case = _case_objects()[str(row["case_id"])]
        parsed[(str(row["case_id"]), int(row["seed"]))] = _parse_outcome(
            track, case, row["outcome"]
        )

    trusted_rows: list[dict[str, Any]] = []
    for row in rows:
        trusted = dict(row)
        trusted["submitted_metrics"] = trusted.pop("metrics", {})
        if row["status"] != "completed":
            trusted["metrics"] = {}
            trusted_rows.append(_json_ready(trusted))
            continue
        track, case = _case_objects()[str(row["case_id"])]
        seed = int(row["seed"])
        output = parsed[(str(row["case_id"]), seed)]
        oracle = _oracle_output(track, case, seed)
        spec = _external_spec(metadata, track, case.case_type)
        if track == "valuation":
            peers: list[Any] = [
                peer
                for (peer_case, peer_seed), peer in parsed.items()
                if peer_case == case.case_id and peer_seed != seed
            ]
            baseline = case.metadata.get("replication_baseline_case_id")
            if baseline and (str(baseline), seed) in parsed:
                _, baseline_case = _case_objects()[str(baseline)]
                peers.append((baseline_case, parsed[(str(baseline), seed)]))
            metrics = evaluate_valuation_metrics(
                case, output, oracle_output=oracle, peer_outputs=peers
            )
        elif track == "procurement":
            metrics = evaluate_procurement_metrics(
                case, output, spec, oracle_output=oracle, method=None, seed=seed
            )
        else:
            metrics = evaluate_trading_metrics(
                case, output, spec, oracle_output=oracle, method=None, seed=seed
            )
        trusted["metrics"] = _json_ready(metrics)
        trusted["metadata"] = {
            **dict(trusted.get("metadata", {})),
            "metric_authority": "evaluator_recomputed",
        }
        trusted_rows.append(_json_ready(trusted))
    payload["results"] = trusted_rows
    return payload


__all__ = [
    "SettingCoverage",
    "SubmissionValidation",
    "evaluate_submission",
    "validate_submission",
]
