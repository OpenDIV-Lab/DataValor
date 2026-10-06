"""Fail-closed KDD Datasets & Benchmarks submission-readiness audit."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

from .case_bank import audit_case_bank_manifests
from .external_validation import audit_external_implementation_records
from .finite_incentives import (
    ALLOWED_CONCLUSIONS,
    verify_finite_incentive_artifacts,
)
from .heldout_evidence import audit_heldout_manifests
from .models import BenchmarkResult
from .paper_artifacts import FIGURES, TABLES, verify_paper_artifact_manifest
from .provenance import ProvenanceCatalog, load_provenance
from .public_release import verify_release_candidate
from .replication import audit_replication_protocol
from .reproduction import (
    audit_clean_room_records,
    load_reproduction_manifest,
    verify_reproduction_manifest,
)
from .risk_cards import verify_mechanism_risk_artifacts

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET = PACKAGE_ROOT / "catalog" / "kdd_submission.yaml"
FLAGSHIP_TRACKS = ("valuation", "procurement", "trading")
REFERENCE_GRADE_KINDS = frozenset({"paper_exact", "official_adapter"})
PARITY_STATUSES = frozenset({"verified", "local_property_only", "missing"})


@dataclass(frozen=True)
class FlagshipTarget:
    track: str
    setting_id: str
    structural_axis: str
    method_ids: tuple[str, ...]


@dataclass(frozen=True)
class ParityEvidence:
    status: str
    paths: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class KDDTarget:
    venue: str
    track: str
    paper_positioning: str
    flagships: Mapping[str, FlagshipTarget]
    parity_evidence: Mapping[str, ParityEvidence]
    method_family_ids: Mapping[str, str]
    requirements: Mapping[str, int | str]
    independent_case_manifests: tuple[str, ...]
    heldout_manifests: tuple[str, ...]
    replication_report_manifest: str
    artifact_manifest: str
    reference_outcome_audit: str
    finite_incentive_manifest: str
    paper_artifact_manifest: str
    mechanism_risk_manifest: str
    public_release_record: str
    post_release_evidence_manifest: str
    clean_room_operators_min: int
    clean_room_records: tuple[str, ...]
    external_validation_records_min: int
    external_validation_fixtures_min: int
    external_validation_methods_min: int
    external_validation_sources_min: int
    external_validation_repositories_min: int
    external_validation_tracks_min: int
    external_validation_records: tuple[str, ...]
    source_path: str
    market_semantic_alignment: str = ""
    qualification_analysis: str = ""

    @property
    def headline_method_ids(self) -> tuple[str, ...]:
        return tuple(
            method_id
            for track in FLAGSHIP_TRACKS
            for method_id in self.flagships[track].method_ids
        )

    @property
    def headline_family_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.method_family_ids[mid] for mid in self.headline_method_ids))


@dataclass(frozen=True)
class ReadinessGate:
    gate_id: str
    status: str
    summary: str
    evidence: Mapping[str, Any]
    next_action: str

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "not_evidenced"}:
            raise ValueError(f"unsupported gate status: {self.status}")


@dataclass(frozen=True)
class KDDReadinessReport:
    venue: str
    track: str
    ready: bool
    gates: tuple[ReadinessGate, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "track": self.track,
            "ready": self.ready,
            "gates": [asdict(gate) for gate in self.gates],
        }


@dataclass(frozen=True)
class PostReleaseEvidenceAudit:
    manifest: str
    present: bool
    release_id: str | None
    core_manifest_sha256: str | None
    public_release_record: str | None
    clean_room_records: tuple[str, ...]
    common_errors: tuple[str, ...]
    public_errors: tuple[str, ...]
    clean_room_errors: tuple[str, ...]


def _mapping(raw: Any, label: str) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return {str(key): value for key, value in raw.items()}


def _string_list(raw: Any, label: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not str(value).strip() for value in raw):
        raise ValueError(f"{label} must be a list of non-empty paths")
    return tuple(str(value) for value in raw)


def _string_path(raw: Any, label: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{label} must be a non-empty path")
    return value


def load_kdd_target(
    path: str | Path = DEFAULT_TARGET,
    *,
    provenance: ProvenanceCatalog | None = None,
) -> KDDTarget:
    """Load and validate the frozen KDD target against mechanism provenance."""

    source = Path(path)
    raw = _mapping(yaml.safe_load(source.read_text(encoding="utf-8")) or {}, "target catalog")
    if str(raw.get("schema_version", "")) != "1.0":
        raise ValueError("unsupported KDD target schema_version")
    target_raw = _mapping(raw.get("target"), "target")
    requirements = _mapping(raw.get("requirements"), "requirements")
    flagship_raw = _mapping(raw.get("flagships"), "flagships")
    if set(flagship_raw) != set(FLAGSHIP_TRACKS):
        raise ValueError(f"flagships must contain exactly {list(FLAGSHIP_TRACKS)}")

    catalog = provenance or load_provenance()
    flagships: dict[str, FlagshipTarget] = {}
    method_families: dict[str, str] = {}
    for track in FLAGSHIP_TRACKS:
        item = _mapping(flagship_raw[track], f"flagship {track}")
        method_ids = _string_list(item.get("method_ids"), f"flagship {track} method_ids")
        if len(method_ids) != len(set(method_ids)):
            raise ValueError(f"flagship {track} contains duplicate method IDs")
        for method_id in method_ids:
            if method_id not in catalog.mechanisms:
                raise ValueError(f"unknown headline method {method_id}")
            mechanism = catalog.mechanisms[method_id]
            if mechanism.track != track:
                raise ValueError(
                    f"headline method {method_id} belongs to {mechanism.track}, not {track}"
                )
            method_families[method_id] = mechanism.family_id
        flagships[track] = FlagshipTarget(
            track=track,
            setting_id=str(item.get("setting_id", "")).strip(),
            structural_axis=str(item.get("structural_axis", "")).strip(),
            method_ids=method_ids,
        )
        if not flagships[track].setting_id or not flagships[track].structural_axis:
            raise ValueError(f"flagship {track} requires setting_id and structural_axis")

    all_methods = tuple(mid for track in FLAGSHIP_TRACKS for mid in flagships[track].method_ids)
    families = {method_families[mid] for mid in all_methods}
    minimum = int(requirements.get("headline_family_count_min", 12))
    maximum = int(requirements.get("headline_family_count_max", 18))
    if not minimum <= len(families) <= maximum:
        raise ValueError(
            f"headline family count {len(families)} outside required range {minimum}..{maximum}"
        )

    parity_raw = _mapping(raw.get("parity_evidence"), "parity_evidence")
    missing_parity = sorted(set(all_methods) - set(parity_raw))
    if missing_parity:
        raise ValueError(f"headline methods missing parity records: {missing_parity}")
    parity: dict[str, ParityEvidence] = {}
    for method_id in all_methods:
        item = _mapping(parity_raw[method_id], f"parity evidence {method_id}")
        status = str(item.get("status", ""))
        if status not in PARITY_STATUSES:
            raise ValueError(f"unsupported parity status {status!r} for {method_id}")
        parity[method_id] = ParityEvidence(
            status=status,
            paths=_string_list(item.get("paths", []), f"parity paths {method_id}"),
            note=str(item.get("note", "")).strip(),
        )

    evidence = _mapping(raw.get("evidence"), "evidence")
    required_keys = (
        "reference_grade_per_track_min",
        "reference_sources_per_track_min",
        "independent_blocks_per_track_min",
        "generator_families_per_track_min",
        "heldout_blocks_per_track_min",
        "replication_blocks_per_track_min",
        "real_heldout_scope",
        "clean_room_operators_min",
        "external_validation_records_min",
        "external_validation_fixtures_min",
        "external_validation_methods_min",
        "external_validation_sources_min",
        "external_validation_repositories_min",
        "external_validation_tracks_min",
    )
    missing_requirements = [key for key in required_keys if key not in requirements]
    if missing_requirements:
        raise ValueError(f"KDD target missing requirements: {missing_requirements}")
    clean_room_records = _string_list(
        evidence.get("clean_room_records", []), "clean_room_records"
    )
    if clean_room_records:
        raise ValueError(
            "clean_room_records must remain empty in the frozen target; "
            "use post_release_evidence_manifest"
        )
    return KDDTarget(
        venue=str(target_raw.get("venue", "")).strip(),
        track=str(target_raw.get("track", "")).strip(),
        paper_positioning=str(target_raw.get("paper_positioning", "")).strip(),
        flagships=flagships,
        parity_evidence=parity,
        method_family_ids=method_families,
        requirements=requirements,
        independent_case_manifests=_string_list(
            evidence.get("independent_case_manifests", []), "independent_case_manifests"
        ),
        heldout_manifests=_string_list(
            evidence.get("heldout_manifests", []), "heldout_manifests"
        ),
        replication_report_manifest=_string_path(
            evidence.get("replication_report_manifest"),
            "replication_report_manifest",
        ),
        artifact_manifest=_string_path(
            evidence.get("artifact_manifest"), "artifact_manifest"
        ),
        reference_outcome_audit=_string_path(
            evidence.get("reference_outcome_audit"), "reference_outcome_audit"
        ),
        finite_incentive_manifest=_string_path(
            evidence.get("finite_incentive_manifest"), "finite_incentive_manifest"
        ),
        paper_artifact_manifest=_string_path(
            evidence.get("paper_artifact_manifest"), "paper_artifact_manifest"
        ),
        mechanism_risk_manifest=_string_path(
            evidence.get("mechanism_risk_manifest"), "mechanism_risk_manifest"
        ),
        public_release_record=_string_path(
            evidence.get("public_release_record"), "public_release_record"
        ),
        post_release_evidence_manifest=_string_path(
            evidence.get("post_release_evidence_manifest"),
            "post_release_evidence_manifest",
        ),
        clean_room_operators_min=int(requirements["clean_room_operators_min"]),
        clean_room_records=clean_room_records,
        external_validation_records_min=int(
            requirements["external_validation_records_min"]
        ),
        external_validation_fixtures_min=int(
            requirements["external_validation_fixtures_min"]
        ),
        external_validation_methods_min=int(
            requirements["external_validation_methods_min"]
        ),
        external_validation_sources_min=int(
            requirements["external_validation_sources_min"]
        ),
        external_validation_repositories_min=int(
            requirements["external_validation_repositories_min"]
        ),
        external_validation_tracks_min=int(
            requirements["external_validation_tracks_min"]
        ),
        external_validation_records=_string_list(
            evidence.get("external_validation_records", []),
            "external_validation_records",
        ),
        source_path=str(source),
        market_semantic_alignment=str(
            evidence.get("market_semantic_alignment", "")
        ).strip(),
        qualification_analysis=str(
            evidence.get("qualification_analysis", "")
        ).strip(),
    )


def _resolve(path: str, repository_root: Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else repository_root / candidate


_SHA256 = re.compile(r"[0-9a-f]{64}")


def _post_release_binding(
    raw: Any,
    repository_root: Path,
    *,
    label: str,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    errors: list[str] = []
    if not isinstance(raw, Mapping):
        return None, None, (f"invalid_binding:{label}",)
    path = str(raw.get("path", "")).strip()
    declared_sha256 = str(raw.get("sha256", "")).strip()
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or "\\" in path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        errors.append(f"path_escapes_repository_root:{path or '<missing>'}")
        return None, None, tuple(errors)
    if candidate.as_posix() != path:
        errors.append(f"noncanonical_path:{path}")
        return None, None, tuple(errors)
    root = repository_root.resolve()
    unresolved = root.joinpath(*candidate.parts)
    resolved = unresolved.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append(f"path_escapes_repository_root:{path}")
        return None, None, tuple(errors)
    if not _SHA256.fullmatch(declared_sha256):
        errors.append(f"invalid_sha256:{path}")
    if unresolved.is_symlink() or not resolved.is_file() or resolved.is_symlink():
        errors.append(f"missing_or_unsafe_file:{path}")
        return path, None, tuple(errors)
    observed_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if declared_sha256 != observed_sha256:
        errors.append(f"hash_mismatch:{path}")
    return path, observed_sha256, tuple(errors)


def audit_post_release_evidence(
    manifest_path: str | Path,
    repository_root: str | Path,
    *,
    expected_release_id: str,
    expected_core_manifest_path: str,
) -> PostReleaseEvidenceAudit:
    """Audit mutable external evidence without adding it to the core hash domain."""

    path = Path(manifest_path)
    root = Path(repository_root)
    if not path.is_absolute():
        path = root / path
    if path.is_symlink():
        return PostReleaseEvidenceAudit(
            manifest=str(path),
            present=True,
            release_id=None,
            core_manifest_sha256=None,
            public_release_record=None,
            clean_room_records=(),
            common_errors=("unsafe_post_release_manifest",),
            public_errors=(),
            clean_room_errors=(),
        )
    if not path.is_file():
        return PostReleaseEvidenceAudit(
            manifest=str(path),
            present=False,
            release_id=None,
            core_manifest_sha256=None,
            public_release_record=None,
            clean_room_records=(),
            common_errors=(),
            public_errors=(),
            clean_room_errors=(),
        )

    common_errors: list[str] = []
    public_errors: list[str] = []
    clean_errors: list[str] = []
    release_id: str | None = None
    core_sha256: str | None = None
    public_record: str | None = None
    clean_records: list[str] = []
    try:
        raw = _mapping(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {},
            "post-release evidence manifest",
        )
        if raw.get("schema_version") != "1.0":
            common_errors.append("unsupported_schema_version")
        if raw.get("manifest_kind") != "kdd_post_release_evidence":
            common_errors.append("wrong_manifest_kind")
        release_id = str(raw.get("release_id", "")).strip()
        if release_id != expected_release_id:
            common_errors.append(
                f"release_id_mismatch:expected={expected_release_id}:observed={release_id}"
            )

        core_path, core_sha256, core_errors = _post_release_binding(
            raw.get("core_manifest"), root, label="core_manifest"
        )
        common_errors.extend(core_errors)
        if any(error.startswith("hash_mismatch:") for error in core_errors):
            common_errors.append("core_manifest_hash_mismatch")
        if core_path != expected_core_manifest_path:
            common_errors.append(
                "core_manifest_path_mismatch:"
                f"expected={expected_core_manifest_path}:observed={core_path}"
            )

        public_path, _, binding_errors = _post_release_binding(
            raw.get("public_release_record"), root, label="public_release_record"
        )
        public_errors.extend(binding_errors)
        if public_path is not None and public_path == core_path:
            public_errors.append(f"duplicate_path:{public_path}")
        if not binding_errors:
            public_record = public_path

        clean_raw = raw.get("clean_room_records", [])
        if not isinstance(clean_raw, list):
            clean_errors.append("clean_room_records_not_list")
            clean_raw = []
        seen = {
            binding_path
            for binding_path in (core_path, public_path)
            if binding_path is not None
        }
        for index, item in enumerate(clean_raw):
            record_path, _, record_errors = _post_release_binding(
                item, root, label=f"clean_room_records[{index}]"
            )
            if record_path is not None and record_path in seen:
                clean_errors.append(f"duplicate_path:{record_path}")
            elif record_path is not None:
                seen.add(record_path)
            clean_errors.extend(record_errors)
            if record_path is not None and not record_errors:
                clean_records.append(record_path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        common_errors.append(f"invalid_post_release_manifest:{exc}")

    if common_errors:
        public_record = None
        clean_records = []
    return PostReleaseEvidenceAudit(
        manifest=str(path),
        present=True,
        release_id=release_id,
        core_manifest_sha256=core_sha256,
        public_release_record=public_record,
        clean_room_records=tuple(clean_records),
        common_errors=tuple(dict.fromkeys(common_errors)),
        public_errors=tuple(dict.fromkeys(public_errors)),
        clean_room_errors=tuple(dict.fromkeys(clean_errors)),
    )


def _read_json_records(paths: tuple[str, ...], repository_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw_path in paths:
        path = _resolve(raw_path, repository_root)
        if not path.is_file():
            errors.append(f"missing:{raw_path}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"invalid:{raw_path}:{exc.__class__.__name__}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"invalid:{raw_path}:not_object")
            continue
        payload = {str(key): value for key, value in payload.items()}
        payload["_path"] = raw_path
        records.append(payload)
    return records, errors


def _gate(
    gate_id: str,
    status: str,
    summary: str,
    evidence: Mapping[str, Any],
    next_action: str,
) -> ReadinessGate:
    return ReadinessGate(gate_id, status, summary, dict(evidence), next_action)


_DOI = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\Z")
_CITATION_PLACEHOLDER = re.compile(
    r"<[^>]*>|\b(?:anonymous|insert|placeholder|tbd|todo)\b", re.IGNORECASE
)


def audit_public_release_evidence(
    record_path: str | Path,
    repository_root: str | Path,
    *,
    expected_release_id: str,
) -> dict[str, Any]:
    """Audit a local candidate and require real external publication identifiers."""

    path = Path(record_path)
    root = Path(repository_root)
    errors: list[str] = []
    missing: list[str] = []
    candidate_valid = False
    entry_count = 0
    release_id: str | None = None
    artifact_license: str | None = None
    license_file: str | None = None
    license_sha256: str | None = None
    archive_url: str | None = None
    archive_sha256: str | None = None
    citation_title: str | None = None
    citation_creators: list[str] = []
    citation_publication_date: str | None = None
    try:
        raw = _mapping(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {},
            "public release record",
        )
        if str(raw.get("schema_version", "")) != "1.0":
            errors.append("unsupported_schema_version")
        release_id = str(raw.get("release_id", "")).strip()
        if release_id != expected_release_id:
            errors.append(
                f"release_id_mismatch:expected={expected_release_id}:observed={release_id}"
            )
        artifact_license = str(raw.get("artifact_license", "")).strip()
        if artifact_license != "Apache-2.0":
            errors.append(
                "artifact_license_mismatch:expected=Apache-2.0:observed="
                + artifact_license
            )
        raw_license_file = raw.get("license_file")
        if not isinstance(raw_license_file, Mapping):
            errors.append("missing_license_file_binding")
        else:
            license_file = str(raw_license_file.get("path", "")).strip()
            declared_license_sha256 = str(
                raw_license_file.get("sha256", "")
            ).strip()
            if license_file != "LICENSE":
                errors.append(
                    f"license_file_mismatch:expected=LICENSE:observed={license_file}"
                )
            else:
                license_path = root / license_file
                if not license_path.is_file() or license_path.is_symlink():
                    errors.append(f"missing_license_file:{license_file}")
                else:
                    license_sha256 = hashlib.sha256(
                        license_path.read_bytes()
                    ).hexdigest()
                    if declared_license_sha256 != license_sha256:
                        errors.append(f"license_sha256_mismatch:{license_file}")
        if raw.get("artifact_badge_pledge") is not True:
            errors.append("artifact_badge_pledge_not_true")

        candidate = _mapping(raw.get("candidate"), "candidate")
        sidecar_path = _resolve(
            _string_path(candidate.get("manifest"), "candidate manifest"), root
        )
        archive_path = _resolve(
            _string_path(candidate.get("archive"), "candidate archive"), root
        )
        verification = verify_release_candidate(sidecar_path, root)
        entry_count = int(verification.get("entry_count", 0))
        errors.extend(
            f"candidate:{error}" for error in verification.get("errors", ())
        )
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        archive_sha256 = str(sidecar["archive"]["sha256"])
        declared_archive = sidecar_path.parent / str(sidecar["archive"]["path"])
        if declared_archive.resolve() != archive_path.resolve():
            errors.append("candidate_archive_path_mismatch")
        if sidecar.get("release_id") != release_id:
            errors.append("candidate_release_id_mismatch")
        candidate_valid = verification.get("valid") is True and not any(
            error.startswith("candidate") for error in errors
        )

        publication = _mapping(raw.get("publication"), "publication")
        fields = (
            "public_repository_url",
            "archive_url",
            "archive_doi",
        )
        values = {
            field: str(publication.get(field) or "").strip() for field in fields
        }
        archive_url = values["archive_url"] or None
        missing.extend(field for field, value in values.items() if not value)
        for field in ("public_repository_url", "archive_url"):
            value = values[field]
            if value and not re.fullmatch(r"https?://[^\s]+", value):
                errors.append(f"malformed_{field}")
        if values["archive_doi"] and not _DOI.fullmatch(values["archive_doi"]):
            errors.append("malformed_archive_doi")

        citation = _mapping(raw.get("citation"), "citation")
        citation_title = str(citation.get("title") or "").strip() or None
        if not citation_title:
            errors.append("missing_citation_title")
        elif _CITATION_PLACEHOLDER.search(citation_title):
            errors.append("placeholder_citation_title")

        description = str(citation.get("description") or "").strip()
        if not description:
            errors.append("missing_citation_description")
        elif _CITATION_PLACEHOLDER.search(description):
            errors.append("placeholder_citation_description")

        citation_version = str(citation.get("version") or "").strip()
        if citation_version != release_id:
            errors.append(
                "citation_version_mismatch:"
                f"expected={release_id}:observed={citation_version}"
            )
        resource_type = str(citation.get("resource_type") or "").strip()
        if resource_type != "software":
            errors.append(
                "citation_resource_type_mismatch:"
                f"expected=software:observed={resource_type}"
            )
        citation_license = str(citation.get("license") or "").strip()
        if citation_license != artifact_license:
            errors.append(
                "citation_license_mismatch:"
                f"expected={artifact_license}:observed={citation_license}"
            )

        keywords = citation.get("keywords")
        if (
            not isinstance(keywords, list)
            or not keywords
            or any(not isinstance(keyword, str) or not keyword.strip() for keyword in keywords)
        ):
            errors.append("invalid_citation_keywords")
        elif len({keyword.strip().casefold() for keyword in keywords}) != len(keywords):
            errors.append("duplicate_citation_keywords")

        creators = citation.get("creators")
        if creators in (None, []):
            missing.append("citation.creators")
        elif not isinstance(creators, list):
            errors.append("invalid_citation_creators")
        else:
            for index, creator in enumerate(creators):
                if not isinstance(creator, Mapping):
                    errors.append(f"invalid_citation_creator:{index}")
                    continue
                name = str(creator.get("name") or "").strip()
                if not name:
                    errors.append(f"missing_citation_creator_name:{index}")
                elif _CITATION_PLACEHOLDER.search(name):
                    errors.append(f"placeholder_citation_creator:{index}")
                else:
                    citation_creators.append(name)

        raw_publication_date = citation.get("publication_date")
        citation_publication_date = (
            str(raw_publication_date).strip() if raw_publication_date else None
        )
        if not citation_publication_date:
            missing.append("citation.publication_date")
        else:
            try:
                date.fromisoformat(citation_publication_date)
            except ValueError:
                errors.append("malformed_citation_publication_date")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, yaml.YAMLError) as exc:
        errors.append(f"invalid_public_release_record:{exc}")

    status = "fail" if errors else ("not_evidenced" if missing else "pass")
    return {
        "status": status,
        "record": str(path),
        "release_id": release_id,
        "candidate_valid": candidate_valid,
        "entry_count": entry_count,
        "artifact_license": artifact_license,
        "license_file": license_file,
        "license_sha256": license_sha256,
        "archive_url": archive_url,
        "archive_sha256": archive_sha256,
        "citation_title": citation_title,
        "citation_creators": citation_creators,
        "citation_publication_date": citation_publication_date,
        "missing_external_fields": sorted(missing),
        "errors": errors,
    }


_PROHIBITED_EMPIRICAL_LANGUAGE = re.compile(r"\b(truthful|dsic|bic|proof)\b", re.IGNORECASE)


def audit_finite_incentive_evidence(
    manifest_path: str | Path,
    expected_method_ids: set[str],
) -> dict[str, Any]:
    """Validate both the hash envelope and claim semantics of an incentive audit."""

    path = Path(manifest_path)
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    try:
        verification = verify_finite_incentive_artifacts(path)
        errors.extend(verification["errors"])
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("claim_strength") != "empirical_finite_domain_audit":
            errors.append("invalid_claim_strength")
        result_entries = [
            item for item in manifest.get("artifacts", ())
            if Path(str(item.get("path", ""))).name == "audit_results.json"
        ]
        if len(result_entries) != 1:
            errors.append("missing_unique_audit_results_json")
        else:
            result_path = (path.parent / str(result_entries[0]["path"])).resolve()
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if result.get("claim_strength") != "empirical_finite_domain_audit":
                errors.append("result_invalid_claim_strength")
            records = [dict(item) for item in result.get("methods", ())]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_finite_incentive_manifest:{exc}")
    observed_ids = {str(record.get("method_id", "")) for record in records}
    missing = sorted(expected_method_ids - observed_ids)
    extra = sorted(observed_ids - expected_method_ids)
    if missing:
        errors.append("missing_methods:" + ",".join(missing))
    if extra:
        errors.append("unexpected_methods:" + ",".join(extra))
    for record in records:
        method_id = str(record.get("method_id", "<missing>"))
        conclusion = str(record.get("conclusion", ""))
        if conclusion not in ALLOWED_CONCLUSIONS:
            errors.append(f"invalid_conclusion:{method_id}")
        if _PROHIBITED_EMPIRICAL_LANGUAGE.search(conclusion):
            errors.append(f"prohibited_conclusion_language:{method_id}")
        if not record.get("type_domain_complete") or not record.get("report_domain_complete"):
            errors.append(f"incomplete_declared_domain:{method_id}")
        if record.get("deviation_evaluation_count") != record.get(
            "expected_deviation_evaluation_count"
        ):
            errors.append(f"incomplete_deviation_count:{method_id}")
        if record.get("tie_free_deviation_evaluation_count") != record.get(
            "expected_tie_free_deviation_evaluation_count"
        ):
            errors.append(f"incomplete_tie_free_count:{method_id}")
        if record.get("stochastic") and record.get("random_support_complete") is not False:
            errors.append(f"random_support_overclaim:{method_id}")
        if not str(record.get("expectation", "")).strip():
            errors.append(f"missing_source_expectation:{method_id}")
        if not record.get("reference_keys") or not str(record.get("source", "")).strip():
            errors.append(f"missing_source_reference:{method_id}")
        if int(record.get("profitable_deviation_count", 0)) > 0 and not record.get(
            "worst_witness"
        ):
            errors.append(f"missing_counterexample_witness:{method_id}")
    counterexamples = sorted(
        str(record["method_id"])
        for record in records
        if int(record.get("profitable_deviation_count", 0)) > 0
    )
    return {
        "passed": not errors,
        "manifest": str(path),
        "covered_method_count": len(observed_ids & expected_method_ids),
        "expected_method_count": len(expected_method_ids),
        "counterexample_methods": counterexamples,
        "errors": errors,
    }


def audit_paper_artifact_evidence(
    manifest_path: str | Path,
    expected_method_ids: set[str],
) -> dict[str, Any]:
    """Validate deterministic paper-output hashes, scope, tables, and SVG labels."""

    path = Path(manifest_path)
    errors: list[str] = []
    row_counts: dict[str, int] = {}
    output_count = 0
    try:
        verification = verify_paper_artifact_manifest(path)
        errors.extend(verification["errors"])
        manifest = json.loads(path.read_text(encoding="utf-8"))
        outputs = manifest.get("outputs", {})
        output_count = len(outputs)
        expected_outputs = set((*TABLES, *FIGURES))
        observed_outputs = set(outputs)
        for missing in sorted(expected_outputs - observed_outputs):
            errors.append(f"missing_paper_output:{missing}")
        for extra in sorted(observed_outputs - expected_outputs):
            errors.append(f"unexpected_paper_output:{extra}")
        row_counts = {str(key): int(value) for key, value in manifest.get("row_counts", {}).items()}
        expected_rows = {
            "table_scope_fidelity.csv": len(expected_method_ids),
            "table_constraint_profiles.csv": len(expected_method_ids),
            "table_finite_incentives.csv": len(expected_method_ids) - 6,
            "table_confirmatory_contrasts.csv": 6,
            "table_replication_wave.csv": 6,
        }
        for name, expected in expected_rows.items():
            if row_counts.get(name) != expected:
                errors.append(
                    f"invalid_row_count:{name}:expected={expected}:observed={row_counts.get(name)}"
                )
            table_path = path.parent / name
            if table_path.is_file():
                with table_path.open(encoding="utf-8", newline="") as handle:
                    actual = len(list(csv.DictReader(handle)))
                if actual != expected:
                    errors.append(
                        f"actual_row_count:{name}:expected={expected}:observed={actual}"
                    )
        scope_path = path.parent / "table_scope_fidelity.csv"
        if scope_path.is_file():
            with scope_path.open(encoding="utf-8", newline="") as handle:
                scope_rows = list(csv.DictReader(handle))
            observed_methods = {str(row.get("method_id", "")) for row in scope_rows}
            if observed_methods != expected_method_ids:
                errors.append("scope_method_mismatch")
            for row in scope_rows:
                if row.get("parity_status") != "verified":
                    errors.append(f"scope_unverified:{row.get('method_id')}")
                if not row.get("reference_url") or not row.get("provenance_kind"):
                    errors.append(f"scope_missing_reference:{row.get('method_id')}")
        else:
            errors.append("missing_scope_table")
        for name in FIGURES:
            svg_path = path.parent / name
            if not svg_path.is_file():
                continue
            try:
                root = ET.parse(svg_path).getroot()
            except ET.ParseError:
                errors.append(f"invalid_svg:{name}")
                continue
            namespace = "{http://www.w3.org/2000/svg}"
            if root.attrib.get("width") != "960" or root.attrib.get("height") != "560":
                errors.append(f"invalid_svg_dimensions:{name}")
            if root.find(namespace + "title") is None:
                errors.append(f"missing_svg_title:{name}")
            if root.find(namespace + "desc") is None:
                errors.append(f"missing_svg_desc:{name}")
        for key, item in manifest.get("inputs", {}).items():
            if Path(str(item.get("path", ""))).is_absolute():
                errors.append(f"absolute_input_path:{key}")
        command = str(manifest.get("generation_command", ""))
        if "build_kdd_paper_artifacts.py" not in command:
            errors.append("missing_generation_command")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"invalid_paper_artifact_manifest:{exc}")
    return {
        "passed": not errors,
        "manifest": str(path),
        "output_count": output_count,
        "row_counts": row_counts,
        "errors": errors,
    }


def audit_replication_report_evidence(
    manifest_path: str | Path,
    repository_root: str | Path,
    target: KDDTarget,
) -> dict[str, Any]:
    """Verify the preregistered, source-disjoint v2 wave without pooling it with v1."""

    root = Path(repository_root).resolve()
    path = Path(manifest_path)
    errors: list[str] = []
    resolved: dict[str, Path] = {}
    summary: dict[str, Any] = {}

    def bind(label: str, item: Any) -> None:
        if not isinstance(item, Mapping):
            errors.append(f"missing_binding:{label}")
            return
        relative = Path(str(item.get("path", "")))
        if not str(relative) or relative.is_absolute():
            errors.append(f"unsafe_path:{label}")
            return
        try:
            candidate = (root / relative).resolve()
            candidate.relative_to(root)
        except ValueError:
            errors.append(f"unsafe_path:{label}")
            return
        if not candidate.is_file() or candidate.is_symlink():
            errors.append(f"missing_file:{label}")
            return
        observed = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if observed != item.get("sha256"):
            errors.append(f"sha256_mismatch:{label}")
            return
        resolved[label] = candidate

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if (
            manifest.get("schema_version") != "1.0"
            or manifest.get("manifest_kind") != "heldout_replication_report"
            or manifest.get("replication_wave") != "v2"
        ):
            errors.append("invalid_replication_manifest_schema")
        if manifest.get("pooled_inference") is not False:
            errors.append("replication_waves_must_not_be_pooled")
        inputs = _mapping(manifest.get("inputs"), "replication inputs")
        outputs = _mapping(manifest.get("outputs"), "replication outputs")
        expected_inputs = {
            "v1_contrasts", "v2_contrasts", "v1_evidence", "v2_evidence",
            "v2_config", "v2_protocol",
        }
        expected_outputs = {"comparisons", "block_effects", "summary", "report"}
        if set(inputs) != expected_inputs:
            errors.append("replication_input_set_mismatch")
        if set(outputs) != expected_outputs:
            errors.append("replication_output_set_mismatch")
        for label, item in inputs.items():
            bind(label, item)
        for label, item in outputs.items():
            bind(label, item)

        required = {"v2_config", "v2_protocol", "v1_evidence", "v2_evidence", "summary", "comparisons"}
        if required <= set(resolved):
            protocol = audit_replication_protocol(
                resolved["v2_config"],
                resolved["v2_protocol"],
                resolved["v1_evidence"],
                root,
            )
            errors.extend(f"protocol:{error}" for error in protocol.errors)
            block_counts = dict(protocol.block_counts)
            minimum = int(target.requirements["replication_blocks_per_track_min"])
            if any(block_counts.get(track, 0) < minimum for track in FLAGSHIP_TRACKS):
                errors.append("insufficient_replication_blocks")

            heldout = audit_heldout_manifests(
                (str(resolved["v2_evidence"]),),
                root,
                target.flagships,
                development_case_ids=set(),
                minimum_blocks_per_track=minimum,
                required_scope=str(target.requirements["real_heldout_scope"]),
            )
            errors.extend(f"heldout:{error}" for error in heldout.errors)
            if dict(heldout.block_counts) != block_counts:
                errors.append("replication_block_count_mismatch")

            summary = _mapping(
                json.loads(resolved["summary"].read_text(encoding="utf-8")),
                "replication summary",
            )
            comparisons = json.loads(resolved["comparisons"].read_text(encoding="utf-8"))
            if not isinstance(comparisons, list) or len(comparisons) != 6:
                errors.append("invalid_replication_comparisons")
            else:
                expected_ids = {
                    "V-BANZHAF-vs-SHAPLEY", "V-RVSV-vs-VSV",
                    "P-CGLR-vs-GPS", "P-JTDEOM-vs-GPS",
                    "T-MCAFEE-vs-TR", "T-SBBA-vs-TR",
                }
                if {str(row.get("contrast_id", "")) for row in comparisons} != expected_ids:
                    errors.append("replication_contrast_set_mismatch")
                if any(int(row.get("v2_blocks", 0)) < minimum for row in comparisons):
                    errors.append("replication_comparison_blocks_insufficient")
            if (
                summary.get("report_kind") != "separate_heldout_replication"
                or summary.get("replication_wave") != "v2"
                or summary.get("pooled_inference") is not False
                or summary.get("contrast_count") != 6
                or summary.get("errors") != []
            ):
                errors.append("invalid_replication_summary")
        else:
            block_counts = {track: 0 for track in FLAGSHIP_TRACKS}
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        errors.append(f"invalid_replication_evidence:{exc}")
        block_counts = {track: 0 for track in FLAGSHIP_TRACKS}

    return {
        "passed": not errors,
        "manifest": str(path),
        "blocks": block_counts,
        "contrast_count": int(summary.get("contrast_count", 0)),
        "v2_confirmed_count": int(summary.get("v2_confirmed_count", 0)),
        "v2_boundary_count": int(summary.get("v2_boundary_count", 0)),
        "pooled_inference": summary.get("pooled_inference"),
        "errors": errors,
    }


def audit_kdd_readiness(
    results: Iterable[BenchmarkResult],
    target: KDDTarget,
    *,
    provenance: ProvenanceCatalog | None = None,
    repository_root: str | Path,
) -> KDDReadinessReport:
    """Evaluate every required KDD gate without treating missing evidence as success."""

    rows = tuple(results)
    catalog = provenance or load_provenance()
    root = Path(repository_root)
    gates: list[ReadinessGate] = []

    benchmark_project = root / "benchmark/pyproject.toml"
    resource_module = root / "benchmark/src/datamechbench/resources.py"
    workflow_path = root / ".github/workflows/ci.yml"
    project_text = (
        benchmark_project.read_text(encoding="utf-8")
        if benchmark_project.is_file()
        else ""
    )
    workflow_text = (
        workflow_path.read_text(encoding="utf-8") if workflow_path.is_file() else ""
    )
    wheel_checks = {
        "declares_datavalor_dependency": '"datavalor>=0.1.0a0"' in project_text,
        "packages_runtime_catalog": '"share/datamechbench/catalog"' in project_text,
        "packages_submission_template": '"share/datamechbench/submission_template"' in project_text,
        "resource_locator_present": resource_module.is_file(),
        "fresh_install_ci_present": "wheel-smoke:" in workflow_text
        and "/tmp/datamech-install" in workflow_text,
    }
    gates.append(_gate(
        "wheel_installability_contract",
        "pass" if all(wheel_checks.values()) else "fail",
        "The benchmark wheel must declare its library dependency, carry runtime assets, and be imported outside the checkout in CI.",
        {"checks": wheel_checks},
        "Package catalogs/templates and add a clean target-install smoke test outside the repository.",
    ))

    submission_metadata = root / "benchmark/submission_template/submission.yaml"
    submission_results = root / "benchmark/submission_template/results.jsonl"
    submission_source = root / "benchmark/src/datamechbench/submission.py"
    try:
        submission_record = yaml.safe_load(
            submission_metadata.read_text(encoding="utf-8")
        )
        submission_rows = [
            json.loads(line)
            for line in submission_results.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        recomputation_checks = {
            "submission_schema_1_1": str(
                submission_record.get("submission_schema_version", "")
            ) == "1.1",
            "completed_rows_include_outcomes": bool(submission_rows)
            and all(
                row.get("status") != "completed" or isinstance(row.get("outcome"), dict)
                for row in submission_rows
            ),
            "evaluator_entrypoint_present": "evaluate-submission" in workflow_text,
            "submitted_metrics_demoted": submission_source.is_file()
            and "authoritative_metrics" in submission_source.read_text(encoding="utf-8")
            and "evaluator_recomputed" in submission_source.read_text(encoding="utf-8"),
        }
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as exc:
        recomputation_checks = {"contract_load_error": False, "error": str(exc)}
    gates.append(_gate(
        "trusted_metric_recomputation",
        "pass" if all(value is True for value in recomputation_checks.values()) else "fail",
        "Open submissions must provide raw outcomes and leaderboard metrics must be recomputed by the evaluator.",
        {"checks": recomputation_checks},
        "Require versioned raw outcomes and use evaluator-produced metrics as the only leaderboard authority.",
    ))

    reference_audit_path = _resolve(target.reference_outcome_audit, root)
    reference_evidence: dict[str, Any] = {"path": target.reference_outcome_audit}
    if not reference_audit_path.is_file():
        reference_status = "not_evidenced"
        reference_evidence["errors"] = ["missing_reference_outcome_audit"]
    else:
        reference_errors: list[str] = []
        try:
            receipt = _mapping(
                json.loads(reference_audit_path.read_text(encoding="utf-8")),
                "reference outcome audit",
            )
            if (
                receipt.get("schema_version") != "1.0"
                or receipt.get("report_kind")
                != "reference_outcome_metric_recomputation"
                or receipt.get("metric_authority")
                != "evaluator_recomputed_from_persisted_outcomes"
            ):
                reference_errors.append("invalid_reference_outcome_audit_schema")
            result_name = str(receipt.get("result_path", ""))
            result_path = reference_audit_path.parent / result_name
            declared_hash = str(receipt.get("result_sha256", ""))
            if (
                not result_name
                or Path(result_name).name != result_name
                or not result_path.is_file()
            ):
                reference_errors.append("missing_bound_reference_results")
            elif (
                not _SHA256.fullmatch(declared_hash)
                or hashlib.sha256(result_path.read_bytes()).hexdigest()
                != declared_hash
            ):
                reference_errors.append("reference_result_hash_mismatch")
            completed_rows = int(receipt.get("completed_rows", -1))
            if (
                receipt.get("passed") is not True
                or receipt.get("errors") != []
                or receipt.get("metric_mismatches") != []
                or int(receipt.get("outcome_rows", -2)) != completed_rows
                or int(receipt.get("auditable_rows", -3)) != completed_rows
                or completed_rows <= 0
            ):
                reference_errors.append("reference_outcome_recomputation_not_passed")
            track_rows = _mapping(receipt.get("track_rows"), "track_rows")
            if any(int(track_rows.get(track, 0)) <= 0 for track in FLAGSHIP_TRACKS):
                reference_errors.append("reference_outcome_track_coverage_incomplete")
            reference_evidence.update(
                {
                    "completed_rows": completed_rows,
                    "recomputed_metric_count": int(
                        receipt.get("recomputed_metric_count", 0)
                    ),
                    "execution_dependent_metric_ids": receipt.get(
                        "execution_dependent_metric_ids", []
                    ),
                    "track_rows": track_rows,
                    "errors": reference_errors,
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            reference_errors = [f"invalid_reference_outcome_audit:{exc}"]
            reference_evidence["errors"] = reference_errors
        reference_status = "fail" if reference_errors else "pass"
    gates.append(_gate(
        "reference_outcome_recomputation",
        reference_status,
        "Frozen reference metrics must be recomputable from persisted score/allocation/payment outcomes without rerunning mechanisms.",
        reference_evidence,
        "Regenerate schema-1.2 reference outcomes and bind an evaluator-side metric recomputation receipt.",
    ))

    retired_tokens = ("www2027", "www_scr", "www_web_markets", "www_game_builders")
    scope_roots = tuple(
        root / "benchmark" / name
        for name in ("configs", "evidence", "scripts", "src")
    )
    retired_paths = sorted(
        path.relative_to(root).as_posix()
        for scope_root in scope_roots
        if scope_root.exists()
        for path in scope_root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and any(token in path.as_posix().lower() for token in retired_tokens)
    )
    manifest_path = root / target.artifact_manifest
    manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else ""
    manifest_retired_tokens = [
        token for token in ("www2027", "scr_shapley", "scr_confirmatory")
        if token in manifest_text.lower()
    ]
    scope_evidence = {
        "retired_paths": retired_paths,
        "retired_manifest_tokens": manifest_retired_tokens,
    }
    gates.append(_gate(
        "kdd_release_scope_isolation",
        "pass" if not retired_paths and not manifest_retired_tokens else "fail",
        "The KDD benchmark artifact must exclude the retired WWW/SCR paper-study pipeline and its evidence.",
        scope_evidence,
        "Move paper-specific experiments outside the benchmark and refresh then independently verify the KDD manifest.",
    ))

    family_count = len(set(target.headline_family_ids))
    minimum = int(target.requirements["headline_family_count_min"])
    maximum = int(target.requirements["headline_family_count_max"])
    gates.append(_gate(
        "headline_family_count",
        "pass" if minimum <= family_count <= maximum else "fail",
        f"{family_count} unique headline families; required {minimum}..{maximum}",
        {"count": family_count, "minimum": minimum, "maximum": maximum},
        "Keep the main paper at 12--18 families; place wider coverage in the artifact.",
    ))

    completed = {
        (str(row.metadata.get("benchmark_setting", "")), row.method_id)
        for row in rows
        if row.status == "completed"
    }
    missing_by_track = {
        track: [
            method_id
            for method_id in flagship.method_ids
            if (flagship.setting_id, method_id) not in completed
        ]
        for track, flagship in target.flagships.items()
    }
    coverage_missing = {track: values for track, values in missing_by_track.items() if values}
    coverage_status = "not_evidenced" if not rows else ("fail" if coverage_missing else "pass")
    gates.append(_gate(
        "completed_flagship_coverage",
        coverage_status,
        "All headline methods need at least one completed run in their flagship setting.",
        {"missing_by_track": coverage_missing},
        "Run every missing headline method on the frozen flagship setting; do not count skips.",
    ))

    provenance_mismatches: list[dict[str, Any]] = []
    observed_headline_rows = 0
    for track, flagship in target.flagships.items():
        for method_id in flagship.method_ids:
            expected = catalog.mechanisms[method_id].provenance_kind
            observed = sorted({
                str(row.metadata.get("provenance_kind", "<missing>"))
                for row in rows
                if row.status == "completed"
                and row.method_id == method_id
                and row.metadata.get("benchmark_setting") == flagship.setting_id
            })
            observed_headline_rows += len(observed)
            if observed and observed != [expected]:
                provenance_mismatches.append({
                    "track": track,
                    "method_id": method_id,
                    "expected": expected,
                    "observed": observed,
                })
    alignment_status = "not_evidenced" if observed_headline_rows == 0 else (
        "fail" if provenance_mismatches else "pass"
    )
    gates.append(_gate(
        "result_provenance_alignment",
        alignment_status,
        "Completed headline rows must carry the same fidelity label as the frozen catalog.",
        {"mismatches": provenance_mismatches},
        "Rerun methods whose implementation/fidelity changed; rendering stale raw rows is insufficient.",
    ))

    reference_minimum = int(target.requirements["reference_grade_per_track_min"])
    reference_counts = {
        track: len({
            catalog.mechanisms[mid].family_id
            for mid in flagship.method_ids
            if catalog.mechanisms[mid].provenance_kind in REFERENCE_GRADE_KINDS
        })
        for track, flagship in target.flagships.items()
    }
    deficient = {
        track: count for track, count in reference_counts.items() if count < reference_minimum
    }
    gates.append(_gate(
        "reference_grade_per_track",
        "fail" if deficient else "pass",
        f"Each flagship track requires {reference_minimum} paper-exact/official families.",
        reference_counts,
        "Add or validate paper-exact/official procurement and trading implementations before headline use.",
    ))

    source_minimum = int(target.requirements["reference_sources_per_track_min"])
    reference_sources = {
        track: sorted({
            reference_key
            for method_id in flagship.method_ids
            if catalog.mechanisms[method_id].provenance_kind in REFERENCE_GRADE_KINDS
            for reference_key in catalog.mechanisms[method_id].reference_keys
        })
        for track, flagship in target.flagships.items()
    }
    source_evidence = {
        track: {"source_count": len(source_ids), "source_ids": source_ids}
        for track, source_ids in reference_sources.items()
    }
    source_deficient = {
        track: evidence["source_count"]
        for track, evidence in source_evidence.items()
        if evidence["source_count"] < source_minimum
    }
    gates.append(_gate(
        "reference_source_diversity",
        "fail" if source_deficient else "pass",
        f"Each flagship track requires reference-grade methods from at least {source_minimum} primary sources.",
        source_evidence,
        "Avoid satisfying the reference-family gate with multiple variants from only one paper.",
    ))

    parity_failures: dict[str, str] = {}
    for method_id, evidence in target.parity_evidence.items():
        if evidence.status != "verified":
            parity_failures[method_id] = evidence.status
            continue
        missing_paths = [
            path for path in evidence.paths if not _resolve(path, root).is_file()
        ]
        if not evidence.paths or missing_paths:
            parity_failures[method_id] = (
                "missing_paths:" + ",".join(missing_paths or ("<none>",))
            )
    gates.append(_gate(
        "parity_evidence",
        "fail" if parity_failures else "pass",
        "Every headline method needs explicit source/official-output parity evidence.",
        {"unverified": parity_failures, "verified_count": len(target.parity_evidence) - len(parity_failures)},
        "Implement paper-derived golden cases or official-output comparisons for every unverified method.",
    ))

    failed_rows = [row.run_id for row in rows if row.status == "failed"]
    gates.append(_gate(
        "no_failed_runs",
        "not_evidenced" if not rows else ("fail" if failed_rows else "pass"),
        "The audited result release must contain no failed runs.",
        {"failed_count": len(failed_rows), "examples": failed_rows[:20]},
        "Resolve failed runs or explicitly remove invalid cases before freezing the release.",
    ))

    block_minimum = int(target.requirements["independent_blocks_per_track_min"])
    generator_minimum = int(target.requirements["generator_families_per_track_min"])
    case_bank = audit_case_bank_manifests(
        target.independent_case_manifests, root, rows
    )
    block_counts = dict(case_bank.block_counts)
    generator_counts = dict(case_bank.generator_counts)
    block_deficient = [
        track for track in FLAGSHIP_TRACKS
        if block_counts[track] < block_minimum or generator_counts[track] < generator_minimum
    ]
    block_status = "not_evidenced" if not target.independent_case_manifests else (
        "fail" if case_bank.errors or block_deficient else "pass"
    )
    gates.append(_gate(
        "independent_case_blocks",
        block_status,
        "Independent blocks and generator families must be explicit, hash-bound, and backed by completed cases.",
        {
            "blocks": block_counts,
            "generator_families": generator_counts,
            "cohorts": {track: list(case_bank.cohorts[track]) for track in FLAGSHIP_TRACKS},
            "errors": list(case_bank.errors),
            "deficient_tracks": block_deficient,
        },
        (
            "Preserve the frozen development bank and add only newly frozen held-out blocks."
            if block_status == "pass"
            else "Create an explicit case-bank manifest using base datasets/markets as independent units, not seeds or parameter points."
        ),
    ))

    required_scope = str(target.requirements["real_heldout_scope"])
    heldout_audit = audit_heldout_manifests(
        target.heldout_manifests,
        root,
        target.flagships,
        development_case_ids={row.case_id for row in rows},
        minimum_blocks_per_track=int(target.requirements["heldout_blocks_per_track_min"]),
        required_scope=required_scope,
    )
    covered_tracks = set(heldout_audit.covered_tracks)
    missing_tracks = sorted(set(FLAGSHIP_TRACKS) - covered_tracks)
    heldout_status = "not_evidenced" if not target.heldout_manifests else (
        "fail" if heldout_audit.errors or missing_tracks else "pass"
    )
    gates.append(_gate(
        "real_heldout_evidence",
        heldout_status,
        f"Held-out manifests must use evidence_scope={required_scope!r}, cover all flagship tracks, and expose economic-observable semantics without treating proxies as direct market evidence.",
        {
            "covered_tracks": sorted(covered_tracks),
            "missing_tracks": missing_tracks,
            "blocks": dict(heldout_audit.block_counts),
            "economic_semantics": {
                track: dict(heldout_audit.economic_semantic_counts[track])
                for track in FLAGSHIP_TRACKS
            },
            "economic_claim_support": dict(
                heldout_audit.economic_claim_support_counts
            ),
            "unique_source_uris": dict(heldout_audit.unique_source_uri_counts),
            "licenses": dict(heldout_audit.license_counts),
            "errors": list(heldout_audit.errors),
        },
        "Run the frozen flagship protocol on real/open-data-backed held-out blocks for every track.",
    ))

    if target.market_semantic_alignment:
        semantic_path = _resolve(target.market_semantic_alignment, root)
        semantic_errors: list[str] = []
        semantic_evidence: dict[str, Any] = {
            "path": target.market_semantic_alignment,
            "errors": semantic_errors,
        }
        try:
            semantic = _mapping(
                json.loads(semantic_path.read_text(encoding="utf-8")),
                "market semantic alignment",
            )
            track_support = semantic.get("track_support")
            supported_tracks = {
                str(row.get("track", ""))
                for row in track_support
                if isinstance(row, Mapping)
            } if isinstance(track_support, list) else set()
            forbidden = {str(item) for item in semantic.get("forbidden_claims", [])}
            if (
                semantic.get("schema_version") != "1.0"
                or semantic.get("report_kind") != "real_market_semantic_alignment"
                or semantic.get("valid") is not True
                or semantic.get("errors") != []
            ):
                semantic_errors.append("invalid_market_semantic_alignment")
            if int(semantic.get("layer_count", 0)) < 6:
                semantic_errors.append("insufficient_semantic_layers")
            if supported_tracks != set(FLAGSHIP_TRACKS):
                semantic_errors.append("incomplete_semantic_track_coverage")
            if (
                int(semantic.get("private_type_observed_layer_count", -1)) != 0
                or int(semantic.get("mechanism_outcome_replayable_layer_count", -1))
                != 0
            ):
                semantic_errors.append("unsupported_private_type_or_replay_claim")
            required_forbidden = {
                "observed_seller_reservation_cost",
                "observed_buyer_value",
                "observed_data_market_mechanism_outcome",
            }
            if not required_forbidden.issubset(forbidden):
                semantic_errors.append("missing_forbidden_market_claims")
            semantic_evidence.update(
                {
                    "layer_count": semantic.get("layer_count"),
                    "supported_tracks": sorted(supported_tracks),
                    "private_type_observed_layer_count": semantic.get(
                        "private_type_observed_layer_count"
                    ),
                    "mechanism_outcome_replayable_layer_count": semantic.get(
                        "mechanism_outcome_replayable_layer_count"
                    ),
                    "forbidden_claims": sorted(forbidden),
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            semantic_errors.append(f"invalid_market_semantic_alignment:{exc}")
        gates.append(_gate(
            "market_semantic_alignment",
            "fail" if semantic_errors else "pass",
            "Real-market evidence layers must remain non-substitutable and must fail closed on unobserved private types or unreplayable transactions.",
            semantic_evidence,
            "Repair semantic layer coverage or remove unsupported private-type and transaction-outcome claims.",
        ))

    if target.qualification_analysis:
        qualification_path = _resolve(target.qualification_analysis, root)
        qualification_errors: list[str] = []
        qualification_evidence: dict[str, Any] = {
            "path": target.qualification_analysis,
            "errors": qualification_errors,
        }
        try:
            qualification = _mapping(
                json.loads(qualification_path.read_text(encoding="utf-8")),
                "qualification analysis",
            )
            source_path = _resolve(str(qualification.get("source_path", "")), root)
            declared_source_hash = str(qualification.get("source_sha256", ""))
            if (
                not source_path.is_file()
                or not _SHA256.fullmatch(declared_source_hash)
                or hashlib.sha256(source_path.read_bytes()).hexdigest()
                != declared_source_hash
            ):
                qualification_errors.append("qualification_source_binding_mismatch")
            method_count = int(qualification.get("headline_method_count", -1))
            status_total = sum(
                int(qualification.get(name, -1000))
                for name in (
                    "joint_pass_count",
                    "joint_fail_count",
                    "joint_not_auditable_count",
                )
            )
            if (
                qualification.get("schema_version") != "1.0"
                or qualification.get("analysis_role")
                != "diagnostic_not_official_rank"
                or method_count != len(target.flagships["trading"].method_ids)
                or status_total != method_count
            ):
                qualification_errors.append("invalid_qualification_decomposition")
            method_table = qualification_path.parent / "method_failure_decomposition.csv"
            frontier_table = qualification_path.parent / "minimum_relaxation_frontier.csv"
            if not method_table.is_file() or not frontier_table.is_file():
                qualification_errors.append("missing_qualification_tables")
            else:
                with method_table.open(encoding="utf-8", newline="") as handle:
                    method_rows = list(csv.DictReader(handle))
                if len(method_rows) != method_count or {
                    row.get("analysis_role") for row in method_rows
                } != {"diagnostic_not_official_rank"}:
                    qualification_errors.append("invalid_qualification_method_table")
            qualification_evidence.update(
                {
                    "headline_method_count": method_count,
                    "joint_pass_count": qualification.get("joint_pass_count"),
                    "one_requirement_near_miss_count": qualification.get(
                        "one_requirement_near_miss_count"
                    ),
                    "minimum_relaxation_path_count": qualification.get(
                        "minimum_relaxation_path_count"
                    ),
                    "analysis_role": qualification.get("analysis_role"),
                }
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            qualification_errors.append(f"invalid_qualification_analysis:{exc}")
        gates.append(_gate(
            "qualification_failure_decomposition",
            "fail" if qualification_errors else "pass",
            "Empty or reduced qualified sets must be explained by observed failures, evidence gaps, and minimum method-specific relaxation paths without creating a composite rank.",
            qualification_evidence,
            "Regenerate the source-bound failure decomposition and minimum-relaxation diagnostics.",
        ))

    replication_audit = audit_replication_report_evidence(
        _resolve(target.replication_report_manifest, root), root, target
    )
    gates.append(_gate(
        "independent_replication_wave",
        "pass" if replication_audit["passed"] else "fail",
        "A separately frozen source-disjoint wave must reproduce all six estimands without pooled inference or rewriting v1 decisions.",
        replication_audit,
        "Repair protocol, source-disjointness, hashes, block coverage, or separate-wave reporting before using replication claims.",
    ))

    incentive_ids = {
        method_id
        for track in ("procurement", "trading")
        for method_id in target.flagships[track].method_ids
    }
    incentive_audit = audit_finite_incentive_evidence(
        _resolve(target.finite_incentive_manifest, root), incentive_ids
    )
    gates.append(_gate(
        "finite_domain_incentive_audit",
        "pass" if incentive_audit["passed"] else "fail",
        "All procurement/trading headline mechanisms need complete, claim-safe finite-domain deviation evidence.",
        incentive_audit,
        "Repair incomplete domains, unsupported theorem language, source annotations, or missing counterexample witnesses.",
    ))

    paper_audit = audit_paper_artifact_evidence(
        _resolve(target.paper_artifact_manifest, root), set(target.headline_method_ids)
    )
    gates.append(_gate(
        "paper_artifact_contract",
        "pass" if paper_audit["passed"] else "fail",
        "Every main table and figure must be deterministic, hash-bound, scope-complete, and reviewer-readable.",
        paper_audit,
        "Rebuild the four tables and six figures from frozen evidence and repair any manifest or accessibility error.",
    ))

    risk_card_audit = verify_mechanism_risk_artifacts(
        _resolve(target.mechanism_risk_manifest, root),
        repository_root=root,
    )
    gates.append(_gate(
        "mechanism_risk_cards",
        "pass" if risk_card_audit["valid"] else "fail",
        "Every headline mechanism must expose role impacts, deployment boundaries, and auditable versus unknown risk dimensions without a composite score.",
        risk_card_audit,
        "Repair missing headline coverage, unsupported risk semantics, unbound evidence, or tampered derived artifacts.",
    ))

    artifact_errors: list[str] = []
    artifact_release_id = "<unavailable>"
    artifact_evidence: dict[str, Any] = {
        "manifest": target.artifact_manifest,
        "verified_artifacts": 0,
        "scientific_digest": None,
        "row_count": 0,
        "track_counts": {},
        "errors": artifact_errors,
    }
    try:
        reproduction_manifest = load_reproduction_manifest(
            _resolve(target.artifact_manifest, root), root
        )
        artifact_release_id = reproduction_manifest.release_id
        artifact_verification = verify_reproduction_manifest(
            reproduction_manifest, root
        )
        artifact_errors.extend(artifact_verification.errors)
        artifact_evidence.update({
            "verified_artifacts": artifact_verification.verified_artifacts,
            "scientific_digest": artifact_verification.scientific_digest,
            "row_count": artifact_verification.row_count,
            "track_counts": dict(artifact_verification.track_counts),
        })
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        artifact_errors.append(f"invalid_manifest:{exc}")
    gates.append(_gate(
        "artifact_reproduction_contract",
        "fail" if artifact_errors else "pass",
        "The frozen core release must be byte-bound and scientifically reproducible without timing noise.",
        artifact_evidence,
        "Repair missing/hash-mismatched release artifacts before requesting external reproduction.",
    ))

    post_release_audit = audit_post_release_evidence(
        target.post_release_evidence_manifest,
        root,
        expected_release_id=artifact_release_id,
        expected_core_manifest_path=target.artifact_manifest,
    )
    post_common_errors = list(post_release_audit.common_errors)
    post_public_errors = list(post_release_audit.public_errors)
    post_clean_errors = list(post_release_audit.clean_room_errors)
    effective_public_record = target.public_release_record
    if (
        post_release_audit.present
        and not post_common_errors
        and not post_public_errors
        and post_release_audit.public_release_record is not None
    ):
        effective_public_record = post_release_audit.public_release_record

    public_release_audit = audit_public_release_evidence(
        _resolve(effective_public_record, root),
        root,
        expected_release_id=artifact_release_id,
    )
    overlay_public_errors = [
        *(f"post_release:{error}" for error in post_common_errors),
        *(f"post_release:{error}" for error in post_public_errors),
    ]
    public_release_audit["errors"].extend(overlay_public_errors)
    if overlay_public_errors:
        public_release_audit["status"] = "fail"
    public_release_audit["post_release_evidence"] = {
        "manifest": post_release_audit.manifest,
        "present": post_release_audit.present,
        "core_manifest_sha256": post_release_audit.core_manifest_sha256,
        "public_release_record": post_release_audit.public_release_record,
        "errors": overlay_public_errors,
    }
    gates.append(_gate(
        "public_release_artifact",
        str(public_release_audit["status"]),
        "The verified Python release must have real public URLs and an archival DOI.",
        public_release_audit,
        "Publish the frozen Python candidate, then record its resolvable URLs and DOI.",
    ))

    external_audit = audit_external_implementation_records(
        target.external_validation_records,
        root,
        expected_method_ids=set(target.headline_method_ids),
        minimum_records=target.external_validation_records_min,
        minimum_fixtures=target.external_validation_fixtures_min,
        minimum_methods=target.external_validation_methods_min,
        minimum_sources=target.external_validation_sources_min,
        minimum_repositories=target.external_validation_repositories_min,
        minimum_tracks=target.external_validation_tracks_min,
    )
    gates.append(_gate(
        "external_implementation_validation",
        str(external_audit["status"]),
        "Distinct headline methods must agree with byte-bound external implementations across multiple source paths, repositories, and benchmark tracks.",
        external_audit,
        "Add unique pinned upstream comparisons until the method, source-path, repository, and track diversity thresholds all pass.",
    ))

    clean_errors: list[str] = [
        *(f"post_release:{error}" for error in post_common_errors),
        *(f"post_release:{error}" for error in post_clean_errors),
    ]
    operator_ids: tuple[str, ...] = ()
    reproduced_tracks: tuple[str, ...] = ()
    valid_records = 0
    effective_clean_room_records = (
        post_release_audit.clean_room_records
        if post_release_audit.present and not post_common_errors
        else target.clean_room_records
    )
    if effective_clean_room_records and public_release_audit["status"] != "pass":
        clean_errors.append("public_release_not_verified")
    elif effective_clean_room_records:
        try:
            clean_audit = audit_clean_room_records(
                effective_clean_room_records,
                root,
                target.artifact_manifest,
                required_operators=target.clean_room_operators_min,
                expected_archive_url=str(
                    public_release_audit.get("archive_url") or ""
                ),
                expected_archive_sha256=str(
                    public_release_audit.get("archive_sha256") or ""
                ),
            )
            clean_errors.extend(clean_audit.errors)
            operator_ids = clean_audit.operator_ids
            reproduced_tracks = clean_audit.covered_tracks
            valid_records = clean_audit.valid_records
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            clean_errors.append(f"invalid_clean_room_evidence:{exc}")
    clean_status = (
        "fail"
        if clean_errors
        else ("not_evidenced" if not effective_clean_room_records else "pass")
    )
    clean_missing = sorted(set(FLAGSHIP_TRACKS) - set(reproduced_tracks))
    gates.append(_gate(
        "clean_room_reproduction",
        clean_status,
        "Distinct independent operators must reproduce the exact core release in isolated environments.",
        {
            "required_operators": target.clean_room_operators_min,
            "observed_operators": len(operator_ids),
            "operator_ids": list(operator_ids),
            "valid_records": valid_records,
            "covered_tracks": list(reproduced_tracks),
            "missing_tracks": clean_missing,
            "post_release_evidence": {
                "manifest": post_release_audit.manifest,
                "present": post_release_audit.present,
                "record_count": len(post_release_audit.clean_room_records),
            },
            "errors": clean_errors,
        },
        "Have two non-implementers run the release protocol and submit complete attestation records.",
    ))

    return KDDReadinessReport(
        venue=target.venue,
        track=target.track,
        ready=all(gate.status == "pass" for gate in gates),
        gates=tuple(gates),
    )


def write_kdd_readiness_report(
    report: KDDReadinessReport,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """Write deterministic machine-readable and reviewer-readable gate reports."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "kdd_readiness.json"
    markdown_path = destination / "kdd_readiness.md"
    json_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    verdict = "READY" if report.ready else "NOT READY"
    lines = [
        f"# {report.venue} {report.track} Readiness",
        "",
        f"**Verdict: {verdict}.** Missing evidence is never treated as passing.",
        "",
        "| Gate | Status | Summary |",
        "|---|---|---|",
    ]
    for gate in report.gates:
        lines.append(f"| `{gate.gate_id}` | **{gate.status}** | {gate.summary} |")
    lines.extend(["", "## Gate evidence", ""])
    for gate in report.gates:
        lines.extend([
            f"### {gate.gate_id}: {gate.status}",
            "",
            gate.summary,
            "",
            "```json",
            json.dumps(gate.evidence, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
            f"Next action: {gate.next_action}",
            "",
        ])
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return json_path, markdown_path


__all__ = [
    "DEFAULT_TARGET",
    "FlagshipTarget",
    "KDDReadinessReport",
    "KDDTarget",
    "ParityEvidence",
    "PostReleaseEvidenceAudit",
    "ReadinessGate",
    "audit_finite_incentive_evidence",
    "audit_external_implementation_records",
    "audit_kdd_readiness",
    "audit_paper_artifact_evidence",
    "audit_post_release_evidence",
    "audit_replication_report_evidence",
    "audit_public_release_evidence",
    "load_kdd_target",
    "write_kdd_readiness_report",
]
