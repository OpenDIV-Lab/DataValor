import pytest

from datavalor.core import DataProduct, DataReference, RunContext
from datavalor.data_eval import (
    AudioClippingRateMetric,
    AudioMetadataQualityMetric,
    AudioSilenceRateMetric,
    EvaluationRequest,
    ImageAspectRatioConsistencyMetric,
    ImageMetadataQualityMetric,
    ImagePixelValidityMetric,
    MultimodalAlignmentMetric,
    MultimodalPackageIntegrityMetric,
    TabularLabelBalanceMetric,
    TabularNumericStatisticsMetric,
    TabularOutlierRateMetric,
    TabularSchemaConsistencyMetric,
    TextLengthQualityMetric,
    TextLexicalDiversityMetric,
    TextRepetitionRateMetric,
    VideoBasicCleanliness,
    VideoFormatProbe,
    VideoOpticalFlowMotionScore,
    VideoPrivacyCVScore,
    VideoSceneSegmentationScore,
    VideoTemporalSSIMConsistency,
)


def _product():
    return DataProduct("p", "fixture", DataReference("memory://fixture", "json"), "owner")


def _request(records):
    return EvaluationRequest(options={"records": records})


def test_tabular_schema_numeric_outlier_and_balance_metrics():
    records = [{"value": 1, "label": "a"}, {"value": 2, "label": "a"}, {"value": 3, "label": "b"}, {"value": 100, "label": "b"}]
    req = _request(records)
    assert TabularSchemaConsistencyMetric(required_fields=("value",), field_types={"value": "number"}).compute(_product(), req, RunContext("r")).value == 1
    numeric = TabularNumericStatisticsMetric("value").compute(_product(), req, RunContext("r"))
    assert numeric.statistics["mean"] == 26.5
    outlier = TabularOutlierRateMetric("value").compute(_product(), req, RunContext("r"))
    assert outlier.statistics["outlier_count"] == 1
    balance = TabularLabelBalanceMetric().compute(_product(), req, RunContext("r"))
    assert balance.value == 1.0


def test_text_metrics_detect_length_diversity_and_repetition():
    req = _request([{"text": "alpha beta alpha"}, {"text": "gamma delta"}])
    assert TextLexicalDiversityMetric().compute(_product(), req, RunContext("r")).value > 0.5
    assert TextLengthQualityMetric(max_tokens=3).compute(_product(), req, RunContext("r")).value == 1.0
    repetition = TextRepetitionRateMetric().compute(_product(), req, RunContext("r"))
    assert repetition.value > 0


def test_image_metrics_validate_manifest_and_pixels():
    records = [{"width": 100, "height": 100, "format": "png", "channels": 3, "pixels": [0, 1, 255]}, {"width": 200, "height": 100, "format": "jpg", "channels": 3, "pixels": [0, 300]}]
    req = _request(records)
    metadata = ImageMetadataQualityMetric(allowed_formats=("png",), expected_channels=(3,)).compute(_product(), req, RunContext("r"))
    assert metadata.value == 0.5
    ratio = ImageAspectRatioConsistencyMetric(tolerance=0.1).compute(_product(), req, RunContext("r"))
    assert ratio.value == 0.5
    pixels = ImagePixelValidityMetric().compute(_product(), req, RunContext("r"))
    assert pixels.statistics["invalid_count"] == 1


def test_audio_metrics_cover_metadata_clipping_and_silence():
    records = [{"duration": 2, "sample_rate": 16000, "channels": 1, "samples": [0, 0.5, 1]}, {"duration": 0, "sample_rate": 8000, "channels": 2, "samples": [0, 0]}]
    req = _request(records)
    assert AudioMetadataQualityMetric().compute(_product(), req, RunContext("r")).value == 0.5
    assert AudioClippingRateMetric().compute(_product(), req, RunContext("r")).statistics["clipped_count"] == 1
    assert AudioSilenceRateMetric().compute(_product(), req, RunContext("r")).value > 0.5


def test_video_metrics_use_manifest_frames_and_privacy_fields():
    records = [{"duration": 2, "fps": 24, "width": 640, "height": 480, "frames_data": [[0, 0], [1, 0], [1, 2]], "scene_boundaries": [0, 1], "temporal_ssim": [0.9, 0.8], "face_count": 2, "blurred_private_count": 1}, {"duration": 0, "fps": 0, "width": 0, "height": 0, "scene_boundaries": [2, 1]}]
    req = _request(records)
    assert VideoFormatProbe().compute(_product(), req, RunContext("r")).value == 0.5
    assert VideoOpticalFlowMotionScore().compute(_product(), req, RunContext("r")).value > 0
    assert VideoSceneSegmentationScore().compute(_product(), req, RunContext("r")).value == 0.5
    assert VideoTemporalSSIMConsistency().compute(_product(), req, RunContext("r")).value == pytest.approx(0.85)
    assert VideoPrivacyCVScore().compute(_product(), req, RunContext("r")).value == pytest.approx(0.25)
    assert VideoBasicCleanliness().compute(_product(), req, RunContext("r")).value == 0.5


def test_multimodal_integrity_and_alignment():
    records = [{"id": "a", "text": "hello", "image": "x", "text_timestamp": 1, "image_timestamp": 1.5}, {"id": "a", "text": "", "image": None, "text_timestamp": 1, "image_timestamp": 4}]
    req = _request(records)
    integrity = MultimodalPackageIntegrityMetric().compute(_product(), req, RunContext("r"))
    assert integrity.statistics["duplicate_id_count"] == 1
    alignment = MultimodalAlignmentMetric(tolerance=1).compute(_product(), req, RunContext("r"))
    assert alignment.value == 0.5
