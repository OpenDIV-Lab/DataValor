"""Provider-group incidence diagnostics for controlled market mechanisms."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable, Mapping

from .induced_value_gold import make_induced_value_cases
from .models import BenchmarkResult, MarketOutcome, ProcurementCase, TradeCase
from .outcomes import parse_outcome
from .report import load_jsonl_results

OUTPUT_NAMES = ("run_incidence.csv", "method_group_summary.csv", "summary.json")


@dataclass(frozen=True)
class GroupIncidenceRow:
    track: str
    method_id: str
    case_id: str
    seed: int
    group_id: str
    group_member_count: int
    selected_count: int
    selection_rate: float
    payment_total: Decimal
    payment_share: float
    payment_denominator_status: str
    seller_surplus_total: Decimal
    seller_surplus_per_member: Decimal


def analyze_group_incidence(
    results: Iterable[BenchmarkResult],
    cases: Mapping[str, ProcurementCase | TradeCase],
) -> tuple[GroupIncidenceRow, ...]:
    """Compute role-based incidence; group labels are experimental, not protected classes."""

    rows: list[GroupIncidenceRow] = []
    for result in results:
        if result.status != "completed" or result.track not in {"procurement", "trading"}:
            continue
        if result.case_id not in cases:
            raise ValueError(f"missing controlled case: {result.case_id}")
        case = cases[result.case_id]
        groups = case.metadata.get("provider_groups")
        if not isinstance(groups, Mapping) or not groups:
            raise ValueError(f"case {result.case_id} lacks provider_groups")
        outcome = parse_outcome(result.track, result.outcome or {})
        if not isinstance(outcome, MarketOutcome):
            raise ValueError("market track requires MarketOutcome")
        sellers = tuple(case.public.seller_ids)
        if set(groups) != set(sellers):
            raise ValueError(f"case {result.case_id} has incomplete provider_groups")
        selected = set(outcome.selected_ids) & set(sellers)
        payments = {seller: Decimal("0") for seller in sellers}
        for payment in outcome.payments:
            if payment.payee_id in payments:
                payments[payment.payee_id] += payment.amount
        total_payment = sum(payments.values(), Decimal("0"))
        for group_id in sorted({str(value) for value in groups.values()}):
            members = tuple(
                seller for seller in sellers if str(groups[seller]) == group_id
            )
            if not members:
                raise ValueError(f"empty provider group: {group_id}")
            selected_members = set(members) & selected
            group_payment = sum((payments[seller] for seller in members), Decimal("0"))
            group_surplus = sum(
                (
                    payments[seller]
                    - (case.true_costs[seller] if seller in selected else Decimal("0"))
                    for seller in members
                ),
                Decimal("0"),
            )
            rows.append(
                GroupIncidenceRow(
                    track=result.track,
                    method_id=result.method_id,
                    case_id=result.case_id,
                    seed=result.seed,
                    group_id=group_id,
                    group_member_count=len(members),
                    selected_count=len(selected_members),
                    selection_rate=len(selected_members) / len(members),
                    payment_total=group_payment,
                    payment_share=(
                        float(group_payment / total_payment)
                        if total_payment > 0
                        else 0.0
                    ),
                    payment_denominator_status=(
                        "positive_total_payment"
                        if total_payment > 0
                        else "zero_total_payment"
                    ),
                    seller_surplus_total=group_surplus,
                    seller_surplus_per_member=group_surplus / len(members),
                )
            )
    return tuple(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_value(value: Any) -> Any:
    return str(value) if isinstance(value, Decimal) else value


def build_distributive_incidence(
    output_dir: str | Path,
    *,
    repository_root: str | Path,
    results_path: str | Path,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    root = Path(repository_root)
    source = Path(results_path)
    if not source.is_absolute():
        source = root / source
    generated = make_induced_value_cases()
    cases = {
        case.case_id: case
        for track in ("procurement", "trading")
        for case in generated[track]
    }
    rows = analyze_group_incidence(load_jsonl_results(source), cases)
    columns = tuple(GroupIncidenceRow.__dataclass_fields__)
    with (output / "run_incidence.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {key: _csv_value(value) for key, value in vars(row).items()} for row in rows
        )

    keys = sorted({(row.track, row.method_id, row.group_id) for row in rows})
    summary_rows: list[dict[str, Any]] = []
    for track, method_id, group_id in keys:
        subset = tuple(
            row
            for row in rows
            if (row.track, row.method_id, row.group_id)
            == (track, method_id, group_id)
        )
        summary_rows.append(
            {
                "track": track,
                "method_id": method_id,
                "group_id": group_id,
                "run_count": len(subset),
                "mean_selection_rate": fmean(row.selection_rate for row in subset),
                "mean_payment_share": fmean(row.payment_share for row in subset),
                "mean_seller_surplus_per_member": fmean(
                    float(row.seller_surplus_per_member) for row in subset
                ),
                "zero_payment_run_count": sum(
                    row.payment_denominator_status == "zero_total_payment"
                    for row in subset
                ),
            }
        )
    with (output / "method_group_summary.csv").open("w", encoding="utf-8", newline="") as stream:
        columns_summary = (
            "track",
            "method_id",
            "group_id",
            "run_count",
            "mean_selection_rate",
            "mean_payment_share",
            "mean_seller_surplus_per_member",
            "zero_payment_run_count",
        )
        writer = csv.DictWriter(stream, fieldnames=columns_summary, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary_rows)
    summary = {
        "schema_version": "1.0",
        "study_id": "kdd-distributive-incidence-v1",
        "valid": bool(rows),
        "run_group_row_count": len(rows),
        "method_group_row_count": len(summary_rows),
        "track_method_counts": {
            track: len({row.method_id for row in rows if row.track == track})
            for track in ("procurement", "trading")
        },
        "group_ids": sorted({row.group_id for row in rows}),
        "claim_boundary": (
            "These are controlled provider-size-group incidence diagnostics, not "
            "protected-class fairness measurements or observed-market causal effects."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "distributive_incidence",
        "inputs": [{"path": str(results_path), "sha256": _sha256(source)}],
        "outputs": [
            {"path": name, "sha256": _sha256(output / name)} for name in OUTPUT_NAMES
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def verify_distributive_incidence(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"valid": False, "errors": [f"invalid_manifest:{type(exc).__name__}"]}
    errors: list[str] = []
    outputs = payload.get("outputs", [])
    seen: set[str] = set()
    for record in outputs if isinstance(outputs, list) else ():
        name = str(record.get("path", "")) if isinstance(record, Mapping) else ""
        seen.add(name)
        target = path.parent / name
        if name not in OUTPUT_NAMES or not target.is_file():
            errors.append(f"missing_or_invalid:{name}")
        elif _sha256(target) != str(record.get("sha256", "")):
            errors.append(f"hash_mismatch:{name}")
    errors.extend(f"missing_binding:{name}" for name in sorted(set(OUTPUT_NAMES) - seen))
    return {"valid": not errors, "errors": errors, "output_count": len(seen)}


__all__ = [
    "GroupIncidenceRow",
    "analyze_group_incidence",
    "build_distributive_incidence",
    "verify_distributive_incidence",
]
