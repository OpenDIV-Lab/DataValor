#!/usr/bin/env python3
"""Build a non-pooled v1/v2 replication report from frozen contrasts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from datamechbench.replication import analyze_replication_wave

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK = ROOT / "benchmark"
DEFAULT_V1 = BENCHMARK / "outputs" / "kdd_heldout_confirmatory" / "confirmatory_contrasts.json"
DEFAULT_V2 = BENCHMARK / "outputs" / "kdd_heldout_replication_v2" / "confirmatory_contrasts.json"
DEFAULT_V1_EVIDENCE = BENCHMARK / "evidence" / "kdd_heldout_confirmatory_v1.json"
DEFAULT_V2_EVIDENCE = BENCHMARK / "evidence" / "kdd_heldout_replication_v2.json"
DEFAULT_V2_CONFIG = BENCHMARK / "configs" / "kdd_heldout_replication_v2.yaml"
DEFAULT_V2_PROTOCOL = BENCHMARK / "evidence" / "kdd_heldout_replication_protocol_v1.json"
DEFAULT_OUTPUT = BENCHMARK / "outputs" / "kdd_heldout_replication_v2"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-contrasts", type=Path, default=DEFAULT_V1)
    parser.add_argument("--v2-contrasts", type=Path, default=DEFAULT_V2)
    parser.add_argument("--v1-evidence", type=Path, default=DEFAULT_V1_EVIDENCE)
    parser.add_argument("--v2-evidence", type=Path, default=DEFAULT_V2_EVIDENCE)
    parser.add_argument("--v2-config", type=Path, default=DEFAULT_V2_CONFIG)
    parser.add_argument("--v2-protocol", type=Path, default=DEFAULT_V2_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {
        "path": resolved.relative_to(ROOT).as_posix(),
        "sha256": _sha256(resolved),
    }


def _atomic_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def _atomic_json(path: Path, payload: Any) -> Path:
    return _atomic_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_block_csv(path: Path, rows: tuple[Any, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("wave", "contrast_id", "track", "block_id", "effect"),
        )
        writer.writeheader()
        writer.writerows(asdict(row) for row in rows)
    os.replace(temporary, path)
    return path


def _markdown(comparisons: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# KDD held-out v2 replication report",
        "",
        "The v2 wave is a separately frozen replication cohort. Its blocks, confidence intervals, and decisions are not pooled with v1, and v1 verdicts are not rewritten.",
        "",
        f"- Frozen contrasts: {summary['contrast_count']}",
        f"- v2 confirmed: {summary['v2_confirmed_count']}",
        f"- v2 boundary: {summary['v2_boundary_count']}",
        f"- Direction categories: `{json.dumps(summary['direction_counts'], sort_keys=True)}`",
        "",
        "| Contrast | Track | v1 effect / decision | v2 effect / decision | Direction | CI relation | Replication verdict |",
        "|---|---|---:|---:|---|---|---|",
    ]
    for row in comparisons:
        lines.append(
            "| {contrast_id} | {track} | {v1_effect:.6g} / {v1_decision} | "
            "{v2_effect:.6g} / {v2_decision} | {direction_category} | "
            "{interval_relation} | {replication_verdict} |".format(**row)
        )
    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "A same-sign result is descriptive directional consistency, not a pooled significance claim. A sign disagreement or attenuation identifies source heterogeneity. With two v2 blocks, all inferential claims remain deliberately conservative.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    v1_rows = json.loads(args.v1_contrasts.read_text(encoding="utf-8"))
    v2_rows = json.loads(args.v2_contrasts.read_text(encoding="utf-8"))
    report = analyze_replication_wave(v1_rows, v2_rows, minimum_v2_blocks=2)
    if report.errors:
        raise RuntimeError("replication audit failed: " + ", ".join(report.errors))

    args.output.mkdir(parents=True, exist_ok=True)
    comparison_rows = [asdict(row) for row in report.comparisons]
    comparison_path = _atomic_json(
        args.output / "replication_comparisons.json", comparison_rows
    )
    block_path = _write_block_csv(
        args.output / "replication_block_effects.csv", report.block_effects
    )
    direction_counts = Counter(row.direction_category for row in report.comparisons)
    verdict_counts = Counter(row.replication_verdict for row in report.comparisons)
    interval_counts = Counter(row.interval_relation for row in report.comparisons)
    summary = {
        "schema_version": "1.0",
        "report_kind": "separate_heldout_replication",
        "replication_wave": "v2",
        "pooled_inference": False,
        "contrast_count": len(report.comparisons),
        "block_effect_row_count": len(report.block_effects),
        "v1_confirmed_count": sum(row.v1_decision == "confirmed" for row in report.comparisons),
        "v2_confirmed_count": sum(row.v2_decision == "confirmed" for row in report.comparisons),
        "v2_boundary_count": sum(row.v2_decision == "boundary" for row in report.comparisons),
        "direction_counts": dict(sorted(direction_counts.items())),
        "replication_verdict_counts": dict(sorted(verdict_counts.items())),
        "interval_relation_counts": dict(sorted(interval_counts.items())),
        "errors": [],
    }
    summary_path = _atomic_json(args.output / "replication_summary.json", summary)
    report_path = _atomic_text(
        args.output / "replication_report.md",
        _markdown(comparison_rows, summary),
    )
    manifest = {
        "schema_version": "1.0",
        "manifest_kind": "heldout_replication_report",
        "replication_wave": "v2",
        "pooled_inference": False,
        "inputs": {
            "v1_contrasts": _artifact(args.v1_contrasts),
            "v2_contrasts": _artifact(args.v2_contrasts),
            "v1_evidence": _artifact(args.v1_evidence),
            "v2_evidence": _artifact(args.v2_evidence),
            "v2_config": _artifact(args.v2_config),
            "v2_protocol": _artifact(args.v2_protocol),
        },
        "outputs": {
            "comparisons": _artifact(comparison_path),
            "block_effects": _artifact(block_path),
            "summary": _artifact(summary_path),
            "report": _artifact(report_path),
        },
    }
    manifest_path = _atomic_json(args.output / "replication_manifest.json", manifest)
    print(
        json.dumps(
            {
                "contrast_count": len(report.comparisons),
                "block_effect_rows": len(report.block_effects),
                "manifest": manifest_path.relative_to(ROOT).as_posix(),
                "valid": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
