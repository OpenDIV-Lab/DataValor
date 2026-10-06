"""Writers for constraint, statistical, and assumption-transfer evidence."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .deep_dives import write_deep_dive_artifacts
from .discovery import write_discovery_artifacts
from .leaderboard import LeaderboardRow, summarize_leaderboard
from .models import BenchmarkResult
from .qualification import (
    ConstraintProfile,
    attach_constraint_ranks,
    summarize_constraint_profiles,
)
from .robustness import AssumptionTransferRow, summarize_assumption_transfers
from .statistics import PairwiseComparison, paired_comparisons
from .structural_profiles import write_structural_profile_artifacts


def _write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    fields: Sequence[str],
) -> Path:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _profile_row(
    profile: ConstraintProfile,
    leaderboard: LeaderboardRow | None,
) -> dict[str, object]:
    return {
        "track": profile.track,
        "setting": profile.setting,
        "family_id": profile.family_id,
        "method_id": profile.method_id,
        "primary_metric": leaderboard.primary_metric if leaderboard else "",
        "mean": leaderboard.mean if leaderboard else None,
        "coverage_ratio": leaderboard.coverage_ratio if leaderboard else None,
        "qualified_rank": leaderboard.qualified_rank if leaderboard else None,
        "constraint_status": profile.constraint_status,
        "constraint_qualified_rank": leaderboard.constraint_qualified_rank if leaderboard else None,
        "passed_rules": ";".join(profile.passed_rules),
        "failed_rules": ";".join(profile.failed_rules),
        "missing_rules": ";".join(profile.missing_rules),
        "rule_values": json.dumps(profile.rule_values, sort_keys=True),
    }


def write_evidence_artifacts(
    results: Iterable[BenchmarkResult],
    output_dir: str | Path,
    *,
    config_path: str | Path | None = None,
) -> tuple[Path, ...]:
    """Write independent evidence layers without creating an aggregate score."""

    del config_path  # Reserved for the release orchestrator; evidence is result-derived.
    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    settings = sorted(
        {
            str(row.metadata["benchmark_setting"])
            for row in materialized
            if row.metadata.get("benchmark_setting")
        }
    )
    profiles = summarize_constraint_profiles(materialized)
    leaderboard_rows = tuple(
        row
        for setting in settings
        for row in summarize_leaderboard(
            materialized,
            include_pilots=False,
            setting=setting,
            view="all",
        )
    )
    qualified_rows = attach_constraint_ranks(leaderboard_rows, profiles)
    constraint_path = _write_csv(
        destination / "constraint_leaderboard.csv",
        [row.to_dict() for row in qualified_rows],
        tuple(LeaderboardRow.__dataclass_fields__),
    )

    row_index = {(row.track, row.setting, row.family_id): row for row in qualified_rows}
    profile_fields = (
        "track", "setting", "family_id", "method_id", "primary_metric", "mean",
        "coverage_ratio", "qualified_rank", "constraint_status",
        "constraint_qualified_rank", "passed_rules", "failed_rules",
        "missing_rules", "rule_values",
    )
    profile_path = _write_csv(
        destination / "mechanism_profiles.csv",
        [
            _profile_row(profile, row_index.get((profile.track, profile.setting, profile.family_id)))
            for profile in profiles
        ],
        profile_fields,
    )

    comparisons = tuple(
        comparison
        for setting in settings
        for comparison in paired_comparisons(materialized, setting, view="all")
    )
    comparison_path = _write_csv(
        destination / "pairwise_comparisons.csv",
        [row.to_dict() for row in comparisons],
        tuple(PairwiseComparison.__dataclass_fields__),
    )

    statistical_path = destination / "statistical_summary.md"
    conclusions = Counter(row.conclusion for row in comparisons)
    statistical_path.write_text(
        "\n".join(
            [
                "# Paired Statistical Evidence",
                "",
                "Comparisons use common cases after seed averaging. Positive deltas always favor family A; Wilcoxon p-values are Holm-adjusted within each setting and accompanied by a deterministic paired-bootstrap 95% interval.",
                "",
                f"- Pairwise comparisons: {len(comparisons)}",
                f"- A significantly better: {conclusions['a_better']}",
                f"- B significantly better: {conclusions['b_better']}",
                f"- Indistinguishable under this protocol: {conclusions['indistinguishable']}",
                f"- Insufficient non-tied cases: {conclusions['insufficient_cases']}",
                "",
                "`indistinguishable` is not evidence of equivalence; it means this case cohort and decision rule did not establish a difference.",
                "",
                "Truthfulness metrics are sampled deviation diagnostics, not exhaustive proofs over every possible report.",
                "A `not_auditable` constraint status means at least one required guardrail was unavailable; it must not be read as a pass.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    transfers = summarize_assumption_transfers(materialized)
    transfer_path = _write_csv(
        destination / "assumption_transfer.csv",
        [row.to_dict() for row in transfers],
        tuple(AssumptionTransferRow.__dataclass_fields__),
    )
    discovery_paths = write_discovery_artifacts(
        materialized,
        destination,
        leaderboard_rows=qualified_rows,
        comparisons=comparisons,
        transfers=transfers,
    )
    deep_dive_paths = write_deep_dive_artifacts(
        materialized,
        destination,
        leaderboard_rows=qualified_rows,
    )
    structural_paths = write_structural_profile_artifacts(materialized, destination)
    return (
        constraint_path,
        profile_path,
        comparison_path,
        statistical_path,
        transfer_path,
        *discovery_paths,
        *deep_dive_paths,
        *structural_paths,
    )


__all__ = ["write_evidence_artifacts"]
