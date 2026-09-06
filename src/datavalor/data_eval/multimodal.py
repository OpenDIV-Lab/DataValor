"""Cross-modal package integrity and alignment metrics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from datavalor.core import ComponentSpec

from ._modal_utils import clamp, result, rows
from .interfaces import QualityMetric
from .models import ScoreDirection


class MultimodalPackageIntegrityMetric(QualityMetric):
    """Check required modality fields, IDs and optional checksums."""

    def __init__(self, required_modalities=("text", "image")):
        self.required_modalities = tuple(required_modalities)

    @property
    def spec(self):
        return ComponentSpec("multimodal.package_integrity", "1.0.0", "data_eval", "quality_metric", capabilities=("multimodal", "integrity"))

    def compute(self, product, request, context):
        data = rows(product, request)
        invalid = []
        ids = []
        for index, row in enumerate(data):
            record_id = row.get("id", index)
            ids.append(str(record_id))
            missing = [modality for modality in self.required_modalities if row.get(modality) in (None, "", ())]
            checksum = row.get("checksum")
            checksum_ok = True
            if checksum and row.get("payload") is not None:
                canonical = json.dumps(row["payload"], sort_keys=True, ensure_ascii=False, default=str).encode()
                checksum_ok = hashlib.sha256(canonical).hexdigest() == str(checksum)
            if missing or not checksum_ok:
                invalid.append({"row": index, "id": record_id, "missing_modalities": tuple(missing), "checksum_ok": checksum_ok})
        duplicate_ids = [identifier for identifier, count in Counter(ids).items() if count > 1]
        score = 1 - (len(invalid) + len(duplicate_ids)) / max(1, len(data))
        return result(self.spec.name, "package_integrity", request, product, clamp(score), ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "invalid_count": len(invalid), "duplicate_id_count": len(duplicate_ids), "duplicate_ids": duplicate_ids, "required_modalities": self.required_modalities}, evidence_items=invalid)


class MultimodalAlignmentMetric(QualityMetric):
    """Measure temporal alignment between modality timestamps in each record."""

    def __init__(self, timestamp_fields=("text_timestamp", "image_timestamp"), tolerance=1.0):
        self.timestamp_fields, self.tolerance = tuple(timestamp_fields), float(tolerance)
        if self.tolerance < 0:
            raise ValueError("alignment tolerance must be non-negative")

    @property
    def spec(self):
        return ComponentSpec("multimodal.alignment", "1.0.0", "data_eval", "quality_metric", capabilities=("multimodal", "alignment"))

    def compute(self, product, request, context):
        data = rows(product, request)
        valid, errors = 0, []
        for index, row in enumerate(data):
            values = [_num(row.get(field)) for field in self.timestamp_fields]
            if all(value is not None for value in values):
                spread = max(values) - min(values)
                if spread <= self.tolerance:
                    valid += 1
                else:
                    errors.append({"row": index, "spread": spread})
            else:
                errors.append({"row": index, "reason": "missing_timestamp"})
        return result(self.spec.name, "cross_modal_alignment", request, product, valid / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "aligned_count": valid, "misaligned_count": len(errors), "tolerance": self.tolerance}, evidence_items=errors)


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["MultimodalAlignmentMetric", "MultimodalPackageIntegrityMetric"]
