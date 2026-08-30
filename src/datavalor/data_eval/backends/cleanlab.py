"""Cleanlab-backed issue detection mapped to DataValor quality evidence.

The adapter uses the public ``Datalab`` API when available and falls back to
the stable ``cleanlab.filter.find_label_issues`` function for older releases.
No Cleanlab object escapes the adapter boundary.
"""

from __future__ import annotations

from typing import Any, Callable

from datavalor.core import ComponentSpec, DataProduct, Evidence, RunContext, require_capability

from ..interfaces import QualityMetric
from ..models import EvaluationRequest, MetricResult, ScoreDirection
from ._utils import records_for, rows_from_external


class CleanlabQualityMetric(QualityMetric):
    """Find label issues (or other Datalab issues) and return an issue-rate metric."""

    def __init__(
        self,
        *,
        labels_field: str = "label",
        pred_probs_field: str | None = "pred_probs",
        issue_type: str = "label",
        detector: Callable[..., Any] | None = None,
    ) -> None:
        self.labels_field = labels_field
        self.pred_probs_field = pred_probs_field
        self.issue_type = issue_type
        self.detector = detector

    @property
    def spec(self) -> ComponentSpec:
        return ComponentSpec(
            "cleanlab.issues", "0.1.0", "data_eval", "quality_metric",
            capabilities=("label_issues", "outliers", "duplicates"),
            requires=("cleanlab>=2.0",),
            description="Cleanlab issue detection converted to DataValor evidence",
        )

    def _detect(self, rows: list[dict[str, Any]], request: EvaluationRequest) -> Any:
        if self.detector is not None:
            return self.detector(rows, request=request, issue_type=self.issue_type)
        cleanlab = require_capability("cleanlab", "cleanlab", distribution="cleanlab", extra="quality")
        labels = [row.get(self.labels_field) for row in rows]
        probs = [row.get(self.pred_probs_field) for row in rows] if self.pred_probs_field else None
        # Datalab is the maintained high-level API.  Its constructor accepts a
        # labels sequence and find_issues() returns a table-like object.
        datalab_cls = getattr(cleanlab, "Datalab", None)
        if datalab_cls is not None and self.issue_type == "label":
            data = request.options.get("data", rows)
            # Cleanlab's documented Datalab input is a pandas DataFrame.  Keep
            # pandas optional and only construct it when the backend is used.
            if data is rows:
                try:
                    pandas = require_capability("pandas", "pandas", distribution="pandas", extra="quality")
                    data = pandas.DataFrame(rows)
                except Exception:
                    data = rows
            try:
                lab = datalab_cls(data=data, labels=labels)
            except TypeError:
                lab = datalab_cls(data=data, label_name=self.labels_field)
            lab.find_issues()
            getter = getattr(lab, "get_issues", None)
            return getter() if callable(getter) else getattr(lab, "issues", None)
        filt = getattr(cleanlab, "filter", None)
        fn = getattr(filt, "find_label_issues", None) if filt is not None else None
        if fn is None:
            raise RuntimeError("installed cleanlab does not expose Datalab or find_label_issues")
        return fn(labels=labels, pred_probs=probs) if probs is not None else fn(labels=labels)

    def compute(self, product: DataProduct, request: EvaluationRequest, context: RunContext) -> MetricResult:
        rows = records_for(product, request.options)
        external = self._detect(rows, request)
        issue_rows = rows_from_external(external)
        # Cleanlab tables commonly contain ``is_label_issue`` and ``label_score``.
        if issue_rows:
            flagged = [r for r in issue_rows if bool(r.get("is_label_issue", r.get("is_issue", False)))]
            if not flagged and isinstance(external, (list, tuple, set)):
                flagged = [r for r in issue_rows if r]
            issue_count = len(flagged)
        elif hasattr(external, "tolist"):
            values = external.tolist()
            issue_count = sum(bool(v) for v in values) if isinstance(values, list) else 0
        elif isinstance(external, (list, tuple)) and external and all(isinstance(v, bool) for v in external):
            issue_count = sum(external)
        else:
            issue_count = 0
        rate = issue_count / len(rows) if rows else 0.0
        evidence = tuple(
            Evidence("cleanlab.issue", summary=f"样本 {i} 被标记为 {self.issue_type} 问题", metadata=dict(row))
            for i, row in enumerate(issue_rows)
            if bool(row.get("is_label_issue", row.get("is_issue", True)))
        )
        return MetricResult(
            name=f"cleanlab.{self.issue_type}_issue_rate",
            dimension="data_quality",
            scope=request.scope,
            value=max(0.0, min(1.0, rate)),
            direction=ScoreDirection.LOWER_IS_BETTER,
            unit="ratio",
            target_id=product.product_id,
            statistics={"record_count": len(rows), "issue_count": issue_count, "issue_rate": rate},
            evidence=evidence,
            diagnostics={"run_id": context.run_id, "backend": "cleanlab", "issue_type": self.issue_type},
        )


CleanlabAdapter = CleanlabQualityMetric

__all__ = ["CleanlabQualityMetric", "CleanlabAdapter"]
