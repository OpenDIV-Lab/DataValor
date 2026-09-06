"""Audio metadata, clipping and silence metrics."""

from __future__ import annotations

import math

from datavalor.core import ComponentSpec

from ._modal_utils import result, rows
from .interfaces import QualityMetric
from .models import ScoreDirection


class AudioMetadataQualityMetric(QualityMetric):
    """Validate duration, sample rate, channel count and codec metadata."""

    def __init__(self, min_duration=0.1, sample_rates=(8000, 16000, 44100, 48000), channels=(1, 2)):
        self.min_duration = float(min_duration)
        self.sample_rates = {int(item) for item in sample_rates}
        self.channels = {int(item) for item in channels}

    @property
    def spec(self):
        return ComponentSpec("audio.metadata_quality", "1.0.0", "data_eval", "quality_metric", capabilities=("audio", "metadata"))

    def compute(self, product, request, context):
        data = rows(product, request)
        invalid = []
        for index, row in enumerate(data):
            duration, rate, channels = _num(row.get("duration")), _num(row.get("sample_rate")), _num(row.get("channels"))
            reasons = []
            if duration is None or duration < self.min_duration:
                reasons.append("duration")
            if self.sample_rates and (rate is None or int(rate) not in self.sample_rates):
                reasons.append("sample_rate")
            if self.channels and (channels is None or int(channels) not in self.channels):
                reasons.append("channels")
            if reasons:
                invalid.append({"row": index, "reasons": tuple(reasons)})
        return result(self.spec.name, "audio_metadata", request, product, 1 - len(invalid) / len(data) if data else 0.0, ScoreDirection.HIGHER_IS_BETTER, context, statistics={"record_count": len(data), "invalid_count": len(invalid)}, evidence_items=invalid)


class AudioClippingRateMetric(QualityMetric):
    """Fraction of PCM samples at or beyond the configured clipping threshold."""

    def __init__(self, samples_field="samples", threshold=0.99):
        self.samples_field, self.threshold = samples_field, float(threshold)
        if not 0 < self.threshold <= 1:
            raise ValueError("clipping threshold must be in (0, 1]")

    @property
    def spec(self):
        return ComponentSpec("audio.clipping_rate", "1.0.0", "data_eval", "quality_metric", capabilities=("audio", "signal"))

    def compute(self, product, request, context):
        data = rows(product, request)
        samples = [_num(value) for row in data for value in row.get(self.samples_field, ())]
        samples = [value for value in samples if value is not None]
        clipped = sum(abs(value) >= self.threshold for value in samples)
        return result(self.spec.name, "clipping", request, product, clipped / len(samples) if samples else 0.0, ScoreDirection.LOWER_IS_BETTER, context, statistics={"sample_count": len(samples), "clipped_count": clipped, "threshold": self.threshold})


class AudioSilenceRateMetric(QualityMetric):
    """Fraction of samples below an absolute amplitude threshold."""

    def __init__(self, samples_field="samples", threshold=0.01):
        self.samples_field, self.threshold = samples_field, float(threshold)
        if self.threshold < 0:
            raise ValueError("silence threshold must be non-negative")

    @property
    def spec(self):
        return ComponentSpec("audio.silence_rate", "1.0.0", "data_eval", "quality_metric", capabilities=("audio", "signal"))

    def compute(self, product, request, context):
        data = rows(product, request)
        rates = []
        evidence = []
        for index, row in enumerate(data):
            samples = [_num(value) for value in row.get(self.samples_field, ())]
            samples = [value for value in samples if value is not None]
            silent = sum(abs(value) <= self.threshold for value in samples)
            rate = silent / len(samples) if samples else 1.0
            rates.append(rate)
            if rate > 0.8:
                evidence.append({"row": index, "silence_rate": rate})
        return result(self.spec.name, "silence", request, product, sum(rates) / len(rates) if rates else 0.0, ScoreDirection.LOWER_IS_BETTER, context, statistics={"record_count": len(data), "high_silence_count": len(evidence), "threshold": self.threshold}, evidence_items=evidence)


def _num(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


__all__ = ["AudioClippingRateMetric", "AudioMetadataQualityMetric", "AudioSilenceRateMetric"]
