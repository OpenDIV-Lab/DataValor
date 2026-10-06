"""Real-market semantic alignment without converting evidence into private types."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .data_deal_evidence import audit_data_deal_snapshot

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = PACKAGE_ROOT / "catalog" / "market_evidence_layers.yaml"
DEFAULT_DEAL_SNAPSHOT = (
    PACKAGE_ROOT
    / "data"
    / "external"
    / "ai_data_deals_cc_by_4"
    / "snapshot.json"
)
DEFAULT_HELDOUT_MANIFESTS = (
    PACKAGE_ROOT / "evidence" / "kdd_heldout_confirmatory_v1.json",
    PACKAGE_ROOT / "evidence" / "kdd_heldout_replication_v2.json",
)
DEFAULT_DIRECT_FINDINGS = (
    PACKAGE_ROOT / "outputs" / "kdd_direct_market_transfer" / "findings.json"
)
DEFAULT_AGGREGATE_FINDINGS = (
    PACKAGE_ROOT / "outputs" / "kdd_aggregate_type_envelope" / "findings.json"
)
DEFAULT_OCEAN_AUDIT = (
    PACKAGE_ROOT / "evidence" / "ocean_settlement_source_audit_v1.json"
)
DEFAULT_OUTPUT = PACKAGE_ROOT / "outputs" / "kdd_market_semantics"


@dataclass(frozen=True)
class EvidenceLayer:
    layer_id: str
    semantic: str
    evidence_unit: str
    observed_units: int
    admission_status: str
    allowed_claim: str
    forbidden_claim: str
    private_types_observed: bool = False
    mechanism_outcome_replayable: bool = False


@dataclass(frozen=True)
class TrackClaimSupport:
    track: str
    performance_support: str
    private_type_support: str
    transaction_outcome_support: str
    interpretation: str


@dataclass(frozen=True)
class MarketSemanticAlignment:
    valid: bool
    layers: tuple[EvidenceLayer, ...]
    track_support: tuple[TrackClaimSupport, ...]
    deal_evidence: Mapping[str, Any]
    forbidden_claims: tuple[str, ...]
    private_type_observed_layer_count: int
    mechanism_outcome_replayable_layer_count: int
    errors: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "report_kind": "real_market_semantic_alignment",
            "valid": self.valid,
            "layer_count": len(self.layers),
            "private_type_observed_layer_count": (
                self.private_type_observed_layer_count
            ),
            "mechanism_outcome_replayable_layer_count": (
                self.mechanism_outcome_replayable_layer_count
            ),
            "layers": [asdict(row) for row in self.layers],
            "track_support": [asdict(row) for row in self.track_support],
            "deal_evidence": dict(self.deal_evidence),
            "forbidden_claims": list(self.forbidden_claims),
            "errors": list(self.errors),
        }


def _load_mapping(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    if path.suffix in {".yaml", ".yml"}:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    else:
        raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be an object")
    return {str(key): value for key, value in raw.items()}


def _heldout_semantics(paths: Sequence[Path]) -> dict[str, int]:
    counts = {"task_utility": 0, "proxy": 0}
    for path in paths:
        payload = _load_mapping(path, "heldout evidence")
        tracks = payload.get("tracks")
        if not isinstance(tracks, Mapping):
            raise ValueError(f"heldout evidence lacks tracks: {path}")
        for track_payload in tracks.values():
            if not isinstance(track_payload, Mapping):
                continue
            blocks = track_payload.get("blocks", ())
            if not isinstance(blocks, list):
                raise ValueError(f"heldout blocks must be a list: {path}")
            for block in blocks:
                observable = block.get("economic_observable", {})
                semantic = str(observable.get("semantic", ""))
                if semantic in counts:
                    counts[semantic] += 1
    return counts


def build_market_semantic_alignment(
    *,
    snapshot_path: str | Path = DEFAULT_DEAL_SNAPSHOT,
    catalog_path: str | Path = DEFAULT_CATALOG,
    heldout_manifests: Sequence[str | Path] = DEFAULT_HELDOUT_MANIFESTS,
    direct_findings_path: str | Path = DEFAULT_DIRECT_FINDINGS,
    aggregate_findings_path: str | Path = DEFAULT_AGGREGATE_FINDINGS,
    ocean_audit_path: str | Path = DEFAULT_OCEAN_AUDIT,
) -> MarketSemanticAlignment:
    """Build a claim-support matrix over non-substitutable evidence semantics."""

    catalog = _load_mapping(Path(catalog_path), "market evidence catalog")
    if catalog.get("schema_version") != "1.0":
        raise ValueError("unsupported market evidence catalog schema")
    raw_layers = catalog.get("layers")
    if not isinstance(raw_layers, list):
        raise ValueError("market evidence layers must be a list")
    expected_ids = (
        "task_utility",
        "cross_domain_proxy",
        "data_market_listing_ask",
        "aggregate_acceptance_anchor",
        "reported_data_licensing_deal",
        "executed_settlement_candidate",
    )
    if tuple(str(row.get("layer_id", "")) for row in raw_layers) != expected_ids:
        raise ValueError("market evidence layer IDs or order do not match contract")

    deal = audit_data_deal_snapshot(snapshot_path)
    direct = _load_mapping(Path(direct_findings_path), "direct-market findings")
    aggregate = _load_mapping(
        Path(aggregate_findings_path), "aggregate-envelope findings"
    )
    ocean = _load_mapping(Path(ocean_audit_path), "settlement source audit")
    semantics = _heldout_semantics(tuple(Path(path) for path in heldout_manifests))
    errors: list[str] = list(deal.errors)
    if direct.get("realized_transactions") is True or direct.get(
        "claim_boundaries", {}
    ).get("realized_transactions") is True:
        errors.append("listing_support_mislabeled_as_transaction")
    if ocean.get("decision") != "not_eligible":
        errors.append("settlement_candidate_admission_changed_without_contract")

    units = {
        "task_utility": semantics["task_utility"],
        "cross_domain_proxy": semantics["proxy"],
        "data_market_listing_ask": int(direct.get("cohort_count", 0)),
        "aggregate_acceptance_anchor": int(aggregate.get("profile_count", 0)),
        "reported_data_licensing_deal": deal.row_count,
        "executed_settlement_candidate": int(
            ocean.get("qualification_pipeline", {}).get(
                "fully_qualified_settlements", 0
            )
        ),
    }
    admission = {
        "task_utility": "benchmark_evidence",
        "cross_domain_proxy": "proxy_calibration_only",
        "data_market_listing_ask": "exploratory_support_transfer",
        "aggregate_acceptance_anchor": "aggregate_sensitivity_only",
        "reported_data_licensing_deal": "landscape_and_disclosure_only",
        "executed_settlement_candidate": "release_ineligible_negative_evidence",
    }
    layers = tuple(
        EvidenceLayer(
            layer_id=str(row["layer_id"]),
            semantic=str(row["semantic"]),
            evidence_unit=str(row["evidence_unit"]),
            observed_units=units[str(row["layer_id"])],
            admission_status=admission[str(row["layer_id"])],
            allowed_claim=str(row["allowed_claim"]),
            forbidden_claim=str(row["forbidden_claim"]),
        )
        for row in raw_layers
    )

    raw_tracks = catalog.get("track_support")
    if not isinstance(raw_tracks, Mapping) or set(raw_tracks) != {
        "valuation",
        "procurement",
        "trading",
    }:
        raise ValueError("track support must cover exactly three benchmark tracks")
    track_support = tuple(
        TrackClaimSupport(track=track, **dict(raw_tracks[track]))
        for track in ("valuation", "procurement", "trading")
    )
    forbidden = catalog.get("forbidden_claims")
    if not isinstance(forbidden, list) or not forbidden:
        raise ValueError("forbidden claims must be a non-empty list")
    deal_payload = deal.as_dict()
    return MarketSemanticAlignment(
        valid=not errors,
        layers=layers,
        track_support=track_support,
        deal_evidence=deal_payload,
        forbidden_claims=tuple(str(value) for value in forbidden),
        private_type_observed_layer_count=sum(
            row.private_types_observed for row in layers
        ),
        mechanism_outcome_replayable_layer_count=sum(
            row.mechanism_outcome_replayable for row in layers
        ),
        errors=tuple(errors),
    )


def write_market_semantic_artifacts(
    output_dir: str | Path = DEFAULT_OUTPUT,
) -> tuple[Path, ...]:
    alignment = build_market_semantic_alignment()
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "market_semantic_alignment.json"
    layer_path = destination / "evidence_layers.csv"
    track_path = destination / "track_claim_support.csv"
    report_path = destination / "report.md"
    json_path.write_text(
        json.dumps(alignment.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    with layer_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(EvidenceLayer.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(row) for row in alignment.layers)
    with track_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=tuple(TrackClaimSupport.__dataclass_fields__)
        )
        writer.writeheader()
        writer.writerows(asdict(row) for row in alignment.track_support)
    deal = alignment.deal_evidence
    report_path.write_text(
        "\n".join(
            [
                "# Real-market semantic alignment",
                "",
                "The evidence layers are deliberately non-substitutable. No licensed record supplies latent private types or a replayable allocation/payment outcome.",
                "",
                f"- Evidence layers: {len(alignment.layers)}",
                f"- Licensed data-licensing deals: {deal['row_count']}",
                f"- Deals with reported amounts: {deal['reported_deal_amount_count']} (high confidence: {deal['high_confidence_reported_deal_amount_count']})",
                f"- Top-two buyer row share: {deal['top_two_buyer_share']:.3f}; rows are not treated as IID.",
                "- Private-type-observed layers: 0",
                "- Mechanism-outcome-replayable layers: 0",
                "",
                "The benchmark therefore uses real evidence to delimit support and stress semantics, not to fabricate transaction or reservation-value labels.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return json_path, layer_path, track_path, report_path


__all__ = [
    "DEFAULT_AGGREGATE_FINDINGS",
    "DEFAULT_CATALOG",
    "DEFAULT_DEAL_SNAPSHOT",
    "DEFAULT_DIRECT_FINDINGS",
    "DEFAULT_HELDOUT_MANIFESTS",
    "DEFAULT_OCEAN_AUDIT",
    "EvidenceLayer",
    "MarketSemanticAlignment",
    "TrackClaimSupport",
    "build_market_semantic_alignment",
    "write_market_semantic_artifacts",
]
