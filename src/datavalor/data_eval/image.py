"""Image metadata and pixel-quality metrics.

Metrics consume rows containing metadata (width, height, channels, format) or
an optional ``pixels`` nested sequence. No PIL/OpenCV dependency is required;
those can be added behind adapters without changing the result contract.
"""

from __future__ import annotations

import math
from statistics import mean

from datavalor.core import ComponentSpec

from ._modal_utils import clamp, result, rows
from .interfaces import QualityMetric
from .models import ScoreDirection


class ImageMetadataQualityMetric(QualityMetric):
    """Validate dimensions, channels, format and file size metadata."""

    def __init__(self, min_width=1, min_height=1, allowed_formats=(), expected_channels=()):
        self.min_width, self.min_height = int(min_width), int(min_height)
        self.allowed_formats = {str(item).casefold() for item in allowed_formats}
        self.expected_channels = {int(item) for item in expected_channels}

    @property
    def spec(self):
        return ComponentSpec("image.metadata_quality", "1.0.0", "data_eval", "quality_metric", capabilities=("image", "metadata"))

    def compute(self, product, request, context):
        data = rows(product, request)
        invalid = []
        for index, row in enumerate(data):
            width, height = _number(row.get("width")), _number(row.get("height"))
            channels = _number(row.get("channels"))
            fmt = str(row.get("format", "")).casefold()
            reasons = []
            if width is None or width < self.min_width:
                reasons.append("width")
            if height is None or height < self.min_height:
                reasons.append("height")
            if self.allowed_formats and fmt not in self.allowed_formats:
                reasons.append("format")
            if self.expected_channels and (channels is None or int(channels) not in self.expected_channels):
                reasons.append("channels")
            if reasons:
                invalid.append({"row": index, "reasons": tuple(reasons)})
        return result(self.spec.name, "image_metadata", request, product, 1 - len(invalid) / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "invalid_count": len(invalid), "min_width": self.min_width, "min_height": self.min_height}, evidence_items=invalid)


class ImageAspectRatioConsistencyMetric(QualityMetric):
    """Quality score based on dispersion around the median aspect ratio."""

    def __init__(self, tolerance=0.05):
        self.tolerance = float(tolerance)
        if self.tolerance < 0:
            raise ValueError("aspect ratio tolerance must be non-negative")

    @property
    def spec(self):
        return ComponentSpec("image.aspect_ratio_consistency", "1.0.0", "data_eval", "quality_metric", capabilities=("image", "geometry"))

    def compute(self, product, request, context):
        data = rows(product, request)
        ratios = [(_number(row.get("width")) / _number(row.get("height"))) for row in data if _number(row.get("width")) and _number(row.get("height"))]
        if not ratios:
            return result(self.spec.name, "aspect_ratio", request, product, 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"valid_count": 0})
        center = sorted(ratios)[len(ratios) // 2]
        deviations = [abs(ratio - center) / center if center else 1.0 for ratio in ratios]
        return result(self.spec.name, "aspect_ratio", request, product, clamp(sum(deviation <= self.tolerance for deviation in deviations) / len(deviations)), ScoreDirection.HIGHER_IS_BETTER, context, statistics={"valid_count": len(ratios), "median_ratio": center, "mean_relative_deviation": mean(deviations), "tolerance": self.tolerance})


class ImagePixelValidityMetric(QualityMetric):
    """Check optional nested pixels for finite values in [0, 1] or [0, 255]."""

    @property
    def spec(self):
        return ComponentSpec("image.pixel_validity", "1.0.0", "data_eval", "quality_metric", capabilities=("image", "pixels"))

    def compute(self, product, request, context):
        data = rows(product, request)
        invalid = []
        checked = 0
        for index, row in enumerate(data):
            values = _flatten(row.get("pixels", ()))
            for value in values:
                checked += 1
                if not math.isfinite(value) or value < 0 or value > 255:
                    invalid.append({"row": index, "value": value})
        return result(self.spec.name, "pixel_validity", request, product, 1 - len(invalid) / checked if checked else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "pixel_count": checked, "invalid_count": len(invalid)}, evidence_items=invalid)


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _flatten(value):
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in _flatten(child)]
    converted = _number(value)
    return [] if converted is None else [converted]


__all__ = ["ImageAspectRatioConsistencyMetric", "ImageMetadataQualityMetric", "ImagePixelValidityMetric"]
