from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from datamechbench.bfm_vm_source_audit import (
    audit_bfm_vm_source_archive,
    write_bfm_vm_source_audit,
)

PINNED = "82f97be91f4404a9f943c5ebf3d60a272a76a13d"


def _archive(
    path: Path,
    *,
    source: str,
    commit: str = PINNED,
    license_text: str | None = None,
) -> Path:
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.comment = commit.encode("ascii")
        archive.writestr("BFM-SWM-main/Crowdsourcing/BFM-VM.h", source)
        if license_text is not None:
            archive.writestr("BFM-SWM-main/LICENSE", license_text)
    return path


def test_source_audit_flags_global_singleton_owner_omission_and_missing_license(
    tmp_path: Path,
) -> None:
    """Catches an audit that promotes structurally different code as paper parity."""

    source = """
// p_t = max(f(u))
double p_t = -1e18;
for (int u = 0; u < node_num; u++) { p_t = max(p_t, f_u(u)); }
vector<S_class> S_prev;
"""
    path = _archive(tmp_path / "source.zip", source=source)

    record = audit_bfm_vm_source_archive(path)

    assert record["source_identity"]["commit"] == PINNED
    assert record["source_identity"]["identity_verified"] is True
    assert record["license_audit"]["declared_license_files"] == []
    assert record["license_audit"]["redistribution_authorized"] is False
    assert record["paper_code_checks"] == {
        "best_singleton_restricted_to_active_set_R": False,
        "owner_locked_candidate_sequence_present": False,
    }
    assert record["conclusion"] == "source_audited_not_paper_parity"
    assert record["headline_eligibility"] is False


def test_source_audit_recognizes_structurally_aligned_fixture(tmp_path: Path) -> None:
    """Catches a parser that reports discrepancies regardless of source behavior."""

    source = """
// p_t = max(f(u))
double p_t = -1e18;
for (int u = 0; u < node_num; u++) {
  if (!is_active[u]) continue;
  p_t = max(p_t, f_u(u));
}
vector<int> owner(node_num, 0);
vector<S_class> S_prev;
"""
    path = _archive(
        tmp_path / "aligned.zip",
        source=source,
        license_text="MIT License",
    )

    record = audit_bfm_vm_source_archive(path)

    assert all(record["paper_code_checks"].values())
    assert record["license_audit"]["declared_license_files"] == ["LICENSE"]
    assert record["license_audit"]["redistribution_authorized"] is False
    assert record["conclusion"] == "structurally_aligned_source_audit"


def test_source_audit_rejects_wrong_archive_identity(tmp_path: Path) -> None:
    """Catches silent auditing of a mutable or unexpected repository revision."""

    path = _archive(
        tmp_path / "wrong.zip",
        source="vector<S_class> S_prev;",
        commit="0" * 40,
    )

    with pytest.raises(ValueError, match="commit mismatch"):
        audit_bfm_vm_source_archive(path)


def test_source_audit_writer_round_trips_canonical_json(tmp_path: Path) -> None:
    """Catches evidence writers that lose fields or emit unstable JSON."""

    source = """
// p_t = max(f(u))
for (int u = 0; u < node_num; u++) { if (!is_active[u]) continue; }
vector<int> owner(node_num, 0);
vector<S_class> S_prev;
"""
    archive = _archive(tmp_path / "source.zip", source=source)
    output = tmp_path / "audit.json"

    expected = write_bfm_vm_source_audit(archive, output)

    assert json.loads(output.read_text(encoding="utf-8")) == expected
    assert output.read_text(encoding="utf-8").endswith("\n")
