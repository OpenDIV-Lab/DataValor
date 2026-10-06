"""Static, fail-closed audit of the BFM-VM author experiment source."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

PINNED_COMMIT = "82f97be91f4404a9f943c5ebf3d60a272a76a13d"
PINNED_HEADER_SHA256 = (
    "4b377288e5c817349602c6426644a3b9c5a07403284de3350daae5ee326bc61c"
)
SOURCE_REPOSITORY = "https://github.com/xue74193-dot/BFM-SWM"
PAPER_URL = "https://proceedings.mlr.press/v306/cui26b.html"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _license_files(names: list[str]) -> list[str]:
    candidates = []
    for name in names:
        base = Path(name).name.upper()
        if base.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")):
            candidates.append(Path(name).name)
    return sorted(set(candidates))


def _paper_code_checks(source: str) -> dict[str, bool]:
    singleton_start = source.find("p_t = max(f(u))")
    singleton_end = source.find("vector<S_class>", singleton_start)
    if singleton_start < 0 or singleton_end < 0:
        singleton_block = source
    else:
        singleton_block = source[singleton_start:singleton_end]
    scans_all_nodes = bool(
        re.search(
            r"for\s*\(\s*int\s+u\s*=\s*0\s*;\s*u\s*<\s*node_num",
            singleton_block,
        )
    )
    active_guard = bool(
        re.search(r"if\s*\(\s*!\s*is_active\s*\[\s*u\s*\]", singleton_block)
    )
    iterates_active_container = bool(
        re.search(r"for\s*\([^:]+:\s*R\s*\)", singleton_block)
    )
    owner_present = bool(re.search(r"\bowner\s*[\[(]", source))
    return {
        "best_singleton_restricted_to_active_set_R": (
            not scans_all_nodes or active_guard or iterates_active_container
        ),
        "owner_locked_candidate_sequence_present": owner_present,
    }


def audit_bfm_vm_source_archive(
    archive_path: str | Path,
    *,
    expected_commit: str = PINNED_COMMIT,
    expected_header_sha256: str | None = None,
) -> dict[str, Any]:
    """Audit one downloaded GitHub source archive without redistributing it."""

    source_path = Path(archive_path)
    if not source_path.is_file():
        raise ValueError(f"missing source archive: {source_path}")
    try:
        with ZipFile(source_path) as archive:
            try:
                commit = archive.comment.decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise ValueError("source archive comment is not ASCII") from exc
            if commit != expected_commit:
                raise ValueError(
                    f"commit mismatch: expected {expected_commit}, observed {commit or '<empty>'}"
                )
            names = archive.namelist()
            members = [name for name in names if name.endswith("/Crowdsourcing/BFM-VM.h")]
            if len(members) != 1:
                raise ValueError(
                    "expected exactly one Crowdsourcing/BFM-VM.h member"
                )
            member = members[0]
            header_bytes = archive.read(member)
            try:
                source = header_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("BFM-VM header is not UTF-8") from exc
            licenses = _license_files(names)
    except BadZipFile as exc:
        raise ValueError(f"invalid source archive: {exc}") from exc

    header_sha256 = _sha256_bytes(header_bytes)
    if expected_header_sha256 is not None and header_sha256 != expected_header_sha256:
        raise ValueError(
            "BFM-VM header hash mismatch: "
            f"expected {expected_header_sha256}, observed {header_sha256}"
        )
    checks = _paper_code_checks(source)
    discrepancies = [
        check_id for check_id, passed in checks.items() if not passed
    ]
    return {
        "schema_version": "1.0",
        "audit_kind": "external_author_source_static_audit",
        "method_id": "bfm_vm",
        "paper": {
            "title": (
                "Budget-Feasible Mechanisms for Submodular Welfare "
                "Maximization in Procurement Auctions"
            ),
            "venue": "ICML 2026",
            "algorithm_location": "Algorithm 2",
            "url": PAPER_URL,
        },
        "source_identity": {
            "repository_url": SOURCE_REPOSITORY,
            "commit": commit,
            "archive_sha256": _sha256_file(source_path),
            "header_member": member,
            "header_sha256": header_sha256,
            "identity_verified": True,
        },
        "license_audit": {
            "declared_license_files": licenses,
            "license_interpreted": False,
            "redistribution_authorized": False,
            "reason": (
                "No repository license file was found; source is not vendored."
                if not licenses
                else "License-file presence is recorded but not interpreted by this audit."
            ),
        },
        "paper_code_checks": checks,
        "observed_discrepancies": discrepancies,
        "conclusion": (
            "source_audited_not_paper_parity"
            if discrepancies
            else "structurally_aligned_source_audit"
        ),
        "headline_eligibility": False,
        "evidence_scope": (
            "Static source-structure audit only. It does not establish output parity, "
            "truthfulness, approximation guarantees, or redistribution rights."
        ),
    }


def write_bfm_vm_source_audit(
    archive_path: str | Path,
    output_path: str | Path,
    *,
    expected_commit: str = PINNED_COMMIT,
    expected_header_sha256: str | None = None,
) -> dict[str, Any]:
    record = audit_bfm_vm_source_archive(
        archive_path,
        expected_commit=expected_commit,
        expected_header_sha256=expected_header_sha256,
    )
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


__all__ = [
    "PAPER_URL",
    "PINNED_COMMIT",
    "PINNED_HEADER_SHA256",
    "SOURCE_REPOSITORY",
    "audit_bfm_vm_source_archive",
    "write_bfm_vm_source_audit",
]
