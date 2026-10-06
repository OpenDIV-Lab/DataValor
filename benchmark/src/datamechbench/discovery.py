"""Versioned, auditable discovery lenses over benchmark evidence."""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .expectations import ExpectationSpec, evaluate_expectations, load_expectations
from .leaderboard import SETTING_PRIMARY_METRICS, LeaderboardRow, summarize_leaderboard
from .models import BenchmarkResult
from .qualification import attach_constraint_ranks, summarize_constraint_profiles
from .robustness import AssumptionTransferRow, summarize_assumption_transfers
from .statistics import PairwiseComparison, paired_comparisons
from .structural_profiles import StructuralProfile, summarize_structural_profiles


@dataclass(frozen=True)
class DiscoveryFinding:
    finding_id: str
    category: str
    evidence_tier: str
    track: str
    setting: str
    family_a: str
    family_b: str
    metric: str
    direction: str
    effect_name: str
    effect_value: float
    secondary_effect_name: str
    secondary_effect_value: float | None
    case_count: int | None
    observation_count: int | None
    coverage_ratio: float | None
    statement: str
    interpretation: str
    limitations: str
    next_test: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _slug(*parts: str) -> str:
    return "-".join(
        filter(None, (re.sub(r"[^a-z0-9]+", "-", part.lower()).strip("-") for part in parts))
    )


def _oriented_mean(profile: StructuralProfile) -> float:
    return profile.mean_primary if profile.direction == "maximize" else -profile.mean_primary


def _response_finding(profile: StructuralProfile, label: str) -> DiscoveryFinding:
    response = "improves" if profile.oriented_slope > 0 else "degrades"
    return DiscoveryFinding(
        _slug("structural", profile.setting, label, profile.family_id),
        "structural_response",
        "design_descriptive",
        profile.track,
        profile.setting,
        profile.family_id,
        "",
        profile.primary_metric,
        profile.direction,
        "oriented_slope",
        profile.oriented_slope,
        "oriented_endpoint_change",
        profile.oriented_endpoint_change,
        profile.case_count,
        profile.observation_count,
        profile.coverage_ratio,
        f"{profile.family_id} has the {label} structural response in {profile.setting}: performance {response} along {profile.axis_name} (oriented slope {profile.oriented_slope:.4f}).",
        "The result separates response to market structure from the mechanism's average performance level.",
        "The slope is descriptive on the frozen design range; it is not a causal effect or a theorem outside the case bank.",
        "Add independently calibrated axis blocks and test whether the response sign and ordering replicate.",
    )


def structural_discoveries(
    profiles: Iterable[StructuralProfile],
    *,
    eligible_families: set[str] | frozenset[str] | None = None,
    minimum_cases: int = 10,
    minimum_slope_magnitude: float = 0.04,
    minimum_level_gap: float = 0.1,
    minimum_slope_gap: float = 0.1,
    minimum_worst_case_gap: float = 0.1,
) -> tuple[DiscoveryFinding, ...]:
    """Mine axis response extremes and level/response trade-offs."""

    groups: dict[str, list[StructuralProfile]] = defaultdict(list)
    for profile in profiles:
        if (
            profile.coverage_ratio == 1.0
            and profile.case_count >= minimum_cases
            and (eligible_families is None or profile.family_id in eligible_families)
        ):
            groups[profile.setting].append(profile)
    findings: list[DiscoveryFinding] = []
    for setting, rows in sorted(groups.items()):
        strongest = max(rows, key=lambda row: (row.oriented_slope, row.family_id))
        weakest = min(rows, key=lambda row: (row.oriented_slope, row.family_id))
        if strongest.oriented_slope >= minimum_slope_magnitude:
            findings.append(_response_finding(strongest, "strongest positive"))
        if weakest.oriented_slope <= -minimum_slope_magnitude and weakest != strongest:
            findings.append(_response_finding(weakest, "strongest negative"))

        def worst_case_gap(profile: StructuralProfile) -> float:
            oriented_worst = (
                profile.worst_case_primary
                if profile.direction == "maximize"
                else -profile.worst_case_primary
            )
            return _oriented_mean(profile) - oriented_worst

        fragile = max(rows, key=lambda row: (worst_case_gap(row), row.family_id))
        gap = worst_case_gap(fragile)
        if gap >= minimum_worst_case_gap:
            findings.append(
                DiscoveryFinding(
                    _slug("worst-case", setting, fragile.family_id),
                    "mean_worst_case_gap",
                    "design_descriptive",
                    fragile.track,
                    setting,
                    fragile.family_id,
                    "",
                    fragile.primary_metric,
                    fragile.direction,
                    "mean_to_worst_oriented_gap",
                    gap,
                    "worst_case_primary",
                    fragile.worst_case_primary,
                    fragile.case_count,
                    fragile.observation_count,
                    fragile.coverage_ratio,
                    f"{fragile.family_id} has the largest mean-to-worst-case gap in {setting}: {gap:.4f} in higher-is-better orientation.",
                    "A favorable average can conceal a mechanism-specific failure region in the structural case bank.",
                    "The selected worst case is exploratory and can be sensitive to the frozen axis range.",
                    "Characterize the worst-case block, then test whether the gap persists on held-out cases from the same regime.",
                )
            )

        candidates: list[tuple[float, StructuralProfile, StructuralProfile, float, float]] = []
        for high_level in rows:
            for responsive in rows:
                if high_level.family_id == responsive.family_id:
                    continue
                level_gap = _oriented_mean(high_level) - _oriented_mean(responsive)
                slope_gap = high_level.oriented_slope - responsive.oriented_slope
                if level_gap >= minimum_level_gap and slope_gap <= -minimum_slope_gap:
                    candidates.append(
                        (level_gap * abs(slope_gap), high_level, responsive, level_gap, slope_gap)
                    )
        if candidates:
            _, high_level, responsive, level_gap, slope_gap = max(
                candidates, key=lambda item: (item[0], item[1].family_id, item[2].family_id)
            )
            findings.append(
                DiscoveryFinding(
                    _slug("tradeoff", setting, high_level.family_id, responsive.family_id),
                    "level_response_tradeoff",
                    "hypothesis_generating",
                    high_level.track,
                    setting,
                    high_level.family_id,
                    responsive.family_id,
                    high_level.primary_metric,
                    high_level.direction,
                    "oriented_level_advantage",
                    level_gap,
                    "oriented_slope_gap",
                    slope_gap,
                    min(high_level.case_count, responsive.case_count),
                    min(high_level.observation_count, responsive.observation_count),
                    min(high_level.coverage_ratio, responsive.coverage_ratio),
                    f"{high_level.family_id} has a {level_gap:.4f} average-performance advantage over {responsive.family_id}, but a {abs(slope_gap):.4f} worse response slope in {setting}.",
                    "Average quality and structural responsiveness identify different mechanism strengths; one static rank cannot represent both.",
                    "This is a selected trade-off pattern, not a multiplicity-corrected pairwise claim.",
                    "Evaluate the pair on held-out axis blocks and test for a crossing or stable ordering of response curves.",
                )
            )
    return tuple(findings)


def constraint_discoveries(
    rows: Iterable[LeaderboardRow],
) -> tuple[DiscoveryFinding, ...]:
    """Find settings where the raw winner is removed by mechanism guardrails."""

    groups: dict[tuple[str, str], list[LeaderboardRow]] = defaultdict(list)
    for row in rows:
        if (
            row.mean is not None
            and row.coverage_ratio == 1.0
            and row.setting in SETTING_PRIMARY_METRICS
        ):
            groups[(row.track, row.setting)].append(row)
    findings = []
    qualified_statuses = {"pass", "not_required"}
    for (track, setting), setting_rows in sorted(groups.items()):
        raw_winners = [row for row in setting_rows if row.rank == 1]
        if not raw_winners or any(row.constraint_status in qualified_statuses for row in raw_winners):
            continue
        qualified = [row for row in setting_rows if row.constraint_qualified_rank == 1]
        if not qualified:
            continue
        raw = sorted(raw_winners, key=lambda row: row.family_id)[0]
        winner = sorted(qualified, key=lambda row: row.family_id)[0]
        rank_shift = float((winner.rank or 1) - 1)
        oriented_gap = float(raw.mean) - float(winner.mean)
        if raw.direction == "minimize":
            oriented_gap = -oriented_gap
        findings.append(
            DiscoveryFinding(
                _slug("constraint", setting, raw.family_id, winner.family_id),
                "constraint_displacement",
                "constraint_audit",
                track,
                setting,
                raw.family_id,
                winner.family_id,
                raw.primary_metric,
                raw.direction,
                "raw_to_constraint_qualified_rank",
                rank_shift,
                "raw_winner_oriented_performance_gap",
                oriented_gap,
                min(raw.case_count, winner.case_count),
                min(raw.observation_count, winner.observation_count),
                1.0,
                f"The raw winner {raw.family_id} is {raw.constraint_status}; applying required guardrails selects {winner.family_id} from raw rank {winner.rank} in {setting}.",
                "The best allocation or valuation score need not identify the best auditable mechanism.",
                "Constraint qualification audits implemented outcomes and sampled deviations; it is not a general truthfulness proof.",
                "Resolve missing guardrails or violations, then repeat the qualified comparison on independent cases.",
            )
        )
    return tuple(findings)


def paired_discoveries(
    comparisons: Iterable[PairwiseComparison],
    *,
    eligible_families: set[str] | frozenset[str] | None = None,
    minimum_cases: int = 10,
    maximum_per_setting: int = 1,
) -> tuple[DiscoveryFinding, ...]:
    """Promote only multiplicity-corrected paired differences."""

    groups: dict[str, list[PairwiseComparison]] = defaultdict(list)
    for row in comparisons:
        if (
            row.common_case_count >= minimum_cases
            and row.conclusion in {"a_better", "b_better"}
            and row.adjusted_p_value is not None
            and row.adjusted_p_value < 0.05
            and (row.ci95_low > 0 or row.ci95_high < 0)
            and (
                eligible_families is None
                or (
                    row.family_a in eligible_families
                    and row.family_b in eligible_families
                )
            )
        ):
            groups[row.setting].append(row)
    findings = []
    for setting, rows in sorted(groups.items()):
        selected = sorted(rows, key=lambda row: (-abs(row.mean_delta), row.family_a, row.family_b))[
            :maximum_per_setting
        ]
        for row in selected:
            a_wins = row.conclusion == "a_better"
            winner = row.family_a if a_wins else row.family_b
            loser = row.family_b if a_wins else row.family_a
            effect = abs(row.mean_delta)
            findings.append(
                DiscoveryFinding(
                    _slug("paired", setting, winner, loser),
                    "paired_advantage",
                    "paired_supported",
                    row.track,
                    setting,
                    winner,
                    loser,
                    row.metric,
                    row.direction,
                    "oriented_mean_delta",
                    effect,
                    "holm_adjusted_p_value",
                    row.adjusted_p_value,
                    row.common_case_count,
                    row.common_case_count,
                    None,
                    f"{winner} outperforms {loser} by an oriented common-case mean of {effect:.4f} in {setting} ({row.common_case_count} cases, Holm-adjusted p={row.adjusted_p_value:.4g}).",
                    "This is the strongest form of benchmark evidence reported by the discovery layer.",
                    "Significance is conditional on the frozen case cohort and does not establish practical or external-market superiority.",
                    "Replicate the comparison on a held-out case family and report the same oriented effect and interval.",
                )
            )
    return tuple(findings)


def assumption_transfer_discoveries(
    rows: Iterable[AssumptionTransferRow],
    *,
    minimum_effect: float = 0.02,
) -> tuple[DiscoveryFinding, ...]:
    """Find the largest qualified gain and loss for each declared transfer."""

    groups: dict[str, list[AssumptionTransferRow]] = defaultdict(list)
    qualified = {"pass", "not_required"}
    for row in rows:
        if (
            row.status == "matched"
            and row.oriented_delta is not None
            and row.source_coverage == 1.0
            and row.target_coverage == 1.0
            and row.source_constraint_status in qualified
            and row.target_constraint_status in qualified
        ):
            groups[row.transfer_id].append(row)
    findings = []
    for transfer_id, candidates in sorted(groups.items()):
        extremes = []
        loss = min(candidates, key=lambda row: (float(row.oriented_delta), row.family_id))
        gain = max(candidates, key=lambda row: (float(row.oriented_delta), row.family_id))
        if float(loss.oriented_delta) <= -minimum_effect:
            extremes.append(("largest loss", loss))
        if float(gain.oriented_delta) >= minimum_effect and gain != loss:
            extremes.append(("largest gain", gain))
        for label, row in extremes:
            delta = float(row.oriented_delta)
            findings.append(
                DiscoveryFinding(
                    _slug("transfer", transfer_id, label, row.family_id),
                    "assumption_transfer",
                    "design_descriptive",
                    row.track,
                    f"{row.source_setting}->{row.target_setting}",
                    row.family_id,
                    "",
                    row.primary_metric,
                    row.direction,
                    "oriented_transfer_delta",
                    delta,
                    "qualified_rank_change",
                    float(row.rank_change) if row.rank_change is not None else None,
                    None,
                    None,
                    1.0,
                    f"{row.family_id} shows the {label} under {transfer_id}: oriented performance changes by {delta:.4f} from {row.source_setting} to {row.target_setting}.",
                    "The same mechanism can respond differently when a declared market assumption changes.",
                    "Source and target case banks may differ in more than one latent property; the delta is descriptive, not a causal decomposition.",
                    "Construct matched or calibrated source/target cases that vary only the target assumption.",
                )
            )
    return tuple(findings)


def expectation_discoveries(
    results: Iterable[BenchmarkResult],
    *,
    specs: Iterable[ExpectationSpec] | None = None,
    minimum_cases: int = 5,
    minimum_failure_rate: float = 0.1,
) -> tuple[DiscoveryFinding, ...]:
    """Identify paper-claim checks that fail systematically on eligible runs."""

    materialized = tuple(results)
    selected_specs = tuple(specs) if specs is not None else load_expectations()
    findings = []
    for spec in selected_specs:
        matching = [
            row
            for row in materialized
            if row.metadata.get("method_family", row.method_id) == spec.family_id
            and row.metadata.get("benchmark_setting") == spec.setting
        ]
        if not matching or spec.claim_kind not in {"theorem", "paper_experiment"}:
            continue
        methods = {row.method_id: str(row.metadata.get("implementation_kind", "native")) for row in matching}
        priority = {"native": 0, "external_adapter": 1}
        canonical = min(methods, key=lambda method: (priority.get(methods[method], 2), method))
        eligible = []
        for row in matching:
            if row.method_id != canonical:
                continue
            context = {"assumptions": row.metadata.get("case_assumptions", ())}
            evaluations = evaluate_expectations(row, context, (spec,))
            if evaluations and evaluations[0].status in {"met", "not_met"}:
                eligible.append((row, evaluations[0].status))
        cases = {row.case_id for row, _ in eligible}
        if len(cases) < minimum_cases or not eligible:
            continue
        failed = sum(status == "not_met" for _, status in eligible)
        rate = failed / len(eligible)
        if rate < minimum_failure_rate:
            continue
        track = eligible[0][0].track
        findings.append(
            DiscoveryFinding(
                _slug("claim", spec.expectation_id),
                "claim_boundary",
                "claim_diagnostic",
                track,
                spec.setting,
                spec.family_id,
                "",
                spec.metric_id,
                "descriptive",
                "not_met_rate",
                rate,
                "not_met_observations",
                float(failed),
                len(cases),
                len(eligible),
                None,
                f"{spec.family_id} misses expectation {spec.expectation_id} on {failed}/{len(eligible)} eligible observations across {len(cases)} cases ({rate:.1%}).",
                "The discrepancy localizes a boundary between the paper claim, the benchmark implementation, and the evaluated setting.",
                "A not-met annotation may reflect implementation fidelity, finite randomization, numerical tolerance, or violated latent assumptions; it does not refute the theorem.",
                f"Reproduce {spec.claim_location} with an exact or official implementation and isolate the first failing case.",
            )
        )
    return tuple(findings)


def discover_findings(
    results: Iterable[BenchmarkResult],
    *,
    leaderboard_rows: Iterable[LeaderboardRow] | None = None,
    comparisons: Iterable[PairwiseComparison] | None = None,
    transfers: Iterable[AssumptionTransferRow] | None = None,
    structural_profiles: Iterable[StructuralProfile] | None = None,
) -> tuple[DiscoveryFinding, ...]:
    """Run all versioned discovery lenses without producing a composite rank."""

    materialized = tuple(results)
    settings = sorted(
        {
            str(row.metadata["benchmark_setting"])
            for row in materialized
            if row.metadata.get("benchmark_setting")
        }
    )
    if leaderboard_rows is None:
        base_rows = tuple(
            row
            for setting in settings
            for row in summarize_leaderboard(
                materialized, include_pilots=False, setting=setting, view="all"
            )
        )
        leaderboard_rows = attach_constraint_ranks(
            base_rows, summarize_constraint_profiles(materialized)
        )
    if comparisons is None:
        comparisons = tuple(
            comparison
            for setting in settings
            for comparison in paired_comparisons(materialized, setting, view="all")
        )
    if transfers is None:
        transfers = summarize_assumption_transfers(materialized)
    if structural_profiles is None:
        structural_profiles = summarize_structural_profiles(materialized)
    paper_families = {
        str(row.metadata.get("method_family", row.method_id))
        for row in materialized
        if row.metadata.get("provenance_kind")
        in {"paper_exact", "official_adapter", "paper_variant", "project_implementation"}
    }
    findings = (
        *structural_discoveries(
            structural_profiles, eligible_families=paper_families
        ),
        *constraint_discoveries(leaderboard_rows),
        *paired_discoveries(comparisons, eligible_families=paper_families),
        *assumption_transfer_discoveries(transfers),
        *expectation_discoveries(materialized),
    )
    return tuple(sorted(findings, key=lambda row: (row.category, row.setting, row.finding_id)))


def write_discovery_artifacts(
    results: Iterable[BenchmarkResult],
    output_dir: str | Path,
    *,
    leaderboard_rows: Iterable[LeaderboardRow] | None = None,
    comparisons: Iterable[PairwiseComparison] | None = None,
    transfers: Iterable[AssumptionTransferRow] | None = None,
) -> tuple[Path, Path]:
    """Write a machine-readable finding table and an interpretation report."""

    materialized = tuple(results)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    findings = discover_findings(
        materialized,
        leaderboard_rows=leaderboard_rows,
        comparisons=comparisons,
        transfers=transfers,
    )
    csv_path = destination / "discovery_findings.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(DiscoveryFinding.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(row.to_dict() for row in findings)

    report_path = destination / "discovery_report.md"
    lines = [
        "# DataMechBench Discovery Screening Appendix",
        "",
        "This is a high-recall screening layer, not a list of independent scientific conclusions. Its cards nominate signals for cross-evidence analysis; the main research findings are developed in `deep_dive_report.md`.",
        "",
        "The report applies versioned deterministic evidence lenses rather than inventing a second leaderboard. The lenses were specified after inspection of the v0.3 results, so the report is exploratory and every finding remains conditional on the frozen benchmark case bank.",
        "",
        "Evidence tiers: `paired_supported` requires a common-case bootstrap interval and Holm-adjusted Wilcoxon result but is not externally confirmed; `constraint_audit` records an observed qualification change; `design_descriptive` summarizes a declared structural or assumption axis; `claim_diagnostic` flags a paper-claim boundary; `hypothesis_generating` must be retested on held-out cases.",
        "",
        "No cross-track composite score is computed, and an absent finding is not evidence that a mechanism has no failure mode.",
        "",
        f"Total findings: {len(findings)}.",
        "",
    ]
    category_titles = {
        "paired_advantage": "Multiplicity-corrected paired differences",
        "constraint_displacement": "Performance–constraint reversals",
        "structural_response": "Structural response extremes",
        "level_response_tradeoff": "Performance-level versus response trade-offs",
        "mean_worst_case_gap": "Mean versus worst-case fragility",
        "assumption_transfer": "Assumption-transfer gains and losses",
        "claim_boundary": "Paper-claim boundaries",
    }
    for category, title in category_titles.items():
        selected = [row for row in findings if row.category == category]
        if not selected:
            continue
        lines.extend([f"## {title}", ""])
        for row in selected:
            support = []
            if row.case_count is not None:
                support.append(f"cases={row.case_count}")
            if row.coverage_ratio is not None:
                support.append(f"coverage={row.coverage_ratio:.0%}")
            support.append(f"tier={row.evidence_tier}")
            lines.extend(
                [
                    f"### {row.finding_id}",
                    "",
                    row.statement,
                    "",
                    f"- Evidence: {', '.join(support)}.",
                    f"- Interpretation: {row.interpretation}",
                    f"- Limitation: {row.limitations}",
                    f"- Next test: {row.next_test}",
                    "",
                ]
            )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, report_path


__all__ = [
    "DiscoveryFinding",
    "assumption_transfer_discoveries",
    "constraint_discoveries",
    "discover_findings",
    "expectation_discoveries",
    "paired_discoveries",
    "structural_discoveries",
    "write_discovery_artifacts",
]
