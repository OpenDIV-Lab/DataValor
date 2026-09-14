"""Joint feedback analysis across valuation, pricing, and realized outcomes."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

from datavalor.core import ComponentSpec

from .interfaces import Analyzer
from .models import AnalysisResult


def _finite_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _summarize(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    accepted = [row for row in rows if row["accepted"]]
    quote_ratios = [row["quoted_price"] / row["estimated_value"] for row in rows]
    realization_ratios = [
        row["realized_value"] / row["estimated_value"] for row in rows
    ]
    return {
        "observations": len(rows),
        "accepted": len(accepted),
        "acceptance_rate": len(accepted) / len(rows) if rows else None,
        "mean_quote_to_value_ratio": _mean(quote_ratios),
        "mean_realization_to_value_ratio": _mean(realization_ratios),
        "estimated_value_bias": _mean(
            [row["estimated_value"] - row["realized_value"] for row in rows]
        ),
        "quoted_revenue": sum(row["quoted_price"] for row in accepted),
        "realized_value": sum(row["realized_value"] for row in rows),
    }


class ValueRealizationAnalyzer(Analyzer):
    """Audit conversion from estimated value to quote and realized outcome."""

    @property
    def spec(self):
        return ComponentSpec(
            "value_realization",
            "1.0.0",
            "toolkit",
            "analyzer",
            capabilities=("value_chain", "grouped_feedback", "conversion"),
        )

    def analyze(self, request, context):
        observations = request.options.get("observations", ())
        valid = []
        invalid = []
        for index, item in enumerate(observations):
            if not isinstance(item, Mapping):
                invalid.append(index)
                continue
            estimated = _finite_number(item.get("estimated_value"))
            quoted = _finite_number(item.get("quoted_price"))
            realized = _finite_number(item.get("realized_value"))
            if (
                estimated is None
                or quoted is None
                or realized is None
                or estimated <= 0
                or quoted < 0
                or realized < 0
            ):
                invalid.append(index)
                continue
            valid.append(
                {
                    **item,
                    "estimated_value": estimated,
                    "quoted_price": quoted,
                    "realized_value": realized,
                    "accepted": bool(item.get("accepted", False)),
                }
            )

        grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
        for row in valid:
            key = tuple(str(row.get(name, "<missing>")) for name in request.group_by)
            grouped[key].append(row)
        group_statistics = tuple(
            {
                "group": dict(zip(request.group_by, key)),
                **_summarize(rows),
            }
            for key, rows in sorted(grouped.items())
        )
        warnings = ()
        if invalid:
            warnings = (f"ignored {len(invalid)} invalid observations",)
        return AnalysisResult(
            self.spec.name,
            {"overall": _summarize(valid), "groups": group_statistics},
            artifacts=request.artifacts,
            warnings=warnings,
            diagnostics={
                "run_id": context.run_id,
                "invalid_indices": tuple(invalid),
                "group_by": request.group_by,
            },
        )


__all__ = ["ValueRealizationAnalyzer"]
