"""Fail-closed audit for licensed, public AI data-licensing deal evidence."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = PACKAGE_ROOT.parent

PRICE_EVIDENCE_CLASSES = frozenset(
    {
        "missing",
        "undisclosed_or_non_numeric",
        "estimated_or_revenue_proxy",
        "offer_or_unit_quote",
        "share_only",
        "reported_deal_amount",
        "inconsistent_amount",
    }
)
_VALID_MODALITIES = frozenset({"text", "image, video"})
_VALID_PRICING_MECHANISMS = frozenset({"aggregate", "per_unit", "unknown"})
_REQUIRED_PROHIBITED_USES = frozenset(
    {
        "seller reservation-cost calibration",
        "buyer-value calibration",
        "mechanism outcome benchmarking",
        "row-iid population inference",
    }
)
_CURRENCY_AMOUNT = re.compile(
    r"(?:[$€£]\s*\d|\b(?:usd|eur|gbp)\s*\d)", re.IGNORECASE
)


def classify_price_evidence(value: str | None) -> str:
    """Classify source wording without converting unlike price bases."""

    if value is None or not str(value).strip():
        return "missing"
    normalized = " ".join(str(value).strip().lower().split())
    if "$42k/month" in normalized and "$2.5m/year" in normalized:
        return "inconsistent_amount"
    if any(
        marker in normalized
        for marker in (
            "est. ",
            "estimated",
            "could add",
            "revenue grew",
            "added $",
            "overall ai-related revenue",
        )
    ):
        return "estimated_or_revenue_proxy"
    if any(
        marker in normalized
        for marker in ("offers of", "reportedly offers", "fee per book")
    ):
        return "offer_or_unit_quote"
    if "possibility" in normalized:
        return "undisclosed_or_non_numeric"
    if any(
        marker in normalized
        for marker in (
            "revenue share",
            "royalty payment",
            "percentage share",
            "pay royalties",
            "50/50 revenue split",
        )
    ):
        return "share_only"
    if _CURRENCY_AMOUNT.search(normalized):
        return "reported_deal_amount"
    return "undisclosed_or_non_numeric"


@dataclass(frozen=True)
class DataDealEvidenceAudit:
    snapshot: str
    source_dataset: str
    source_revision: str
    source_file_sha256: str
    license_id: str
    row_count: int
    allowed_uses: tuple[str, ...]
    prohibited_uses: tuple[str, ...]
    price_evidence_counts: Mapping[str, int]
    pricing_mechanism_counts: Mapping[str, int]
    reported_deal_amount_count: int
    high_confidence_reported_deal_amount_count: int
    buyer_count: int
    seller_count: int
    top_buyer_row_count: int
    top_two_buyer_share: float
    invalid_modality_row_count: int
    role_complete_count: int
    financial_terms_present_count: int
    source_url_count: int
    known_exclusivity_count: int
    creator_compensation_reported_count: int
    use_case_counts: Mapping[str, int]
    record_iid_eligible: bool
    mechanism_replayable_record_count: int
    private_type_calibration_eligible: bool
    mechanism_outcome_eligible: bool
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "report_kind": "ai_data_deal_evidence_audit",
            "snapshot": self.snapshot,
            "source_dataset": self.source_dataset,
            "source_revision": self.source_revision,
            "source_file_sha256": self.source_file_sha256,
            "license_id": self.license_id,
            "valid": self.valid,
            "row_count": self.row_count,
            "allowed_uses": list(self.allowed_uses),
            "prohibited_uses": list(self.prohibited_uses),
            "price_evidence_counts": dict(self.price_evidence_counts),
            "pricing_mechanism_counts": dict(self.pricing_mechanism_counts),
            "reported_deal_amount_count": self.reported_deal_amount_count,
            "high_confidence_reported_deal_amount_count": (
                self.high_confidence_reported_deal_amount_count
            ),
            "buyer_count": self.buyer_count,
            "seller_count": self.seller_count,
            "top_buyer_row_count": self.top_buyer_row_count,
            "top_two_buyer_share": self.top_two_buyer_share,
            "invalid_modality_row_count": self.invalid_modality_row_count,
            "role_complete_count": self.role_complete_count,
            "financial_terms_present_count": self.financial_terms_present_count,
            "source_url_count": self.source_url_count,
            "known_exclusivity_count": self.known_exclusivity_count,
            "creator_compensation_reported_count": (
                self.creator_compensation_reported_count
            ),
            "use_case_counts": dict(self.use_case_counts),
            "record_iid_eligible": self.record_iid_eligible,
            "mechanism_replayable_record_count": (
                self.mechanism_replayable_record_count
            ),
            "private_type_calibration_eligible": (
                self.private_type_calibration_eligible
            ),
            "mechanism_outcome_eligible": self.mechanism_outcome_eligible,
            "errors": list(self.errors),
        }


def _text(record: Mapping[str, Any], field: str, prefix: str, errors: list[str]) -> str:
    raw = record.get(field)
    value = raw.strip() if isinstance(raw, str) else ""
    if not value or value.startswith("<"):
        errors.append(f"{prefix}:missing_{field}")
    return value


def _string_list(
    record: Mapping[str, Any], field: str, prefix: str, errors: list[str]
) -> tuple[str, ...]:
    raw = record.get(field)
    if not isinstance(raw, list) or not raw:
        errors.append(f"{prefix}:{field}:must_be_nonempty_list")
        return ()
    values = tuple(value.strip() if isinstance(value, str) else "" for value in raw)
    if any(not value or value.startswith("<") for value in values):
        errors.append(f"{prefix}:{field}:invalid_item")
    return values


def _snapshot_label(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def audit_data_deal_snapshot(path: str | Path) -> DataDealEvidenceAudit:
    """Validate and summarize a minimized snapshot of licensed deal records."""

    snapshot_path = Path(path)
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("data-deal snapshot must be a mapping")
    errors: list[str] = []
    if str(payload.get("schema_version", "")) != "1.0":
        errors.append("unsupported_schema_version")

    source = payload.get("source")
    if not isinstance(source, Mapping):
        source = {}
        errors.append("source:must_be_mapping")
    source_dataset = _text(source, "dataset_id", "source", errors)
    source_revision = _text(source, "revision", "source", errors)
    source_file_sha256 = _text(source, "source_file_sha256", "source", errors)
    if not re.fullmatch(r"[0-9a-f]{64}", source_file_sha256):
        errors.append("source:invalid_source_file_sha256")
    license_id = _text(source, "license_id", "source", errors)
    if license_id != "CC-BY-4.0":
        errors.append(f"source:unsupported_license:{license_id}")
    _text(source, "source_url", "source", errors)
    _text(source, "attribution", "source", errors)

    use_contract = payload.get("use_contract")
    if not isinstance(use_contract, Mapping):
        use_contract = {}
        errors.append("use_contract:must_be_mapping")
    allowed_uses = _string_list(
        use_contract, "allowed_uses", "use_contract", errors
    )
    prohibited_uses = _string_list(
        use_contract, "prohibited_uses", "use_contract", errors
    )
    overlap = sorted(set(allowed_uses) & set(prohibited_uses))
    if overlap:
        errors.append("use_contract:allowed_prohibited_overlap:" + ",".join(overlap))
    missing_prohibitions = sorted(
        _REQUIRED_PROHIBITED_USES.difference(prohibited_uses)
    )
    errors.extend(
        f"use_contract:missing_prohibited_use:{use}"
        for use in missing_prohibitions
    )

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        errors.append("rows:must_be_nonempty_list")
        rows = []
    expected_row_count = source.get("row_count")
    if expected_row_count != len(rows):
        errors.append(
            f"source:row_count_mismatch:declared={expected_row_count}:observed={len(rows)}"
        )

    row_ids: set[str] = set()
    evidence_counts: Counter[str] = Counter()
    mechanism_counts: Counter[str] = Counter()
    buyers: Counter[str] = Counter()
    sellers: Counter[str] = Counter()
    high_confidence_reported = 0
    invalid_modality_rows = 0
    role_complete_rows = 0
    financial_terms_present = 0
    source_urls = 0
    known_exclusivity = 0
    creator_compensation_reported = 0
    use_cases: Counter[str] = Counter()
    for index, raw_row in enumerate(rows):
        if not isinstance(raw_row, Mapping):
            errors.append(f"row:{index}:must_be_mapping")
            continue
        row_id = _text(raw_row, "row_id", f"row:{index}", errors)
        if not re.fullmatch(r"[0-9a-f]{64}", row_id):
            errors.append(f"row:{row_id or index}:invalid_row_id")
        if row_id in row_ids:
            errors.append(f"duplicate_row_id:{row_id}")
        row_ids.add(row_id)

        stored_class = str(raw_row.get("price_evidence_class", "")).strip()
        if stored_class not in PRICE_EVIDENCE_CLASSES:
            errors.append(
                f"row:{row_id or index}:invalid_price_evidence_class:{stored_class}"
            )
        financial_terms = raw_row.get("financial_terms")
        if financial_terms is not None and not isinstance(financial_terms, Mapping):
            errors.append(f"row:{row_id or index}:financial_terms:must_be_mapping_or_null")
            financial_terms = None
        if financial_terms:
            financial_terms_present += 1
        value = financial_terms.get("value") if financial_terms else None
        derived_class = classify_price_evidence(value)
        if stored_class in PRICE_EVIDENCE_CLASSES and stored_class != derived_class:
            errors.append(
                f"row:{row_id or index}:price_evidence_class_mismatch:"
                f"stored={stored_class}:derived={derived_class}"
            )
        evidence_counts[derived_class] += 1
        confidence = str(financial_terms.get("confidence", "")) if financial_terms else ""
        if derived_class == "reported_deal_amount" and confidence == "high":
            high_confidence_reported += 1

        mechanism = str(raw_row.get("pricing_mechanism", "")).strip()
        if mechanism not in _VALID_PRICING_MECHANISMS:
            errors.append(
                f"row:{row_id or index}:invalid_pricing_mechanism:{mechanism}"
            )
        mechanism_counts[mechanism] += 1
        buyer = _text(raw_row, "buyer", f"row:{row_id or index}", errors)
        seller = _text(raw_row, "seller", f"row:{row_id or index}", errors)
        if buyer and seller:
            role_complete_rows += 1
        buyers[buyer] += 1
        sellers[seller] += 1
        if isinstance(raw_row.get("source_url"), str) and str(
            raw_row["source_url"]
        ).strip():
            source_urls += 1
        exclusivity = str(raw_row.get("exclusivity", "unknown")).strip()
        if exclusivity and exclusivity != "unknown":
            known_exclusivity += 1
        if raw_row.get("creator_compensated") is not None:
            creator_compensation_reported += 1
        use_cases[str(raw_row.get("use_case", "unknown")).strip() or "unknown"] += 1
        modality = raw_row.get("modality")
        if modality is not None and str(modality) not in _VALID_MODALITIES:
            invalid_modality_rows += 1

    buyer_frequencies = sorted(buyers.values(), reverse=True)
    top_buyer_rows = buyer_frequencies[0] if buyer_frequencies else 0
    top_two_share = (
        round(sum(buyer_frequencies[:2]) / len(rows), 12) if rows else 0.0
    )
    prohibited = set(prohibited_uses)
    audit_valid = not errors
    return DataDealEvidenceAudit(
        snapshot=_snapshot_label(snapshot_path),
        source_dataset=source_dataset,
        source_revision=source_revision,
        source_file_sha256=source_file_sha256,
        license_id=license_id,
        row_count=len(rows),
        allowed_uses=allowed_uses,
        prohibited_uses=prohibited_uses,
        price_evidence_counts=dict(sorted(evidence_counts.items())),
        pricing_mechanism_counts=dict(sorted(mechanism_counts.items())),
        reported_deal_amount_count=evidence_counts["reported_deal_amount"],
        high_confidence_reported_deal_amount_count=high_confidence_reported,
        buyer_count=len(buyers),
        seller_count=len(sellers),
        top_buyer_row_count=top_buyer_rows,
        top_two_buyer_share=top_two_share,
        invalid_modality_row_count=invalid_modality_rows,
        role_complete_count=role_complete_rows,
        financial_terms_present_count=financial_terms_present,
        source_url_count=source_urls,
        known_exclusivity_count=known_exclusivity,
        creator_compensation_reported_count=creator_compensation_reported,
        use_case_counts=dict(sorted(use_cases.items())),
        record_iid_eligible=False,
        mechanism_replayable_record_count=0,
        private_type_calibration_eligible=(
            audit_valid
            and "seller reservation-cost calibration" not in prohibited
        ),
        mechanism_outcome_eligible=(
            audit_valid and "mechanism outcome benchmarking" not in prohibited
        ),
        errors=tuple(errors),
    )


def write_data_deal_evidence_report(
    snapshot_path: str | Path, output_path: str | Path
) -> Path:
    """Write a deterministic JSON report for a valid frozen snapshot."""

    audit = audit_data_deal_snapshot(snapshot_path)
    if not audit.valid:
        raise ValueError("invalid data-deal snapshot: " + "; ".join(audit.errors))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(audit.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


__all__ = [
    "DataDealEvidenceAudit",
    "PRICE_EVIDENCE_CLASSES",
    "audit_data_deal_snapshot",
    "classify_price_evidence",
    "write_data_deal_evidence_report",
]
