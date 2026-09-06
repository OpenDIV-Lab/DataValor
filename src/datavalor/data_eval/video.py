"""Video metadata and temporal quality metrics.

The lightweight implementation operates on manifest rows and optional sampled
frame vectors. A CV backend can provide the same fields without changing the
DataValor metric contract.
"""

from __future__ import annotations

import math
from statistics import mean, pstdev

from datavalor.core import ComponentSpec

from ._modal_utils import clamp, result, rows
from .interfaces import QualityMetric
from .models import ScoreDirection


def get_video_metadata(row):
    """Normalize common ffprobe-style metadata keys."""
    return {
        "duration": _num(row.get("duration", row.get("duration_sec"))),
        "fps": _num(row.get("fps", row.get("frame_rate"))),
        "width": _num(row.get("width")),
        "height": _num(row.get("height")),
        "frames": _num(row.get("frames", row.get("frame_count"))),
        "codec": row.get("codec"),
    }


def iter_sampled_frames(row, max_frames=16):
    """Yield manifest-provided sampled frames, capped deterministically."""
    frames = row.get("frames_data", row.get("sampled_frames", ()))
    if not isinstance(frames, (list, tuple)):
        return iter(())
    step = max(1, math.ceil(len(frames) / max(1, int(max_frames))))
    return iter(frames[::step][: max(1, int(max_frames))])


class VideoFormatProbe(QualityMetric):
    """Check playable duration, dimensions, frame rate and codec fields."""

    def __init__(self, min_duration=0.1, min_width=16, min_height=16, min_fps=1):
        self.min_duration, self.min_width, self.min_height, self.min_fps = map(float, (min_duration, min_width, min_height, min_fps))

    @property
    def spec(self):
        return ComponentSpec("video.format_probe", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "metadata"))

    def compute(self, product, request, context):
        data = rows(product, request)
        invalid = []
        for index, row in enumerate(data):
            meta = get_video_metadata(row)
            reasons = []
            if meta["duration"] is None or meta["duration"] < self.min_duration:
                reasons.append("duration")
            if meta["width"] is None or meta["width"] < self.min_width:
                reasons.append("width")
            if meta["height"] is None or meta["height"] < self.min_height:
                reasons.append("height")
            if meta["fps"] is None or meta["fps"] < self.min_fps:
                reasons.append("fps")
            if reasons:
                invalid.append({"row": index, "reasons": tuple(reasons)})
        return result(self.spec.name, "video_format", request, product, 1 - len(invalid) / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "invalid_count": len(invalid)}, evidence_items=invalid)


class VideoMotionMetadata(QualityMetric):
    """Summarize motion magnitudes from frame-difference or manifest values."""

    @property
    def spec(self):
        return ComponentSpec("video.motion_metadata", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "motion"))

    def compute(self, product, request, context):
        data = rows(product, request)
        values = [_num(row.get("motion_score")) for row in data]
        values = [value for value in values if value is not None]
        return result(self.spec.name, "motion", request, product, mean(values) if values else None, ScoreDirection.DESCRIPTIVE, context, unit="score", statistics={"record_count": len(data), "motion": _describe(values)})


class VideoOpticalFlowMotionScore(QualityMetric):
    """Estimate temporal motion from adjacent sampled frame vectors."""

    @property
    def spec(self):
        return ComponentSpec("video.optical_flow_motion", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "motion", "frame_vectors"))

    def compute(self, product, request, context):
        data = rows(product, request)
        scores = []
        for row in data:
            frames = list(iter_sampled_frames(row))
            differences = [_distance(frames[index], frames[index - 1]) for index in range(1, len(frames))]
            if differences:
                scores.append(mean(differences))
        return result(self.spec.name, "motion", request, product, mean(scores) if scores else None, ScoreDirection.DESCRIPTIVE, context, unit="mean_frame_distance", statistics={"video_count": len(data), "scored_videos": len(scores), "mean_motion": mean(scores) if scores else None})


class VideoSceneSegmentationScore(QualityMetric):
    """Score whether scene boundaries are available and internally sorted."""

    @property
    def spec(self):
        return ComponentSpec("video.scene_segmentation", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "scenes"))

    def compute(self, product, request, context):
        data = rows(product, request)
        valid = 0
        evidence = []
        for index, row in enumerate(data):
            boundaries = row.get("scene_boundaries", ())
            numeric = [_num(value) for value in boundaries] if isinstance(boundaries, (list, tuple)) else []
            ok = bool(numeric) and all(value is not None for value in numeric) and numeric == sorted(numeric)
            valid += ok
            if not ok:
                evidence.append({"row": index, "reason": "missing_or_unsorted_boundaries"})
        return result(self.spec.name, "scene_segmentation", request, product, valid / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "valid_count": valid}, evidence_items=evidence)


class VideoTemporalSSIMConsistency(QualityMetric):
    """Average adjacent-frame similarity when SSIM-like values are supplied."""

    @property
    def spec(self):
        return ComponentSpec("video.temporal_ssim", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "temporal_consistency"))

    def compute(self, product, request, context):
        data = rows(product, request)
        values = [value for row in data for value in (_num(item) for item in row.get("temporal_ssim", ())) if value is not None]
        return result(self.spec.name, "temporal_consistency", request, product, clamp(mean(values)) if values else None, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"video_count": len(data), "pair_count": len(values), "mean_ssim": mean(values) if values else None, "std_ssim": pstdev(values) if len(values) > 1 else 0.0})


class VideoPrivacyCVScore(QualityMetric):
    """Privacy risk score from supplied face/license-plate detection counts."""

    @property
    def spec(self):
        return ComponentSpec("video.privacy_cv", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "privacy"))

    def compute(self, product, request, context):
        data = rows(product, request)
        risks = []
        evidence = []
        for index, row in enumerate(data):
            faces = max(0, int(_num(row.get("face_count", 0)) or 0))
            plates = max(0, int(_num(row.get("plate_count", 0)) or 0))
            blurred = max(0, int(_num(row.get("blurred_private_count", 0)) or 0))
            private = faces + plates
            risk = (private - min(private, blurred)) / private if private else 0.0
            risks.append(risk)
            if risk > 0:
                evidence.append({"row": index, "faces": faces, "plates": plates, "blurred": blurred, "risk": risk})
        return result(self.spec.name, "privacy_risk", request, product, mean(risks) if risks else 0.0, ScoreDirection.LOWER_IS_BETTER, context, statistics={"record_count": len(data), "private_detection_count": len(evidence)}, evidence_items=evidence)


class VideoBasicCleanliness(VideoFormatProbe):
    """Compatibility metric combining format validity and explicit corruption flags."""

    @property
    def spec(self):
        return ComponentSpec("video.basic_cleanliness", "1.0.0", "data_eval", "quality_metric", capabilities=("video", "cleanliness"))

    def compute(self, product, request, context):
        base = super().compute(product, request, context)
        data = rows(product, request)
        corrupt = sum(bool(row.get("corrupt", False)) for row in data)
        return result(self.spec.name, "cleanliness", request, product, clamp((base.value or 0.0) - corrupt / len(data) if data else 0.0), ScoreDirection.HIGHER_IS_BETTER, context, statistics={**base.statistics, "corrupt_count": corrupt})


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _distance(left, right):
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)) and len(left) == len(right):
        return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)))
    return abs((_num(left) or 0.0) - (_num(right) or 0.0))


def _describe(values):
    return {"count": len(values), "mean": mean(values) if values else None, "std": pstdev(values) if len(values) > 1 else 0.0}


__all__ = ["VideoBasicCleanliness", "VideoFormatProbe", "VideoMotionMetadata", "VideoOpticalFlowMotionScore", "VideoPrivacyCVScore", "VideoSceneSegmentationScore", "VideoTemporalSSIMConsistency", "get_video_metadata", "iter_sampled_frames"]
